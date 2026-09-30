import os
import re
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError
from sqlalchemy import select

from resolveflow.agent.providers import Baseline, Fixture, Provider
from resolveflow.domain.common import DomainError, Scope
from resolveflow.jobs.queue import event, fence
from resolveflow.settings import get_settings
from resolveflow.storage.checkpoints import FencedSaver
from resolveflow.storage.models import Approval, Effect, Proposal, Run, now, record
from resolveflow.tools.contracts import TOOLS, FinalResponse
from resolveflow.tools.executor import ToolExecutor


class AgentState(TypedDict, total=False):
    run_id: str
    decision: dict[str, Any]
    observations: list[dict]
    history: list[dict]
    tool_calls: int
    model_calls: int
    repairs: int
    active_seconds: float
    total_tokens: int
    token_usage_known: bool
    fingerprints: dict[str, int]
    final: dict
    route: str
    effect: dict


def final_for(session, run, outcome, explanation, evidence=None):
    effects = list(session.scalars(select(Effect).where(Effect.run_id == run.id)))
    return FinalResponse(
        outcome=outcome,
        explanation=explanation,
        evidence_ids=evidence
        or [o["observation_id"] for o in run.state.get("observations", [])][-12:],
        missing_information=(run.clarification or {}).get("fields", []),
        proposal_id=run.proposal_id,
        action_ids=[e.id for e in effects],
    ).model_dump() | {
        "mode": run.mode,
        "run_id": run.id,
        "committed_effects": [record(e) for e in effects],
        "simulated": True,
    }


class Workflow:
    def __init__(self, factory, saver, run_id, owner, provider=None):
        self.factory, self.run_id, self.owner = factory, run_id, owner
        with factory() as s:
            run = s.get(Run, run_id)
            self.scope = Scope(run.actor, "operator", run.workspace, (run.customer_id,))
            self.adapter: Any = (
                provider
                or {"fixture": Fixture, "baseline": Baseline, "provider": Provider}[run.mode]()
            )
        self.tools = ToolExecutor(factory, self.scope, run_id, owner)
        graph = StateGraph(AgentState)
        graph.add_node("step", self.step)
        graph.add_node("wait_information", self.wait_information)
        graph.add_node("wait_approval", self.wait_approval)
        graph.add_node("action", self.action)
        graph.add_node("finish", self.finish)
        graph.add_edge(START, "step")
        graph.add_conditional_edges(
            "step",
            lambda state: state["route"],
            {
                "step": "step",
                "information": "wait_information",
                "approval": "wait_approval",
                "finish": "finish",
            },
        )
        graph.add_edge("wait_information", "step")
        graph.add_conditional_edges(
            "wait_approval", lambda state: state["route"], {"action": "action", "finish": "finish"}
        )
        graph.add_edge("action", "finish")
        graph.add_edge("finish", END)
        self.graph = graph.compile(checkpointer=FencedSaver(saver, factory, run_id, owner))

    def save(self, state):
        with self.factory.begin() as s:
            run, _ = fence(s, self.run_id, self.owner)
            run.state = dict(state)
            run.updated_at = now()

    def step(self, incoming):
        # Business state is authoritative for crash windows between transaction and checkpoint.
        with self.factory.begin() as s:
            run, job = fence(s, self.run_id, self.owner)
            state = dict(run.state or incoming)
            run.status = "recovering" if job.stage == "recovering" else "running"
            if run.proposal_id:
                proposal = s.get(Proposal, run.proposal_id)
                state["route"] = (
                    "finish" if proposal.payload["action"] == "escalation" else "approval"
                )
                state["final"] = {
                    "outcome": "escalated",
                    "explanation": "Case escalated for review.",
                }
                return state
        cfg = get_settings()
        started = time.perf_counter()
        try:
            if (
                state.get("tool_calls", 0) >= cfg.max_tool_calls
                or state.get("model_calls", 0) >= cfg.max_model_calls
                or state.get("active_seconds", 0) >= cfg.max_active_seconds
                or state.get("total_tokens", 0) >= cfg.max_total_tokens
            ):
                raise DomainError(
                    "budget_exhausted", "Investigation budget exhausted; escalate for review"
                )
            if run.mode == "provider":
                state["model_calls"] = state.get("model_calls", 0) + 1
                self.save(state)  # Reserve budget before an unknown provider outcome.
            decision = self.adapter.next(run, state)
            state["decision"] = decision
            if metadata := decision.get("metadata"):
                usage = metadata.get("usage")
                state["token_usage_known"] = (
                    state.get("token_usage_known", True) and usage is not None
                )
                state["total_tokens"] = state.get("total_tokens", 0) + (usage or {}).get(
                    "total_tokens", 0
                )
                with self.factory.begin() as s:
                    fence(s, self.run_id, self.owner)
                    event(s, self.run_id, "provider_call", metadata)
            if "final" in decision:
                final = FinalResponse.model_validate(decision["final"])
                known = {o["observation_id"] for o in state.get("observations", [])}
                if not set(final.evidence_ids).issubset(known):
                    raise DomainError(
                        "invalid_model_output", "Final response cites unknown evidence"
                    )
                known_records = {
                    str(o["data"].get("id", "")) for o in state.get("observations", [])
                }
                mentioned = set(re.findall(r"\b(?:ORD|POL)-[A-Za-z0-9]+\b", final.explanation))
                if not mentioned.issubset(known_records):
                    raise DomainError(
                        "invalid_model_output", "Final explanation invents record references"
                    )
                if final.action_ids or final.proposal_id:
                    raise DomainError(
                        "invalid_model_output",
                        "Only the server constructs action and proposal references",
                    )
                if final.outcome not in ("policy_ineligible", "escalated"):
                    raise DomainError(
                        "invalid_model_output",
                        "Final outcome is inconsistent with persisted business state",
                    )
                if final.outcome == "policy_ineligible" and not any(
                    o["tool"] == "check_resolution_eligibility"
                    and o["data"]["status"] == "ineligible"
                    for o in state.get("observations", [])
                ):
                    raise DomainError(
                        "invalid_model_output", "Policy rejection lacks a deterministic check"
                    )
                state.update(route="finish", final=final.model_dump())
            else:
                from resolveflow.domain.common import canonical

                if decision["name"] not in TOOLS:
                    raise DomainError("invalid_arguments", "Unknown tool", 422)
                fingerprint = canonical(
                    {"name": decision["name"], "args": decision["arguments"], "facts": run.facts}
                )
                fingerprints = dict(state.get("fingerprints", {}))
                fingerprints[fingerprint] = fingerprints.get(fingerprint, 0) + 1
                state["fingerprints"] = fingerprints
                if fingerprints[fingerprint] > 2:
                    raise DomainError("budget_exhausted", "Repeated identical tool calls stopped")
                state["tool_calls"] = state.get("tool_calls", 0) + 1
                self.save(state)  # Store stable call identity before a side effect.
                result = self.tools.call(
                    decision["name"], decision["arguments"], decision["call_id"]
                )
                state["observations"] = [*state.get("observations", []), result]
                state["history"] = [*state.get("history", []), {**decision, "result": result}]
                state["route"] = {
                    "request_clarification": "information",
                    "propose_resolution": "approval",
                }.get(decision["name"], "step")
                if (
                    decision["name"] == "propose_resolution"
                    and result["data"]["payload"]["action"] == "escalation"
                ):
                    state.update(
                        route="finish",
                        final={
                            "outcome": "escalated",
                            "explanation": "Support case escalated with cited evidence.",
                        },
                    )
        except (DomainError, ValidationError) as exc:
            code = exc.code if isinstance(exc, DomainError) else "invalid_model_output"
            message = (
                exc.message
                if isinstance(exc, DomainError)
                else "Model response failed typed validation"
            )
            if code in ("lost_lease", "cancelled"):
                raise
            with self.factory.begin() as s:
                fence(s, self.run_id, self.owner)
                event(
                    s,
                    self.run_id,
                    "tool_error" if state.get("decision", {}).get("name") else "model_error",
                    {"code": code, "message": message},
                )
            state["repairs"] = state.get("repairs", 0) + 1
            state["history"] = [
                *state.get("history", []),
                {"error": {"code": code, "message": message}},
            ]
            if (
                (run.mode == "provider" and code in ("invalid_arguments", "invalid_model_output"))
                or code == "transient_failure"
            ) and state["repairs"] <= 2:
                state["route"] = "step"
            else:
                state.update(
                    route="finish",
                    final={
                        "outcome": "provider_unavailable"
                        if code == "provider_unavailable"
                        else "invalid_model_output"
                        if code in ("invalid_arguments", "invalid_model_output")
                        else "escalated",
                        "explanation": message,
                    },
                )
        state["active_seconds"] = state.get("active_seconds", 0) + time.perf_counter() - started
        self.save(state)
        return state

    def wait_information(self, state):
        with self.factory.begin() as s:
            run, _ = fence(s, self.run_id, self.owner)
            if run.clarification:
                run.status = "awaiting_information"
                run.final = final_for(s, run, "needs_information", run.clarification["question"])
        interrupt({"kind": "information"})
        return dict(state, route="step")

    def wait_approval(self, state):
        with self.factory.begin() as s:
            run, _ = fence(s, self.run_id, self.owner)
            approval = s.scalar(select(Approval).where(Approval.proposal_id == run.proposal_id))
            if not approval:
                run.status = "awaiting_approval"
                run.final = final_for(
                    s,
                    run,
                    "awaiting_approval",
                    "Exact simulated proposal is pending supervisor review.",
                )
        interrupt({"kind": "approval"})
        with self.factory.begin() as s:
            run, _ = fence(s, self.run_id, self.owner)
            approval = s.scalar(select(Approval).where(Approval.proposal_id == run.proposal_id))
            if not approval:
                raise DomainError("conflict", "Resume has no persisted approval decision")
            if approval.decision == "reject":
                return dict(
                    state,
                    route="finish",
                    final={
                        "outcome": "approval_rejected",
                        "explanation": "Supervisor rejected the proposal; no protected action was committed.",
                    },
                )
        return dict(state, route="action")

    def action(self, state):
        from resolveflow.approvals.service import execute

        started = time.perf_counter()
        try:
            with self.factory.begin() as s:
                effect = execute(s, self.scope, self.run_id, self.owner)
            # Named fault only for developer recovery scripts; never accepted via HTTP.
            if os.getenv("RESOLVEFLOW_TEST_CRASH") == "after_business_commit":
                os._exit(77)
            return dict(
                state,
                effect=effect,
                final={
                    "outcome": "resolved",
                    "explanation": "Supervisor-approved simulated action committed. The sandbox ledger is the source of truth.",
                },
                active_seconds=state.get("active_seconds", 0) + time.perf_counter() - started,
            )
        except DomainError as exc:
            if exc.code in ("lost_lease", "cancelled"):
                raise
            with self.factory.begin() as s:
                run, _ = fence(s, self.run_id, self.owner)
                p = s.get(Proposal, run.proposal_id)
                p.status = "invalidated"
                event(s, self.run_id, "action_blocked", {"code": exc.code, "message": exc.message})
            return dict(state, final={"outcome": "execution_failed", "explanation": exc.message})

    def finish(self, state):
        with self.factory.begin() as s:
            run, _ = fence(s, self.run_id, self.owner)
            final = state["final"]
            run.final = final_for(
                s, run, final["outcome"], final["explanation"], final.get("evidence_ids")
            )
            run.status = {
                "resolved": "completed",
                "policy_ineligible": "completed",
                "approval_rejected": "rejected",
                "escalated": "escalated",
            }.get(final["outcome"], "failed")
            run.state = dict(state)
            event(
                s,
                run.id,
                "finished",
                {"status": run.status, "outcome": final["outcome"], "mode": run.mode},
            )
        return state

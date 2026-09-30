import json
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import select

from resolveflow.domain.common import DomainError, canonical, clock, instant
from resolveflow.domain.policy import applicable_policy, authorized_order, eligibility
from resolveflow.jobs.queue import event, fence
from resolveflow.storage.models import (
    Case,
    LineItem,
    Operation,
    Payment,
    Proposal,
    Shipment,
    record,
    uid,
)
from resolveflow.tools.contracts import TOOLS


class ToolExecutor:
    def __init__(self, factory, scope, run_id, owner):
        self.factory, self.scope, self.run_id, self.owner = factory, scope, run_id, owner

    def call(self, name, raw, call_id):
        if name not in TOOLS:
            raise DomainError("invalid_arguments", "Unknown tool", 422)
        try:
            args = TOOLS[name][0].model_validate(raw)
        except ValidationError as exc:
            raise DomainError(
                "invalid_arguments", "Arguments do not match the tool schema", 422
            ) from exc
        payload_hash = canonical({"name": name, "args": args.model_dump()})
        op_id = f"tool:{self.run_id}:{call_id}"
        with self.factory.begin() as s:
            run, _ = fence(s, self.run_id, self.owner)
            previous = s.get(Operation, op_id)
            if previous:
                if previous.request_hash != payload_hash:
                    raise DomainError("conflict", "Tool-call identity reused with changed payload")
                return previous.result
            result = self._dispatch(s, run, name, args)
            result = {
                "observation_id": f"OBS-{uid()}",
                "observed_at": clock(run).isoformat(),
                "tool": name,
                "data": result,
            }
            if len(json.dumps(result)) > 12000:
                raise DomainError(
                    "invalid_arguments", "Tool output exceeds bounded observation size"
                )
            s.add(
                Operation(
                    id=op_id,
                    run_id=run.id,
                    workspace=self.scope.workspace,
                    request_hash=payload_hash,
                    kind="tool",
                    result=result,
                )
            )
            event(
                s,
                run.id,
                "tool_result",
                {
                    "call_id": call_id,
                    "name": name,
                    "arguments": args.model_dump(),
                    "result": result,
                },
            )
            return result

    def _dispatch(self, s, run, name, args):
        if name == "request_clarification":
            fields = list(dict.fromkeys(args.fields))
            if any(run.facts.get(f) for f in fields):
                raise DomainError(
                    "invalid_arguments", "Clarification asks for an already supplied fact", 422
                )
            run.clarification = {"fields": fields, "question": args.question}
            return run.clarification
        order = authorized_order(s, self.scope, args.order_id)
        if name == "get_order":
            return record(order) | {
                "line_items": [
                    record(x)
                    for x in s.scalars(select(LineItem).where(LineItem.order_id == order.id))
                ],
                "payment": record(s.scalar(select(Payment).where(Payment.order_id == order.id))),
            }
        if name == "get_tracking":
            shipment = s.scalar(select(Shipment).where(Shipment.order_id == order.id))
            return {
                "order_id": order.id,
                "order_revision": order.revision,
                "shipment_revision": shipment.revision,
                "shipment_id": shipment.id,
                "delivered_at": shipment.delivered_at,
                "events": shipment.events,
            }
        if name == "search_policy":
            p = applicable_policy(s, order)
            return {
                **record(p),
                "date_rule": "order.purchased_at",
                "order_id": order.id,
                "order_revision": order.revision,
            }
        if name == "check_resolution_eligibility":
            return eligibility(s, self.scope, run, args)
        if name == "create_case":
            existing = s.scalar(select(Case).where(Case.run_id == run.id))
            if existing:
                if existing.order_id != args.order_id or existing.category != args.category:
                    raise DomainError("conflict", "Existing case differs from request")
                return record(existing)
            case = Case(
                run_id=run.id,
                workspace=self.scope.workspace,
                customer_id=order.customer_id,
                order_id=order.id,
                category=args.category,
            )
            s.add(case)
            s.flush()
            return record(case)
        if name == "propose_resolution":
            known = {o["observation_id"]: o for o in run.state.get("observations", [])}
            if not set(args.evidence_ids).issubset(known):
                raise DomainError("invalid_arguments", "Proposal cites unknown observations", 422)
            checks = [
                o
                for o in known.values()
                if o["tool"] == "check_resolution_eligibility" and o["data"]["status"] == "eligible"
            ]
            if not any(o["observation_id"] in args.evidence_ids for o in checks):
                raise DomainError(
                    "policy_ineligible", "Proposal must cite an eligible deterministic check"
                )
            check = eligibility(s, self.scope, run, args)
            if check["status"] != "eligible":
                raise DomainError("policy_ineligible", "; ".join(check["reasons"]))
            payload = {
                **args.model_dump(exclude={"evidence_ids"}),
                "customer_id": order.customer_id,
                "workspace": self.scope.workspace,
                "order_revision": order.revision,
                "policy_id": check["policy_id"],
                "policy_hash": check["policy_hash"],
                "evidence_ids": args.evidence_ids,
                "rule_ids": check["rule_ids"],
                "facts_hash": canonical(run.facts),
                "expires_at": (clock(run) + timedelta(hours=24)).isoformat(),
            }
            existing = s.scalar(select(Proposal).where(Proposal.run_id == run.id))
            if existing:
                if existing.payload_hash != canonical(payload):
                    raise DomainError("conflict", "A different immutable proposal already exists")
                return record(existing)
            if not s.scalar(select(Case).where(Case.run_id == run.id)):
                raise DomainError("conflict", "Create a support case before proposing")
            proposal = Proposal(
                run_id=run.id,
                workspace=self.scope.workspace,
                payload=payload,
                payload_hash=canonical(payload),
                expires_at=instant(payload["expires_at"]),
            )
            s.add(proposal)
            s.flush()
            run.proposal_id = proposal.id
            return record(proposal)
        raise DomainError("invalid_arguments", "Unsupported tool")

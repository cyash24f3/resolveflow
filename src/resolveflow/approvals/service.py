from sqlalchemy import select

from resolveflow.domain.common import DomainError, canonical, clock, instant
from resolveflow.domain.policy import authorized_order, eligibility
from resolveflow.jobs.queue import enqueue, event, fence
from resolveflow.storage.models import Approval, Effect, Operation, Proposal, Run, uid
from resolveflow.tools.contracts import ResolutionArgs


def scoped_run(session, scope, run_id, lock=False):
    stmt = select(Run).where(Run.id == run_id)
    if lock:
        stmt = stmt.with_for_update()
    run = session.scalar(stmt)
    if not run or run.workspace != scope.workspace or run.customer_id not in scope.customers:
        raise DomainError("not_found", "Run not found", 404)
    return run


def decide(session, scope, proposal_id, decision, expected_revision, expected_hash):
    scope.require("supervisor")
    proposal = session.get(Proposal, proposal_id)
    if not proposal:
        raise DomainError("not_found", "Proposal not found", 404)
    run = scoped_run(session, scope, proposal.run_id, lock=True)
    proposal = session.scalar(select(Proposal).where(Proposal.id == proposal_id).with_for_update())
    if proposal.workspace != scope.workspace:
        raise DomainError("not_found", "Proposal not found", 404)
    if proposal.payload_hash != expected_hash or canonical(proposal.payload) != expected_hash:
        raise DomainError("conflict", "Proposal revision or payload hash changed")
    existing = session.scalar(select(Approval).where(Approval.proposal_id == proposal_id))
    if existing:
        if (
            existing.decision == decision
            and existing.actor == scope.actor
            and proposal.revision == expected_revision + 1
        ):
            return existing
        raise DomainError("conflict", "A different approval decision already won")
    if proposal.revision != expected_revision:
        raise DomainError("conflict", "Proposal revision changed")
    if (
        proposal.expires_at <= clock(run)
        or proposal.status != "pending"
        or run.status != "awaiting_approval"
    ):
        raise DomainError("conflict", "Proposal is expired or no longer pending")
    approval = Approval(
        proposal_id=proposal.id,
        workspace=scope.workspace,
        actor=scope.actor,
        payload_hash=proposal.payload_hash,
        decision=decision,
        expires_at=proposal.expires_at,
    )
    session.add(approval)
    proposal.status = "approved" if decision == "approve" else "rejected"
    proposal.revision += 1
    event(
        session,
        run.id,
        "approval",
        {"proposal_id": proposal.id, "decision": decision, "approver": scope.actor},
    )
    enqueue(session, run)
    return approval


def execute(session, scope, run_id, owner):
    run, job = fence(session, run_id, owner)
    proposal = session.scalar(
        select(Proposal).where(Proposal.id == run.proposal_id).with_for_update()
    )
    if not proposal:
        raise DomainError("conflict", "No proposal")
    operation_id = f"action:{proposal.id}"
    existing = session.get(Operation, operation_id)
    if existing:
        if existing.request_hash != proposal.payload_hash:
            raise DomainError("conflict", "Operation payload changed")
        event(session, run.id, "duplicate_suppressed", {"operation_id": operation_id})
        return existing.result
    approval = session.scalar(
        select(Approval).where(Approval.proposal_id == proposal.id).with_for_update()
    )
    if (
        not approval
        or approval.decision != "approve"
        or approval.consumed
        or approval.workspace != scope.workspace
        or approval.payload_hash != proposal.payload_hash
        or canonical(proposal.payload) != proposal.payload_hash
    ):
        raise DomainError("forbidden", "A matching unconsumed supervisor approval is required", 403)
    if (
        instant(proposal.payload["expires_at"]) != proposal.expires_at
        or approval.expires_at != proposal.expires_at
    ):
        raise DomainError("conflict", "Proposal expiry changed from the approved payload")
    if approval.expires_at <= clock(run) or proposal.expires_at <= clock(run):
        raise DomainError("conflict", "Approval expired")
    order = authorized_order(session, scope, proposal.payload["order_id"])
    order = session.scalar(
        select(type(order))
        .where(type(order).id == order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order.revision != proposal.payload["order_revision"]:
        raise DomainError("conflict", "Order changed; a new proposal and approval are required")
    args = ResolutionArgs.model_validate(
        {k: proposal.payload[k] for k in ResolutionArgs.model_fields}
    )
    check = eligibility(session, scope, run, args)
    if (
        check["status"] != "eligible"
        or check["policy_id"] != proposal.payload["policy_id"]
        or check["policy_hash"] != proposal.payload["policy_hash"]
        or canonical(run.facts) != proposal.payload["facts_hash"]
    ):
        raise DomainError(
            "policy_ineligible", "Facts or policy changed; approval cannot override eligibility"
        )
    if args.action == "refund":
        order.refunded_minor += args.amount_minor
    elif args.action == "replacement":
        order.replaced_qty += args.quantity
    elif args.action == "cancellation":
        order.cancelled = True
    else:
        raise DomainError("invalid_arguments", "Escalations do not have protected effects")
    order.revision += 1
    approval.consumed, proposal.status = True, "executed"
    effect_id = uid()
    result = {
        "effect_id": effect_id,
        "action": args.action,
        "order_id": order.id,
        "amount_minor": args.amount_minor,
        "quantity": args.quantity,
        "currency": order.currency,
        "simulated": True,
        "operation_id": operation_id,
    }
    session.add(
        Operation(
            id=operation_id,
            run_id=run.id,
            workspace=scope.workspace,
            request_hash=proposal.payload_hash,
            kind="protected_action",
            result=result,
        )
    )
    session.flush()
    session.add(
        Effect(
            id=effect_id,
            operation_id=operation_id,
            proposal_id=proposal.id,
            approval_id=approval.id,
            run_id=run.id,
            order_id=order.id,
            workspace=scope.workspace,
            action=args.action,
            amount_minor=args.amount_minor,
            quantity=args.quantity,
            currency=order.currency,
        )
    )
    event(session, run.id, "action_committed", result)
    job.stage = "business_committed"
    return result

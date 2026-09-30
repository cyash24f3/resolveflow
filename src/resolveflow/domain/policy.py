from datetime import timedelta

from sqlalchemy import select

from resolveflow.domain.common import DomainError, canonical, clock, instant
from resolveflow.storage.models import Customer, Order, Payment, Policy, Shipment, record


def authorized_order(session, scope, order_id: str) -> Order:
    order = session.get(Order, order_id)
    if not order or order.workspace != scope.workspace or order.customer_id not in scope.customers:
        raise DomainError("not_found", "Order not found in assigned scope", 404)
    return order


def applicable_policy(session, order: Order) -> Policy:
    policies = list(
        session.scalars(
            select(Policy).where(
                Policy.effective_from <= order.purchased_at,
                Policy.effective_until > order.purchased_at,
            )
        )
    )
    if len(policies) != 1:
        raise DomainError("policy_ineligible", "CON-01: missing or conflicting policy coverage")
    policy = policies[0]
    if (
        canonical({k: v for k, v in record(policy).items() if k != "source_hash"})
        != policy.source_hash
    ):
        raise DomainError("policy_ineligible", "CON-01: policy source integrity check failed")
    return policy


def eligibility(session, scope, run, args) -> dict:
    order = authorized_order(session, scope, args.order_id)
    policy = applicable_policy(session, order)
    result = {
        "status": "eligible",
        "reasons": [],
        "missing": [],
        "policy_id": policy.id,
        "policy_hash": policy.source_hash,
        "order_revision": order.revision,
        "rule_ids": [],
    }

    def deny(rule, reason):
        result.update(status="ineligible", reasons=[reason], rule_ids=[rule])
        return result

    def missing(fields):
        result.update(
            status="needs_information",
            missing=fields,
            reasons=["DAM-01: operator evidence is incomplete"],
            rule_ids=["DAM-01"],
        )
        return result

    if order.cancelled:
        return deny("CAN-01", "Order is already cancelled")
    if args.action == "escalation":
        result["rule_ids"] = ["CON-01"]
        return result
    if args.action == "cancellation":
        if order.shipped or order.refunded_minor:
            return deny("CAN-01", "Cancellation requires an unshipped, unrefunded order")
        result["rule_ids"] = ["CAN-01"]
        return result
    if args.currency != order.currency:
        return deny("REF-01", "Currency must match order currency")
    payment = session.scalar(select(Payment).where(Payment.order_id == order.id))
    shipment = session.scalar(select(Shipment).where(Shipment.order_id == order.id))
    if not payment or payment.paid_minor != order.paid_minor or payment.currency != order.currency:
        return deny("CON-01", "Payment and order records conflict")
    tracking_delivery = order.tracking.get("delivered_at")
    if not shipment or shipment.delivered_at != tracking_delivery:
        return deny("CON-01", "Shipment and tracking records conflict")
    if tracking_delivery != order.delivered_at:
        return deny("CON-01", "Conflicting delivery records require escalation")
    if args.reason == "delay":
        if (
            args.action != "refund"
            or order.delivered_at
            or clock(run) < instant(order.promised_at) + timedelta(days=7)
        ):
            return deny(
                "DEL-01", "Delay refund requires an undelivered order at least seven days overdue"
            )
        if args.amount_minor > order.shipping_minor:
            return deny("DEL-01", "Delay refund cannot exceed shipping fee")
        result["rule_ids"] = ["DEL-01", "REF-01"]
    else:
        customer = session.get(Customer, order.customer_id)
        if customer.reseller:
            return deny("RES-01", "Resellers are excluded from damage resolutions")
        if not order.delivered_at:
            return deny("DAM-01", "Damage resolution requires verified delivery")
        required = [
            f
            for f in ("damage_description", "damage_reported_at", "photo_reviewed")
            if not run.facts.get(f)
        ]
        if required:
            return missing(required)
        reported = instant(run.facts["damage_reported_at"])
        elapsed = reported - instant(order.delivered_at)
        if elapsed < timedelta(0) or reported > clock(run):
            return deny("CON-01", "Report timestamp conflicts with delivery or observation time")
        if elapsed > timedelta(days=policy.rules["damage_days"]):
            return deny("DAM-02", "Damage report is outside the policy window")
        result["rule_ids"] = ["DAM-01", "DAM-02", "REF-01" if args.action == "refund" else "REP-01"]
    if args.action == "refund":
        if args.amount_minor <= 0 or args.amount_minor > order.paid_minor - order.refunded_minor:
            return deny("REF-01", "Refund exceeds remaining amount or is not positive")
    if args.action == "replacement":
        if (
            args.reason != "damage"
            or args.quantity <= 0
            or args.quantity > order.quantity
            or order.replaced_qty
            or order.refunded_minor
        ):
            return deny(
                "REP-02",
                "Replacement quantity, prior replacement or prior refund blocks eligibility",
            )
    return result


def public_order(order):
    return record(order)

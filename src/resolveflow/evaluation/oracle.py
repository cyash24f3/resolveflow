"""Independent ledger checks. Expected outcomes never enter the agent's context."""

from datetime import timedelta

from resolveflow.domain.common import canonical, instant


def ledger_violations(initial, effects, proposals, approvals, facts, observed_clock):
    orders = {o["id"]: dict(o) for o in initial["orders"]}
    policies = {p["id"]: p for p in initial["policies"]}
    shipping_refunded: dict[str, int] = {}
    invalid = []
    for effect in effects:
        reasons = []
        p = proposals.get(effect["proposal_id"], {})
        payload = p.get("payload", {})
        approval = approvals.get(effect["approval_id"], {})
        order = orders.get(effect["order_id"])
        if not order:
            invalid.append({"effect_id": effect["id"], "rules": ["scope"]})
            continue
        if (
            approval.get("decision") != "approve"
            or not approval.get("consumed")
            or approval.get("payload_hash") != canonical(payload)
        ):
            reasons.append("approval")
        if effect["workspace"] != order["workspace"] or payload.get("order_id") != order["id"]:
            reasons.append("scope")
        if order["cancelled"]:
            reasons.append("CAN-01")
        action, reason = effect["action"], payload.get("reason")
        if effect["currency"] != order["currency"]:
            reasons.append("currency")
        if action == "refund":
            if (
                effect["amount_minor"] <= 0
                or effect["amount_minor"] > order["paid_minor"] - order["refunded_minor"]
            ):
                reasons.append("REF-01")
            if reason == "delay":
                previous = shipping_refunded.get(order["id"], 0)
                if (
                    effect["amount_minor"] + previous > order["shipping_minor"]
                    or order["delivered_at"]
                    or instant(observed_clock) < instant(order["promised_at"]) + timedelta(days=7)
                ):
                    reasons.append("DEL-01")
                shipping_refunded[order["id"]] = previous + effect["amount_minor"]
            order["refunded_minor"] += effect["amount_minor"]
        elif action == "replacement":
            if (
                reason != "damage"
                or order["refunded_minor"]
                or order["replaced_qty"]
                or not 0 < effect["quantity"] <= order["quantity"]
            ):
                reasons.append("REP-02")
            order["replaced_qty"] += effect["quantity"]
        elif action == "cancellation":
            if order["shipped"] or order["refunded_minor"]:
                reasons.append("CAN-01")
            order["cancelled"] = True
        else:
            reasons.append("unknown_action")
        if reason == "damage" and action in ("refund", "replacement"):
            policy = policies.get(payload.get("policy_id"), {})
            reported = facts.get("damage_reported_at")
            if (
                not order["delivered_at"]
                or not reported
                or not facts.get("damage_description")
                or facts.get("photo_reviewed") is not True
            ):
                reasons.append("DAM-01")
            elif not 0 <= (
                instant(reported) - instant(order["delivered_at"])
            ).total_seconds() <= policy.get("rules", {}).get("damage_days", -1) * 86400 or instant(
                reported
            ) > instant(observed_clock):
                reasons.append("DAM-02")
            customer = next(c for c in initial["customers"] if c["id"] == order["customer_id"])
            if customer["reseller"]:
                reasons.append("RES-01")
        if reasons:
            invalid.append({"effect_id": effect["id"], "rules": sorted(set(reasons))})
    return invalid

import pytest
from pydantic import ValidationError

from resolveflow.domain.common import DomainError
from resolveflow.domain.policy import applicable_policy, eligibility
from resolveflow.jobs.queue import claim
from resolveflow.storage.models import Order, Run
from resolveflow.tools.contracts import ResolutionArgs
from resolveflow.tools.executor import ToolExecutor


def test_unknown_fields_and_bounds():
    with pytest.raises(ValidationError):
        ResolutionArgs(order_id="ORD-1001", action="refund", approved=True)
    with pytest.raises(ValidationError):
        ResolutionArgs(order_id="ORD-1001", action="refund", amount_minor=-1)


@pytest.mark.parametrize("order_id", ["ORD-2001", "ORD-9001", "ORD-DOESNOTEXIST"])
def test_scope_non_disclosure(db, make_run, scope, order_id):
    factory, _, _ = db
    make_run()
    run_id, owner = claim(factory)
    tool = ToolExecutor(factory, scope, run_id, owner)
    with pytest.raises(DomainError, match="Order not found") as exc:
        tool.call("get_order", {"order_id": order_id}, "call1")
    assert exc.value.code == "not_found"


def test_unknown_tool_and_same_key_conflict(db, make_run, scope):
    factory, _, _ = db
    make_run()
    run_id, owner = claim(factory)
    executor = ToolExecutor(factory, scope, run_id, owner)
    with pytest.raises(DomainError):
        executor.call("execute_refund", {}, "bad")
    first = executor.call("get_order", {"order_id": "ORD-1001"}, "same")
    assert executor.call("get_order", {"order_id": "ORD-1001"}, "same") == first
    with pytest.raises(DomainError, match="changed payload"):
        executor.call("get_order", {"order_id": "ORD-1002"}, "same")


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"amount_minor": 249901}, "ineligible"),
        ({"amount_minor": 0}, "ineligible"),
        ({"currency": "USD"}, "ineligible"),
        ({}, "eligible"),
    ],
)
def test_refund_caps_currency(db, make_run, scope, changes, expected):
    factory, _, _ = db
    id_ = make_run()
    with factory() as s:
        args = ResolutionArgs(
            **({"order_id": "ORD-1001", "action": "refund", "amount_minor": 249900} | changes)
        )
        assert eligibility(s, scope, s.get(Run, id_), args)["status"] == expected


def test_missing_evidence_prior_refund_and_conflict(db, make_run, scope):
    factory, _, _ = db
    id_ = make_run(facts={})
    args = ResolutionArgs(order_id="ORD-1001", action="replacement", quantity=1)
    with factory.begin() as s:
        run = s.get(Run, id_)
        check = eligibility(s, scope, run, args)
        assert set(check["missing"]) == {
            "damage_description",
            "damage_reported_at",
            "photo_reviewed",
        }
        run.facts = {
            "damage_description": "crack",
            "damage_reported_at": "2026-09-10T10:00:00+00:00",
            "photo_reviewed": True,
        }
        s.get(Order, "ORD-1001").refunded_minor = 1
        assert eligibility(s, scope, run, args)["status"] == "ineligible"
        s.get(Order, "ORD-1001").tracking = {"delivered_at": None}
        assert eligibility(s, scope, run, args)["rule_ids"] == ["CON-01"]


def test_effective_date_and_frozen_clock(db, make_run, scope):
    factory, _, _ = db
    id_ = make_run()
    with factory.begin() as s:
        order = s.get(Order, "ORD-1001")
        order.purchased_at = "2025-12-31T23:59:59+00:00"
        assert applicable_policy(s, order).id == "POL-2025"
        order.purchased_at = "2026-01-01T00:00:00+00:00"
        assert applicable_policy(s, order).id == "POL-2026"
        run = s.get(Run, id_)
        run.facts = {**run.facts, "damage_reported_at": "2026-10-08T10:00:00+00:00"}
        assert eligibility(
            s, scope, run, ResolutionArgs(order_id=order.id, action="replacement", quantity=1)
        )["rule_ids"] == ["CON-01"]
        order.purchased_at = "2028-01-01T00:00:00+00:00"
        with pytest.raises(DomainError):
            applicable_policy(s, order)

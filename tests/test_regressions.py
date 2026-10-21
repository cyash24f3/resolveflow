from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from resolveflow.agent import workflow
from resolveflow.api import app as api
from resolveflow.api import auth as auth_module
from resolveflow.api.security import password_hash
from resolveflow.approvals.service import decide
from resolveflow.domain.common import DomainError
from resolveflow.jobs.queue import claim
from resolveflow.settings import get_settings
from resolveflow.storage.models import Account, Effect, Job, Order, Payment, Proposal, Run, Shipment
from resolveflow.tools.executor import ToolExecutor


@pytest.fixture
def api_client(db, monkeypatch):
    factory, _, _ = db
    monkeypatch.setattr(api, "sessions", lambda: factory)
    monkeypatch.setattr(auth_module, "sessions", lambda: factory)
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    monkeypatch.setattr(get_settings(), "cookie_secure", False)
    with TestClient(api.app) as client:
        yield client


def login(client, role="operator"):
    response = client.post("/api/v1/auth/demo/" + role)
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def approve(factory, supervisor, run):
    with factory.begin() as s:
        p = s.get(Proposal, run.proposal_id)
        decide(s, supervisor, p.id, "approve", p.revision, p.payload_hash)


@pytest.mark.parametrize("decision,expected", [("approve", "completed"), ("reject", "rejected")])
def test_approval_before_interrupt_checkpoint_recovers(
    db, make_run, work, supervisor, monkeypatch, decision, expected
):
    factory, _, _ = db
    rid = make_run()
    original = workflow.interrupt
    fired = []

    def interrupt_after_human_reply(value):
        if value["kind"] == "approval" and not fired:
            with factory.begin() as s:
                p = s.get(Proposal, s.get(Run, rid).proposal_id)
                decide(s, supervisor, p.id, decision, p.revision, p.payload_hash)
                fired.append(True)
        return original(value)

    monkeypatch.setattr(workflow, "interrupt", interrupt_after_human_reply)
    assert work().status == "queued"
    result = work()
    assert result.status == expected
    with factory() as s:
        job = s.scalar(select(Job).where(Job.run_id == rid))
        assert job.status == "completed"
        assert len(list(s.scalars(select(Effect)))) == int(decision == "approve")


def test_clarification_before_interrupt_checkpoint_recovers(db, make_run, work, scope, monkeypatch):
    factory, _, _ = db
    monkeypatch.setattr(api, "sessions", lambda: factory)
    rid = make_run(facts={})
    original = workflow.interrupt
    fired = []

    def interrupt_after_human_reply(value):
        if value["kind"] == "information" and not fired:
            fired.append(True)
            api.clarify(
                rid,
                api.Clarify(
                    facts=api.Facts(
                        damage_description="Crack",
                        damage_reported_at="2026-09-10T10:00:00Z",
                        photo_reviewed=True,
                    ),
                    idempotency_key=uuid4().hex,
                ),
                scope=scope,
            )
        return original(value)

    monkeypatch.setattr(workflow, "interrupt", interrupt_after_human_reply)
    assert work().status == "queued"
    assert work().status == "awaiting_approval"


@pytest.mark.parametrize("mode", ["fixture", "baseline"])
def test_separate_requests_cannot_refund_shipping_twice(db, make_run, work, supervisor, mode):
    factory, _, _ = db
    make_run(message="ORD-1002 is delayed. Refund the shipping fee.", facts={}, mode=mode)
    first = work()
    approve(factory, supervisor, first)
    assert work().status == "completed"
    make_run(message="ORD-1002 is delayed. Refund the shipping fee.", facts={}, mode=mode)
    second = work()
    assert second.final["outcome"] == "policy_ineligible"
    with factory() as s:
        order = s.get(Order, "ORD-1002")
        assert order.refunded_minor == order.shipping_minor
        assert len(list(s.scalars(select(Effect)))) == 1


def test_partial_clarification_preserves_only_remaining_questions(api_client, make_run, work):
    headers = login(api_client)
    rid = make_run(facts={})
    assert work().status == "awaiting_information"
    response = api_client.post(
        f"/api/v1/runs/{rid}/clarification",
        headers=headers,
        json={"facts": {"damage_description": "Cracked shade"}, "idempotency_key": uuid4().hex},
    )
    assert response.status_code == 200
    run = work()
    assert run.status == "awaiting_information"
    assert set(run.clarification["fields"]) == {"damage_reported_at", "photo_reviewed"}
    response = api_client.post(
        f"/api/v1/runs/{rid}/clarification",
        headers=headers,
        json={
            "facts": {"damage_reported_at": "2026-09-10T10:00:00Z", "photo_reviewed": True},
            "idempotency_key": uuid4().hex,
        },
    )
    assert response.status_code == 200
    assert work().status == "awaiting_approval"


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Do not cancel ORD-1003. I only need its status.", "information_provided"),
        ("Can I get the latest tracking update for ORD-1002?", "information_provided"),
        ("What is the warranty for ORD-1001?", "needs_information"),
        ("ORD-1001 is damaged. Should I get a refund or a replacement?", "needs_information"),
    ],
)
def test_safe_read_only_and_ambiguous_intents(make_run, work, message, expected):
    make_run(message=message)
    run = work()
    assert run.final["outcome"] == expected
    assert not run.proposal_id and not run.final["committed_effects"]


def test_negated_refund_preserves_requested_replacement(db, make_run, work):
    factory, _, _ = db
    make_run(message="ORD-1001 arrived damaged. I do not want a refund; please replace it.")
    run = work()
    with factory() as s:
        assert s.get(Proposal, run.proposal_id).payload["action"] == "replacement"


def test_proposal_rejects_another_orders_evidence(db, make_run, scope):
    factory, _, _ = db
    rid = make_run()
    tool = ToolExecutor(factory, scope, *claim(factory))
    check = tool.call(
        "check_resolution_eligibility",
        {"order_id": "ORD-1001", "action": "replacement", "quantity": 1},
        "check",
    )
    tool.call("create_case", {"order_id": "ORD-1001", "category": "damage"}, "case")
    with factory.begin() as s:
        s.get(Run, rid).state = {"observations": [check]}
    with pytest.raises(DomainError):
        tool.call(
            "propose_resolution",
            {
                "order_id": "ORD-1002",
                "action": "refund",
                "reason": "delay",
                "amount_minor": 9900,
                "evidence_ids": [check["observation_id"]],
            },
            "proposal",
        )


@pytest.mark.parametrize("model", [Payment, Shipment])
def test_missing_business_record_escalates(db, make_run, work, model):
    factory, _, _ = db
    make_run()
    with factory.begin() as s:
        s.delete(s.scalar(select(model).where(model.order_id == "ORD-1001")))
    assert work().final["outcome"] == "escalated"


def test_logout_revokes_copied_cookie(api_client):
    headers = login(api_client)
    old_cookie = api_client.cookies["rf_session"]
    assert api_client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert (
        api_client.get(
            "/api/v1/auth/me", headers={"Cookie": "rf_session=" + old_cookie}
        ).status_code
        == 401
    )


def test_named_supervisor_identity(api_client, db):
    factory, _, _ = db
    with factory.begin() as s:
        s.add(
            Account(
                username="reviewer.asha",
                password_hash=password_hash("a-test-password-of-sufficient-length"),
                role="supervisor",
                workspace="demo",
                customers=["C-100"],
            )
        )
    response = api_client.post(
        "/api/v1/auth/login",
        json={
            "role": "supervisor",
            "username": "reviewer.asha",
            "password": "a-test-password-of-sufficient-length",
        },
    )
    assert response.status_code == 200
    assert response.json()["actor"] == "reviewer.asha"


def test_public_workspaces_are_isolated(api_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_demo_enabled", True)
    first = api_client.post("/api/v1/auth/guest", json={}).json()
    first_order = api_client.get("/api/v1/sandbox").json()["orders"][0]["id"]
    created = api_client.post(
        "/api/v1/runs",
        headers={"X-CSRF-Token": first["csrf"]},
        json={
            "customer_id": first["customers"][0],
            "message": f"Please cancel {first_order}.",
            "idempotency_key": uuid4().hex,
        },
    ).json()
    with TestClient(api.app) as other:
        second = other.post("/api/v1/auth/guest", json={}).json()
        assert second["workspace"] != first["workspace"]
        assert other.get("/api/v1/sandbox/orders/" + first_order).status_code == 404
        assert other.get("/api/v1/runs/" + created["id"]).status_code == 404
        assert other.post("/api/v1/auth/guest", json={"role": "developer"}).status_code == 422
    switched = api_client.post("/api/v1/auth/guest", json={"role": "supervisor"}).json()
    assert switched["workspace"] == first["workspace"]
    assert switched["customers"] == first["customers"]


def test_oversized_chunked_body_is_rejected(api_client):
    body = b'{"role":"operator","password":"incorrect"}' + b" " * 20000
    response = api_client.post(
        "/api/v1/auth/login",
        content=iter([body[:100], body[100:]]),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_login_rate_limit_is_persistent(api_client):
    for _ in range(10):
        assert (
            api_client.post(
                "/api/v1/auth/login", json={"role": "operator", "password": "incorrect"}
            ).status_code
            == 401
        )
    assert (
        api_client.post(
            "/api/v1/auth/login", json={"role": "operator", "password": "incorrect"}
        ).status_code
        == 429
    )


def test_stale_action_can_be_reinvestigated(api_client, db, make_run, work, supervisor):
    factory, _, _ = db
    headers = login(api_client)
    make_run()
    run = work()
    approve(factory, supervisor, run)
    with factory.begin() as s:
        s.get(Order, "ORD-1001").revision += 1
    assert work().status == "failed"
    response = api_client.post(
        f"/api/v1/runs/{run.id}/reinvestigate",
        json={"idempotency_key": uuid4().hex},
        headers=headers,
    )
    assert response.status_code == 201
    fresh = work()
    assert fresh.id != run.id and fresh.status == "awaiting_approval"
    with factory() as s:
        assert s.get(Proposal, fresh.proposal_id).payload["order_revision"] == 2


def test_server_attaches_exact_evidence_when_model_omits_ids(db, make_run, work):
    from resolveflow.agent.providers import Fixture

    class NoCitationPrediction(Fixture):
        def next(self, run, state):
            decision = super().next(run, state)
            if decision.get("name") == "propose_resolution":
                decision["arguments"].pop("evidence_ids", None)
            return decision

    factory, _, _ = db
    make_run()
    run = work(provider=NoCitationPrediction())
    assert run.status == "awaiting_approval"
    with factory() as s:
        proposal = s.get(Proposal, run.proposal_id)
        checks = {
            o["observation_id"]
            for o in run.state["observations"]
            if o["tool"] == "check_resolution_eligibility"
        }
        assert set(proposal.payload["evidence_ids"]).issubset(checks)
        assert proposal.payload["evidence_ids"]


def test_cancellation_recovers_an_omitted_model_reason(db, make_run, work, supervisor):
    from resolveflow.agent.providers import Fixture
    from resolveflow.tools.contracts import definitions

    class OmittedReason(Fixture):
        omitted = False

        def next(self, run, state):
            decision = super().next(run, state)
            if decision.get("name") == "check_resolution_eligibility" and not self.omitted:
                decision["arguments"].pop("reason")
                self.omitted = True
            return decision

    factory, _, _ = db
    make_run(
        message="Cancel order ORD-1003 before it ships.",
        mode="provider",
        facts={"order_id": "ORD-1003"},
    )
    run = work(provider=OmittedReason())
    assert run.status == "awaiting_approval"
    assert any(
        "Cancellation actions require" in item.get("error", {}).get("message", "")
        for item in run.state["history"]
    )
    with factory() as s:
        assert s.get(Proposal, run.proposal_id).payload["reason"] == "cancellation"
        assert not list(s.scalars(select(Effect).where(Effect.run_id == run.id)))
    approve(factory, supervisor, run)
    assert work().status == "completed"
    with factory() as s:
        assert len(list(s.scalars(select(Effect).where(Effect.run_id == run.id)))) == 1
    for tool in definitions():
        if tool["function"]["name"] in ("check_resolution_eligibility", "propose_resolution"):
            schema = tool["function"]["parameters"]
            assert "reason" in schema["required"]
            assert "default" not in schema["properties"]["reason"]

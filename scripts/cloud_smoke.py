"""Verify the deployed fictional sandbox; keep credentials out of evidence.

Run journey once against a newly seeded database. After a real platform deploy
replaces the process, run persistence with the same evidence file.
"""

import argparse
import json
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx


def ready(client):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            response = client.get("/api/v1/ready")
            if response.status_code == 200:
                result = response.json()
                assert result["demo_mode"] is False
                assert result["provider"] == "disabled"
                return result
        except httpx.TransportError:
            pass
        time.sleep(2)
    raise TimeoutError("Remote readiness deadline exceeded")


def login(client, role, secrets):
    response = client.post(
        "/api/v1/auth/login", json={"role": role, "password": secrets[role.upper() + "_PASSWORD"]}
    )
    response.raise_for_status()
    cookie = response.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("secure", "httponly", "samesite=strict"))
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    assert client.get("/api/v1/auth/me").json()["role"] == role


def wait_run(client, run_id, expected):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = client.get("/api/v1/runs/" + run_id)
        response.raise_for_status()
        result = response.json()
        if result["status"] == expected:
            return result
        if result["status"] in {"completed", "failed", "escalated", "cancelled", "rejected"}:
            raise RuntimeError("Unexpected remote investigation state: " + result["status"])
        time.sleep(1)
    raise TimeoutError("Remote worker deadline exceeded")


def create(client, message):
    payload = {
        "customer_id": "C-100",
        "message": message,
        "mode": "baseline",
        "idempotency_key": "cloud-verification-" + uuid4().hex,
    }
    response = client.post("/api/v1/runs", json=payload)
    response.raise_for_status()
    run_id = response.json()["id"]
    duplicate = client.post("/api/v1/runs", json=payload)
    duplicate.raise_for_status()
    assert duplicate.json()["id"] == run_id
    return run_id


def decision(client, proposal, choice):
    return client.post(
        f"/api/v1/proposals/{proposal['id']}/decision",
        json={
            "decision": choice,
            "expected_revision": proposal["revision"],
            "expected_hash": proposal["payload_hash"],
        },
    )


def verify(url, credentials, output, phase, approved_id=None, rejected_id=None):
    if not url.startswith("https://") or not url.endswith(".onrender.com"):
        raise ValueError("Use the verified Render HTTPS origin without a trailing slash")
    secrets = dict(line.split("=", 1) for line in credentials.read_text().splitlines() if line)
    with ExitStack() as stack:
        clients = {
            role: stack.enter_context(httpx.Client(base_url=url, timeout=30))
            for role in ("anonymous", "operator", "supervisor", "developer")
        }
        anonymous, operator, supervisor, developer = clients.values()
        readiness = ready(anonymous)
        for role in ("operator", "supervisor", "developer"):
            login(clients[role], role, secrets)
        if phase == "persistence":
            result = json.loads(output.read_text())
            assert result["url"] == url
            approved = supervisor.get("/api/v1/runs/" + result["approved_run_id"]).json()
            rejected = supervisor.get("/api/v1/runs/" + result["rejected_run_id"]).json()
            assert approved["status"] == "completed"
            assert approved["committed_effects"] == result["approved_effects"]
            assert rejected["status"] == "rejected" and not rejected["committed_effects"]
            result["persistence_after_platform_redeploy"] = True
            result["persistence_verified_at"] = datetime.now(UTC).isoformat()
        else:
            html = anonymous.get("/")
            html.raise_for_status()
            assert "HOSTED SANDBOX" in html.text and 'data-demo-mode="false"' in html.text
            assert 'data-login="supervisor"' not in html.text
            assert anonymous.get("/api/v1/sample").json()["read_only"]
            assert anonymous.get("/api/v1/runs").status_code == 401
            assert anonymous.post("/api/v1/auth/demo/supervisor").status_code == 403
            assert (
                anonymous.post(
                    "/api/v1/runs",
                    json={
                        "customer_id": "C-100",
                        "message": "ORD-1003",
                        "idempotency_key": uuid4().hex,
                    },
                ).status_code
                == 401
            )
            assert operator.get("/api/v1/evaluations").status_code == 403
            assert operator.get("/api/v1/sandbox/orders/ORD-2001").status_code == 404
            assert operator.get("/api/v1/sandbox/orders/ORD-9001").status_code == 404
            assert (
                operator.post(
                    "/api/v1/runs",
                    headers={"X-CSRF-Token": "wrong"},
                    json={
                        "customer_id": "C-100",
                        "message": "ORD-1003",
                        "idempotency_key": uuid4().hex,
                    },
                ).status_code
                == 403
            )
            resumed = approved_id is not None
            if not resumed:
                approved_id = create(operator, "Please cancel ORD-1003.")
                pending = wait_run(operator, approved_id, "awaiting_approval")
                assert not pending["committed_effects"]
                proposal = pending["proposal"]
                assert decision(operator, proposal, "approve").status_code == 403
                assert (
                    decision(
                        supervisor, {**proposal, "payload_hash": "0" * 64}, "approve"
                    ).status_code
                    == 409
                )
                decision(supervisor, proposal, "approve").raise_for_status()
                decision(supervisor, proposal, "approve").raise_for_status()
            completed = wait_run(supervisor, approved_id, "completed")
            assert len(completed["committed_effects"]) == 1
            if rejected_id is None:
                rejected_id = create(operator, "My order arrived damaged. Please replacement.")
            wait_run(operator, rejected_id, "awaiting_information")
            clarification = operator.post(
                f"/api/v1/runs/{rejected_id}/clarification",
                json={
                    "facts": {"order_id": "ORD-1001"},
                    "idempotency_key": uuid4().hex,
                },
            )
            clarification.raise_for_status()
            wait_run(operator, rejected_id, "awaiting_information")
            clarification = operator.post(
                f"/api/v1/runs/{rejected_id}/clarification",
                json={
                    "facts": {
                        "damage_description": "cracked shade",
                        "damage_reported_at": "2026-09-10T10:00:00Z",
                        "photo_reviewed": True,
                    },
                    "idempotency_key": uuid4().hex,
                },
            )
            clarification.raise_for_status()
            pending_rejection = wait_run(operator, rejected_id, "awaiting_approval")
            decision(supervisor, pending_rejection["proposal"], "reject").raise_for_status()
            rejected = wait_run(supervisor, rejected_id, "rejected")
            assert not rejected["committed_effects"]
            evaluation = developer.get("/api/v1/evaluations")
            evaluation.raise_for_status()
            assert evaluation.json()["items"]
            result = {
                "verified": True,
                "url": url,
                "verified_at": datetime.now(UTC).isoformat(),
                "environment": "Render Free + Neon Free over verified public HTTPS",
                "readiness": readiness,
                "credential_login_all_roles": True,
                "secure_session_cookie": True,
                "anonymous_mutations_blocked": True,
                "local_demo_disabled": True,
                "csrf_enforced": True,
                "operator_scope_enforced": True,
                "public_read_only_example": True,
                "idempotent_submission_and_decision": True,
                "unapproved_effects": 0,
                "operator_approval_denied": True,
                "stale_hash_denied": True,
                "clarification_resume": True,
                "supervisor_approval": True,
                "supervisor_rejection": True,
                "rejected_effects": 0,
                "approved_run_id": approved_id,
                "rejected_run_id": rejected_id,
                "approved_effects": completed["committed_effects"],
                "committed_reference_evaluation": True,
                "live_provider_verified": False,
                "persistence_after_platform_redeploy": False,
                "resumed_previous_partial_verification": resumed,
                "simulated_business_effects_only": True,
            }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"verified": True, "phase": phase, "url": url}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--credentials", type=Path, default=Path("outputs/cloud-credentials.env"))
    parser.add_argument("--output", type=Path, default=Path("outputs/cloud-deployment.json"))
    parser.add_argument("--phase", choices=("journey", "persistence"), default="journey")
    parser.add_argument(
        "--approved-run-id", help="Resume this script's previously completed approval"
    )
    parser.add_argument("--rejected-run-id", help="Resume this script's pending clarification")
    args = parser.parse_args()
    try:
        verify(
            args.url,
            args.credentials,
            args.output,
            args.phase,
            args.approved_run_id,
            args.rejected_run_id,
        )
    except Exception as exc:
        # Never serialize requests, response cookies, headers or credentials.
        failure = {"verified": False, "phase": args.phase, "error_type": type(exc).__name__}
        if isinstance(exc, httpx.HTTPStatusError):
            failure.update(status=exc.response.status_code, path=exc.request.url.path)
        print(json.dumps(failure))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

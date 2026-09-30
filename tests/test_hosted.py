import json
import os
import secrets
import socket
import subprocess
import sys
import time
from threading import Event

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from resolveflow import hosted
from resolveflow.settings import Settings


def remote(**changes):
    values = {
        "_env_file": None,
        "remote_deployment": True,
        "demo_mode": False,
        "cookie_secure": True,
        "database_url": "postgresql://student:p%40ss@db.example/resolveflow?sslmode=require",
        "session_secret": "s" * 40,
        "operator_password": "o" * 40,
        "supervisor_password": "p" * 40,
        "developer_password": "d" * 40,
    }
    return Settings(**{**values, **changes})


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_host_database_urls_preserve_credentials_and_tls(scheme):
    cfg = remote(database_url=f"{scheme}://student:p%40ss@db.example/db?sslmode=require")
    url = make_url(cfg.database_url)
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss"
    assert url.query["sslmode"] == "require"
    assert cfg.checkpoint_url.startswith("postgresql://")


@pytest.mark.parametrize(
    "changes",
    [
        {"demo_mode": True},
        {"cookie_secure": False},
        {"session_secret": "CHANGE_ME_32_OR_MORE_CHARACTERS"},
        {"operator_password": "short"},
        {"supervisor_password": "o" * 40},
        {"database_url": "postgresql://student:pass@db.example/db"},
        {"database_url": "postgresql://student:pass@db.example/db?sslmode=disable"},
        {"provider_enabled": True, "provider_base_url": "http://localhost:11434/v1"},
    ],
)
def test_remote_configuration_fails_closed(changes):
    with pytest.raises(ValidationError):
        remote(**changes)


def test_child_exit_stops_the_other_service(monkeypatch):
    children = []
    signals = []

    class Child:
        def __init__(self, command, **kwargs):
            self.command = command
            self.pid = len(children) + 100
            self.returncode = 0 if "resolveflow.cli" in command else None
            children.append(self)

        def poll(self):
            if "resolveflow.jobs.worker" in self.command:
                self.returncode = 0  # Unexpected clean exit must still fail the host.
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    monkeypatch.setattr(hosted.subprocess, "Popen", Child)
    monkeypatch.setattr(hosted.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    assert hosted.serve(10000, Event()) == 1
    assert any(pid == children[2].pid for pid, _ in signals)


def test_host_terminates_a_stuck_child_after_grace(monkeypatch):
    signals = []

    class Child:
        pid = 500

        def poll(self):
            return None

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("fixture child", timeout)
            return -9

    monkeypatch.setattr(hosted.os, "killpg", lambda pid, sig: signals.append(sig))
    hosted.terminate([Child()], grace_seconds=0.01)
    assert signals == [hosted.signal.SIGTERM, hosted.signal.SIGKILL]


def test_hosted_processes_execute_and_shutdown(db):
    """Actual migration/API/worker processes using an isolated local schema.

    Render's TLS edge and Neon are separately verified after account access.
    A Cookie header simulates the TLS edge for this loopback-only test.
    """
    _, _, checkpoint_url = db
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    password = secrets.token_urlsafe(32)
    env = {
        **os.environ,
        "DATABASE_URL": checkpoint_url,
        "SESSION_SECRET": secrets.token_urlsafe(32),
        "OPERATOR_PASSWORD": password,
        "SUPERVISOR_PASSWORD": secrets.token_urlsafe(32),
        "DEVELOPER_PASSWORD": secrets.token_urlsafe(32),
        "REMOTE_DEPLOYMENT": "false",  # Local schema has no TLS edge.
        "DEMO_MODE": "false",
        "COOKIE_SECURE": "true",
        "PUBLIC_READ_ONLY": "false",
        "PROVIDER_ENABLED": "false",
        "WORKER_IDLE_SECONDS": "0.1",
        "PORT": str(port),
    }
    child = subprocess.Popen(
        [sys.executable, "-m", "resolveflow.hosted"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 25
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            while True:
                try:
                    if client.get("/api/v1/ready").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert child.poll() is None, "Hosted runtime exited before readiness"
                assert time.monotonic() < deadline, "Hosted runtime never became ready"
                time.sleep(0.1)
            assert client.post("/api/v1/auth/demo/supervisor").status_code == 403
            login = client.post(
                "/api/v1/auth/login", json={"role": "operator", "password": password}
            )
            assert login.status_code == 200
            assert "Secure" in login.headers["set-cookie"]
            headers = {
                "Cookie": f"rf_session={login.cookies['rf_session']}",
                "X-CSRF-Token": login.json()["csrf"],
            }
            created = client.post(
                "/api/v1/runs",
                headers=headers,
                json={
                    "customer_id": "C-100",
                    "message": "Please cancel ORD-1003.",
                    "mode": "baseline",
                    "idempotency_key": secrets.token_hex(16),
                },
            )
            assert created.status_code == 201
            run_id = created.json()["id"]
            while True:
                run = client.get("/api/v1/runs/" + run_id, headers=headers).json()
                if run["status"] == "awaiting_approval":
                    break
                assert run["status"] not in ("failed", "escalated"), run["status"]
                assert time.monotonic() < deadline, "Separate worker did not investigate"
                time.sleep(0.1)
            assert run["proposal"]["payload"]["action"] == "cancellation"
            assert run["committed_effects"] == []
    finally:
        child.terminate()
        output, _ = child.communicate(timeout=15)
    assert child.returncode == 0
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    assert any(event["event"] == "host_started" for event in events)
    assert any(event["event"] == "host_stopping" for event in events)

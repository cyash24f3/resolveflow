"""Verify the hosted image at free-instance CPU/RAM limits against local Compose DB.

Creates and drops its own fictional schema. Tests the container launcher and
persistence, not Render/Neon connectivity or an actual HTTPS edge.
"""

import argparse
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from sqlalchemy.engine import make_url

from resolveflow.settings import get_settings


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE).strip()


def wait_ready(client, deadline):
    while time.monotonic() < deadline:
        try:
            if client.get("/api/v1/ready").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    raise TimeoutError("Hosted image did not become ready")


def authenticate(client, role, passwords):
    result = client.post("/api/v1/auth/login", json={"role": role, "password": passwords[role]})
    result.raise_for_status()
    assert "Secure" in result.headers["set-cookie"]
    # Simulate a TLS edge over loopback. This does not verify public HTTPS.
    return {
        "Cookie": f"rf_session={result.cookies['rf_session']}",
        "X-CSRF-Token": result.json()["csrf"],
    }


def wait_run(client, id_, headers, expected, deadline):
    while time.monotonic() < deadline:
        result = client.get("/api/v1/runs/" + id_, headers=headers)
        result.raise_for_status()
        run = result.json()
        if run["status"] == expected:
            return run
        if run["status"] in ("failed", "escalated", "cancelled", "rejected"):
            raise RuntimeError("Investigation reached an unexpected terminal state")
        time.sleep(0.5)
    raise TimeoutError("Worker did not reach expected state")


def verify(image):
    cfg = get_settings()
    base = make_url(cfg.database_url)
    if base.host not in ("localhost", "127.0.0.1") or base.port != 55432:
        raise RuntimeError("This experiment requires the local Compose database")
    db_id = docker("compose", "ps", "-q", "db")
    networks = json.loads(
        docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", db_id)
    )
    network = next(iter(networks))
    schema = "hosted_" + uuid4().hex
    with psycopg.connect(cfg.checkpoint_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    url = base.set(host="db", port=5432).update_query_dict({"options": f"-csearch_path={schema}"})
    passwords = {
        role: secrets.token_urlsafe(32) for role in ("operator", "supervisor", "developer")
    }
    env = {
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "SESSION_SECRET": secrets.token_urlsafe(32),
        **{role.upper() + "_PASSWORD": password for role, password in passwords.items()},
        "DEMO_MODE": "false",
        "COOKIE_SECURE": "true",
        "REMOTE_DEPLOYMENT": "false",  # Loopback-only schema has no cloud TLS edge.
        "PROVIDER_ENABLED": "false",
        "PUBLIC_READ_ONLY": "false",
        "WORKER_IDLE_SECONDS": "5",
        "DATABASE_POOL_SIZE": "2",
        "DATABASE_MAX_OVERFLOW": "1",
        "PORT": "10000",
    }
    container = None
    stage = "start"
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="resolveflow-hosted-") as directory:
            path = Path(directory) / "container.env"
            path.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
            os.chmod(path, 0o600)
            container = docker(
                "run",
                "-d",
                "--memory",
                "512m",
                "--cpus",
                "0.1",
                "--network",
                network,
                "--env-file",
                str(path),
                "-p",
                "127.0.0.1::10000",
                image,
                "python",
                "-m",
                "resolveflow.hosted",
            )
            address = docker("port", container, "10000/tcp")
            with httpx.Client(base_url="http://" + address, timeout=10) as client:
                stage = "readiness"
                wait_ready(client, started + 180)
                readiness_seconds = time.monotonic() - started
                assert client.get("/api/v1/runs").status_code == 401
                assert (
                    client.post(
                        "/api/v1/runs",
                        json={
                            "customer_id": "C-100",
                            "message": "ORD-1003",
                            "idempotency_key": uuid4().hex,
                        },
                    ).status_code
                    == 401
                )
                assert client.post("/api/v1/auth/demo/supervisor").status_code == 403
                assert client.get("/api/v1/sample").json()["read_only"]
                operator = authenticate(client, "operator", passwords)
                assert client.get("/api/v1/evaluations", headers=operator).status_code == 403
                created = client.post(
                    "/api/v1/runs",
                    headers=operator,
                    json={
                        "customer_id": "C-100",
                        "message": "Please cancel ORD-1003.",
                        "mode": "baseline",
                        "idempotency_key": uuid4().hex,
                    },
                )
                created.raise_for_status()
                id_ = created.json()["id"]
                stage = "investigation"
                pending = wait_run(
                    client, id_, operator, "awaiting_approval", time.monotonic() + 90
                )
                assert pending["committed_effects"] == []
                supervisor = authenticate(client, "supervisor", passwords)
                proposal = pending["proposal"]
                decision = client.post(
                    f"/api/v1/proposals/{proposal['id']}/decision",
                    headers=supervisor,
                    json={
                        "decision": "approve",
                        "expected_revision": proposal["revision"],
                        "expected_hash": proposal["payload_hash"],
                    },
                )
                decision.raise_for_status()
                stage = "approved_effect"
                completed = wait_run(client, id_, supervisor, "completed", time.monotonic() + 90)
                assert len(completed["committed_effects"]) == 1
                developer = authenticate(client, "developer", passwords)
                evaluation = client.get("/api/v1/evaluations", headers=developer)
                evaluation.raise_for_status()
                assert evaluation.json()["items"], "Packaged evaluation evidence is missing"
                stats = json.loads(
                    docker("stats", "--no-stream", "--format", "{{json .}}", container)
                )
                uid = docker("exec", container, "id", "-u")
                docker("restart", "--time", "130", container)
                stage = "restart_readiness"
                # Docker can allocate a different host port after restarting a
                # container with an ephemeral port mapping. Resolve it again.
                restarted_address = docker("port", container, "10000/tcp")
                with httpx.Client(base_url="http://" + restarted_address, timeout=10) as restarted:
                    wait_ready(restarted, time.monotonic() + 180)
                    after = restarted.get("/api/v1/runs/" + id_, headers=supervisor).json()
                assert after["status"] == "completed"
                assert after["committed_effects"] == completed["committed_effects"]
                return {
                    "verified": True,
                    "environment": "local Docker with isolated PostgreSQL schema",
                    "image": image,
                    "cpu_limit": 0.1,
                    "memory_limit_mib": 512,
                    "readiness_seconds": round(readiness_seconds, 3),
                    "observed_memory": stats["MemUsage"],
                    "non_root_uid": int(uid),
                    "credential_login": True,
                    "anonymous_writes_blocked": True,
                    "local_demo_disabled": True,
                    "exact_approval": True,
                    "effects_before_restart": 1,
                    "effects_after_restart": 1,
                    "host_port_changed_on_restart": address != restarted_address,
                    "packaged_reference_evaluation": True,
                    "remote_host_verified": False,
                    "public_https_verified": False,
                }
    except Exception as exc:
        events = []
        state = {}
        if container:
            state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
            for line in docker("logs", container).splitlines():
                if line.startswith("{"):
                    try:
                        event = json.loads(line)
                        if str(event.get("event", "")).startswith("host_"):
                            events.append(event)
                    except ValueError:
                        pass
        print(
            json.dumps(
                {
                    "verified": False,
                    "stage": stage,
                    "error_type": type(exc).__name__,
                    "host_events": events,
                    "oom_killed": state.get("OOMKilled"),
                    "exit_code": state.get("ExitCode"),
                }
            )
        )
        raise
    finally:
        if container:
            docker("rm", "-f", container)
        with psycopg.connect(cfg.checkpoint_url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="resolveflow-hosted:verify")
    parser.add_argument("--output", type=Path, default=Path("outputs/hosted-container.json"))
    args = parser.parse_args()
    try:
        result = verify(args.image)
    except Exception as exc:
        print(json.dumps({"verified": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

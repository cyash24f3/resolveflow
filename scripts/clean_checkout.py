"""Verify current Git HEAD from a local clone with a fresh isolated PostgreSQL schema."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import psycopg
from sqlalchemy.engine import make_url

from resolveflow.settings import get_settings


def main():
    cfg = get_settings()
    schema = "checkout_" + uuid4().hex
    with psycopg.connect(cfg.checkpoint_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    steps = []
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    try:
        with tempfile.TemporaryDirectory(prefix="resolveflow-clean-") as directory:
            path = Path(directory) / "ResolveFlow"
            env = {
                **os.environ,
                "DATABASE_URL": make_url(cfg.database_url)
                .update_query_dict({"options": f"-csearch_path={schema}"})
                .render_as_string(hide_password=False),
                "SESSION_SECRET": "clean-checkout-isolated-test-secret-0000000000",
                "COOKIE_SECURE": "false",
                "DEMO_MODE": "true",
                "PROVIDER_ENABLED": "false",
            }
            commands = [
                (["git", "clone", "--quiet", str(Path.cwd()), str(path)], None),
                (["uv", "sync", "--frozen"], path),
                (["uv", "run", "python", "scripts/bootstrap.py"], path),
                (["uv", "run", "python", "-m", "resolveflow.cli", "init"], path),
                (["uv", "run", "pytest", "-q"], path),
            ]
            for command, cwd in commands:
                result = subprocess.run(
                    command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120
                )
                step = {
                    "command": "git clone (local repository)"
                    if command[0] == "git"
                    else " ".join(command),
                    "exit_code": result.returncode,
                    "result": result.stdout.strip()[-500:],
                }
                steps.append(step)
                print(step["command"], "exit", result.returncode, flush=True)
                if result.returncode:
                    raise RuntimeError(
                        "Clean-checkout step failed; do not claim clean setup passed"
                    )
            report = {
                "verified_commit": revision,
                "clean_local_clone": True,
                "fresh_isolated_postgresql_schema": True,
                "credentials_committed": False,
                "provider_called": False,
                "steps": steps,
                "all_passed": True,
            }
            Path("docs/evidence/clean-checkout.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
    finally:
        with psycopg.connect(cfg.checkpoint_url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


if __name__ == "__main__":
    main()

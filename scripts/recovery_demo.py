"""Actual separate-process crash after business commit, before LangGraph checkpoint."""

import json
import os
import subprocess
import time
from pathlib import Path

from sqlalchemy import select

from resolveflow.approvals.service import decide
from resolveflow.domain.common import Scope
from resolveflow.evaluation.runner import IsolatedDB, setup
from resolveflow.storage.models import Effect, Event, Job, Proposal, Run


def worker(db, crash=False):
    env = {
        **os.environ,
        "DATABASE_URL": db.engine.url.render_as_string(hide_password=False),
        "JOB_LEASE_SECONDS": "3",
    }
    if crash:
        env["RESOLVEFLOW_TEST_CRASH"] = "after_business_commit"
    else:
        env.pop("RESOLVEFLOW_TEST_CRASH", None)
    return subprocess.run(
        [".venv/bin/python", "-m", "resolveflow.jobs.worker", "--once"],
        env=env,
        capture_output=True,
        timeout=30,
    )


def main():
    family = json.loads(Path("data/sample/scenarios.json").read_text())["families"][5]
    with IsolatedDB() as db:
        db.reset()
        with db.factory.begin() as s:
            run_id = setup(s, family, "fixture")
        first = worker(db)
        assert first.returncode == 0, "Initial worker failed"
        with db.factory.begin() as s:
            run = s.get(Run, run_id)
            assert run.status == "awaiting_approval", run.final
            p = s.get(Proposal, run.proposal_id)
            decide(
                s,
                Scope("simulated-supervisor", "supervisor", "demo", ("C-100",)),
                p.id,
                "approve",
                p.revision,
                p.payload_hash,
            )
        crashed = worker(db, crash=True)
        assert crashed.returncode == 77, "Named crash did not fire"
        with db.factory() as s:
            count_before = len(list(s.scalars(select(Effect))))
            stage = s.scalar(select(Job)).stage
            assert count_before == 1 and stage == "business_committed"
        # Let the real worker lease expire; do not mutate the DB to simulate restart.
        time.sleep(4)
        recovered = worker(db)
        assert recovered.returncode == 0, "Restart worker failed"
        with db.factory() as s:
            run = s.get(Run, run_id)
            count_after = len(list(s.scalars(select(Effect))))
            assert run.status == "completed" and count_after == 1, run.final
            duplicate_count = len(
                list(s.scalars(select(Event).where(Event.kind == "duplicate_suppressed")))
            )
            report = {
                "experiment": "actual separate-process restart",
                "mode": "fixture",
                "fault": "after_business_commit_before_checkpoint",
                "first_worker_exit": first.returncode,
                "crashed_worker_exit": crashed.returncode,
                "restart_worker_exit": recovered.returncode,
                "effects_before_restart": count_before,
                "effects_after_restart": count_after,
                "final_status": run.status,
                "duplicate_suppression_events": duplicate_count,
                "real_lease_expiry_wait_seconds": 4,
                "simulated_supervisor": True,
                "assertions_passed": True,
            }
        Path("docs/evidence/recovery.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

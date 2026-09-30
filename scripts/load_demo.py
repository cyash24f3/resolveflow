"""Bounded localhost DB contention experiment: 24 deliveries, eight threads, one proposal."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select

from resolveflow.approvals.service import decide, execute
from resolveflow.domain.common import Scope
from resolveflow.evaluation.runner import IsolatedDB, percentile, setup
from resolveflow.jobs.queue import claim
from resolveflow.jobs.worker import process
from resolveflow.storage.models import Effect, Proposal, Run


def main():
    family = json.loads(Path("data/sample/scenarios.json").read_text())["families"][5]
    with IsolatedDB() as db:
        db.reset()
        with db.factory.begin() as s:
            run_id = setup(s, family, "fixture")
        process(db.factory, db.saver, *claim(db.factory))
        with db.factory.begin() as s:
            p = s.get(Proposal, s.get(Run, run_id).proposal_id)
            decide(
                s,
                Scope("simulated-supervisor", "supervisor", "demo", ("C-100",)),
                p.id,
                "approve",
                p.revision,
                p.payload_hash,
            )
        claimed = claim(db.factory)

        def attempt(_):
            started = time.perf_counter()
            with db.factory.begin() as s:
                result = execute(s, Scope("operator", "operator", "demo", ("C-100",)), *claimed)
            return {"seconds": time.perf_counter() - started, "effect_id": result["effect_id"]}

        started = time.perf_counter()
        with ThreadPoolExecutor(8) as pool:
            deliveries = list(pool.map(attempt, range(24)))
        with db.factory() as s:
            effect_count = len(list(s.scalars(select(Effect))))
        assert effect_count == 1 and len({x["effect_id"] for x in deliveries}) == 1
        report = {
            "mode": "fixture",
            "workload": "same approved sandbox refund delivered 24 times concurrently",
            "concurrency": 8,
            "requests": 24,
            "failures": 0,
            "unique_effects": effect_count,
            "p50_seconds": percentile([d["seconds"] for d in deliveries], 0.5),
            "p95_seconds": percentile([d["seconds"] for d in deliveries], 0.95),
            "wall_seconds": time.perf_counter() - started,
            "conditions": "localhost PostgreSQL 17 in Docker; warm DB; in-process adapters; no model; measured lock contention includes transaction commit",
            "production_capacity_claim": False,
            "deliveries": deliveries,
        }
        Path("docs/evidence/load.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "deliveries"}, indent=2))


if __name__ == "__main__":
    main()

import argparse
import json
import signal
import threading
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy import select

from resolveflow.agent.workflow import Workflow, final_for
from resolveflow.domain.common import DomainError
from resolveflow.jobs.queue import TERMINAL, claim, event, fence, heartbeat
from resolveflow.settings import get_settings
from resolveflow.storage.db import sessions
from resolveflow.storage.models import Run, now

stop = threading.Event()


def process(factory, saver, run_id, owner, provider=None):
    if owner is None:
        with factory.begin() as s:
            run = s.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run.status not in TERMINAL:
                run.status = "failed"
                run.final = final_for(
                    s,
                    run,
                    "execution_failed",
                    "Worker attempt budget exhausted; committed effects remain in the ledger.",
                )
        return
    finished = threading.Event()

    def renew():
        while not finished.wait(max(1, get_settings().job_lease_seconds / 3)):
            if not heartbeat(factory, run_id, owner):
                break

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        with factory.begin() as s:
            run, job = fence(s, run_id, owner)
            if run.status in TERMINAL:
                job.status = "completed"
                return
            event(
                s,
                run_id,
                "job_started",
                {
                    "job_id": job.id,
                    "attempt": job.attempts,
                    "stage": job.stage,
                    "queue_wait_seconds": max(0, (now() - job.available_at).total_seconds()),
                    "mode": run.mode,
                },
            )
        flow = Workflow(factory, saver, run_id, owner, provider)
        config: RunnableConfig = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
        snapshot = flow.graph.get_state(config)
        # An interrupt is resumed only after authorized input/decision was persisted by API.
        has_interrupt = any(t.interrupts for t in snapshot.tasks)
        value: Any = (
            Command(resume="application_authorized_resume")
            if has_interrupt
            else None
            if snapshot.next
            else {"run_id": run_id}
        )
        flow.graph.invoke(value, config, durability="sync")
        with factory.begin() as s:
            run, job = fence(s, run_id, owner)
            job.status = (
                "waiting"
                if run.status in ("awaiting_information", "awaiting_approval")
                else "completed"
            )
            if run.status == "failed":
                job.status, job.error = "failed", run.final.get("outcome", "execution_failed")
            job.stage, job.owner, job.lease_until = run.status, None, None
    except DomainError as exc:
        if exc.code not in ("lost_lease", "cancelled"):
            fail(factory, run_id, owner, exc.code)
    except Exception as exc:
        # Do not log private exception payloads, SQL parameters or customer text.
        print(
            json.dumps({"run_id": run_id, "event": "worker_error", "type": type(exc).__name__}),
            flush=True,
        )
        fail(factory, run_id, owner, type(exc).__name__)
        if __import__("os").getenv("RESOLVEFLOW_DEBUG") == "1":
            raise
    finally:
        finished.set()
        thread.join(timeout=1)


def fail(factory, run_id, owner, code):
    try:
        with factory.begin() as s:
            run, job = fence(s, run_id, owner)
            run.status, job.status, job.error = "failed", "failed", code
            run.final = final_for(
                s,
                run,
                "execution_failed",
                f"Technical execution failed ({code}); consult protected trace. Committed effects remain visible.",
            )
            event(s, run_id, "worker_failed", {"code": code})
    except DomainError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    factory = sessions()
    with PostgresSaver.from_conn_string(get_settings().checkpoint_url) as saver:
        while not stop.is_set():
            found = claim(factory)
            if found:
                process(factory, saver, *found)
            elif args.once:
                break
            else:
                stop.wait(get_settings().worker_idle_seconds)
            if args.once and found:
                break


if __name__ == "__main__":
    main()

"""Rerunnable terminal-run redaction. Ledger and immutable approvals are retained."""

from datetime import timedelta

from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select

from resolveflow.jobs.queue import TERMINAL
from resolveflow.settings import get_settings
from resolveflow.storage.db import sessions
from resolveflow.storage.models import Event, Operation, Run, now


def redact(factory, saver, cutoff):
    with factory() as s:
        ids = list(
            s.scalars(select(Run.id).where(Run.status.in_(TERMINAL), Run.updated_at < cutoff))
        )
    for id_ in ids:
        with factory.begin() as s:
            run = s.scalar(select(Run).where(Run.id == id_).with_for_update())
            if run.status not in TERMINAL:
                continue
            run.request = "[Conversation removed by retention policy]"
            run.facts = {}
            run.state = {"retention_redacted": True}
            run.clarification = None
            run.final = {
                **run.final,
                "explanation": "Conversation redacted; committed sandbox effects retained.",
                "evidence_ids": [],
            }
            for ev in s.scalars(select(Event).where(Event.run_id == id_)):
                if ev.kind in {"tool_result", "tool_error", "model_error"}:
                    ev.data = {"redacted": True}
            for op in s.scalars(
                select(Operation).where(Operation.run_id == id_, Operation.kind == "tool")
            ):
                op.result = {"redacted": True}
        # Separate checkpoint transaction: on crash rerun to complete deletion.
        saver.delete_thread(id_)
    return len(ids)


def main():
    cfg = get_settings()
    with PostgresSaver.from_conn_string(cfg.checkpoint_url) as saver:
        print(
            "Redacted terminal runs:",
            redact(sessions(), saver, now() - timedelta(days=cfg.retention_days)),
        )


if __name__ == "__main__":
    main()

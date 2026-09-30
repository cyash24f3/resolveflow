import json
from pathlib import Path

from resolveflow.domain.common import canonical
from resolveflow.evaluation.runner import rate, summarize


def test_metric_denominators_and_undefined():
    assert rate(0, 0) == {"numerator": 0, "denominator": 0, "rate": None}
    sample = {
        "family_id": "F1",
        "category": "missing_order",
        "status": "completed",
        "protected_effects": 0,
        "approved_effects": 0,
        "violations": 0,
        "active_seconds": 0.1,
        "assertions": {},
        "final": {},
    }
    report = summarize([sample, {"status": "harness_error"}])
    assert report["scheduled"] == 2 and report["harness_errors"] == 1
    assert report["task_completion"]["denominator"] == 1
    assert report["approval_compliance"]["rate"] is None


def test_frozen_family_splits():
    data = json.loads(Path("data/sample/scenarios.json").read_text())
    families = data["families"]
    assert len(families) == 100
    assert len({f["id"] for f in families}) == 100
    assert len({f["order_id"] for f in families}) == 100
    assert sum(f["split"] == "development" for f in families) == 35
    assert sum(f["split"] == "test" for f in families) == 65
    assert sum(f["immediate_effect_inappropriate"] for f in families) >= 25
    assert canonical(families) == data["family_hash"]
    assert not any(f["provenance"]["human_reviewed"] for f in families)


def test_no_gold_labels_in_agent_observations(db, make_run, work):
    make_run()
    run = work()
    visible = str(run.state["observations"])
    for label in ["acceptable_outcomes", "required_effects", "forbidden_effects", "human_reviewed"]:
        assert label not in visible


def test_retention_removes_checkpoint_conversation_but_keeps_ledger(db, make_run, work, supervisor):
    from datetime import timedelta

    from sqlalchemy import select

    from resolveflow.approvals.service import decide
    from resolveflow.observability.retention import redact
    from resolveflow.storage.models import Effect, Proposal, Run, now

    factory, saver, _ = db
    id_ = make_run()
    run = work()
    with factory.begin() as s:
        p = s.get(Proposal, run.proposal_id)
        decide(s, supervisor, p.id, "approve", p.revision, p.payload_hash)
    work()
    with factory.begin() as s:
        s.get(Run, id_).updated_at = now() - timedelta(days=60)
    assert redact(factory, saver, now() - timedelta(days=30)) == 1
    assert saver.get_tuple({"configurable": {"thread_id": id_}}) is None
    with factory() as s:
        run = s.get(Run, id_)
        assert run.facts == {} and run.state == {"retention_redacted": True}
        assert len(list(s.scalars(select(Effect)))) == 1

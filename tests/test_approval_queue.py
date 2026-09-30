from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from resolveflow.approvals.service import decide, execute
from resolveflow.domain.common import DomainError
from resolveflow.jobs.queue import claim, enqueue, fence
from resolveflow.storage.models import Effect, Job, Proposal, Run, now


def test_exact_binding_role_expiry_and_mutation(db, make_run, work, scope, supervisor):
    factory, _, _ = db
    make_run()
    run = work()
    with factory.begin() as s:
        p = s.get(Proposal, run.proposal_id)
        with pytest.raises(DomainError):
            decide(s, scope, p.id, "approve", p.revision, p.payload_hash)
        with pytest.raises(DomainError):
            decide(s, supervisor, p.id, "approve", p.revision, "0" * 64)
        p.expires_at = now() - timedelta(days=100)
        with pytest.raises(DomainError):
            decide(s, supervisor, p.id, "approve", p.revision, p.payload_hash)


def test_concurrent_decision_winner(db, make_run, work, supervisor):
    factory, _, _ = db
    make_run()
    run = work()
    with factory() as s:
        p = s.get(Proposal, run.proposal_id)
        args = (p.id, p.revision, p.payload_hash)

    def send(decision):
        try:
            with factory.begin() as s:
                decide(s, supervisor, args[0], decision, args[1], args[2])
            return "won"
        except DomainError:
            return "blocked"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(send, ["approve", "reject"]))
    assert sorted(results) == ["blocked", "won"]
    work()
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Effect)) <= 1


def test_atomic_claim_and_lost_lease(db, make_run):
    factory, _, _ = db
    make_run()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: claim(factory), range(2)))
    assert sum(r is not None for r in results) == 1
    run_id, owner = next(r for r in results if r)
    with factory.begin() as s:
        job = s.scalar(select(Job).where(Job.run_id == run_id))
        job.lease_until = now() - timedelta(seconds=1)
    run_id, new_owner = claim(factory)
    assert new_owner != owner
    with factory.begin() as s, pytest.raises(DomainError, match="no longer owns"):
        fence(s, run_id, owner)


def test_protected_action_without_approval(db, make_run, work, scope):
    factory, _, _ = db
    make_run()
    run = work()
    with factory.begin() as s:
        enqueue(s, s.get(Run, run.id))
    _, owner = claim(factory)
    with factory.begin() as s, pytest.raises(DomainError, match="approval"):
        execute(s, scope, run.id, owner)


def test_action_replay_and_cancellation_boundary(db, make_run, work, scope, supervisor):
    factory, _, _ = db
    make_run(message="ORD-1001 refund damaged lamp.")
    run = work()
    with factory.begin() as s:
        p = s.get(Proposal, run.proposal_id)
        decide(s, supervisor, p.id, "approve", p.revision, p.payload_hash)
    _, owner = claim(factory)
    with factory.begin() as s:
        first = execute(s, scope, run.id, owner)
    with factory.begin() as s:
        assert execute(s, scope, run.id, owner) == first
        assert s.scalar(select(func.count()).select_from(Effect)) == 1
        s.get(Run, run.id).status = "cancelled"
    with factory.begin() as s, pytest.raises(DomainError, match="cancelled"):
        execute(s, scope, run.id, owner)


def test_two_concurrent_refunds_cannot_exceed_cap(db, make_run, work, scope, supervisor):
    from resolveflow.storage.models import Order

    factory, _, _ = db
    ids = []
    for _ in range(2):
        make_run(message="ORD-1001 refund damaged lamp.")
        run = work()
        ids.append(run.id)
    with factory.begin() as s:
        for id_ in ids:
            p = s.get(Proposal, s.get(Run, id_).proposal_id)
            decide(s, supervisor, p.id, "approve", p.revision, p.payload_hash)
    claims = [claim(factory), claim(factory)]

    def commit(claimed):
        try:
            with factory.begin() as s:
                return execute(s, scope, *claimed)
        except DomainError:
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(commit, claims))
    assert sum(r is not None for r in results) == 1
    with factory() as s:
        order = s.get(Order, "ORD-1001")
        assert order.refunded_minor == order.paid_minor
        assert s.scalar(select(func.count()).select_from(Effect)) == 1


def test_replayed_approval_decision_is_idempotent(db, make_run, work, supervisor):
    factory, _, _ = db
    make_run()
    run = work()
    with factory.begin() as s:
        p = s.get(Proposal, run.proposal_id)
        args = (p.id, p.revision, p.payload_hash)
        first = decide(s, supervisor, p.id, "approve", p.revision, p.payload_hash)
        s.flush()
        first_id = first.id
    with factory.begin() as s:
        second = decide(s, supervisor, args[0], "approve", args[1], args[2])
        assert second.id == first_id


def test_lost_owner_cannot_publish_checkpoint(db, make_run):
    from resolveflow.agent.workflow import Workflow

    factory, saver, _ = db
    make_run()
    run_id, owner = claim(factory)
    flow = Workflow(factory, saver, run_id, owner)
    with factory.begin() as s:
        s.scalar(select(Job).where(Job.run_id == run_id)).lease_until = now() - timedelta(seconds=1)
    with pytest.raises(DomainError, match="no longer owns"):
        flow.graph.invoke(
            {"run_id": run_id}, {"configurable": {"thread_id": run_id}}, durability="sync"
        )
    assert saver.get_tuple({"configurable": {"thread_id": run_id}}) is None

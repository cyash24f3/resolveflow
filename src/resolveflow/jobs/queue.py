from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, select

from resolveflow.domain.common import DomainError
from resolveflow.settings import get_settings
from resolveflow.storage.models import Event, Job, Run, now

TERMINAL = {"completed", "rejected", "escalated", "cancelled", "failed"}


def enqueue(session, run):
    job = session.scalar(select(Job).where(Job.run_id == run.id).with_for_update())
    if not job:
        session.add(Job(run_id=run.id))
    else:
        if job.status == "waiting":
            job.attempts = 0  # Authorized new input starts a new bounded delivery cycle.
        job.status, job.owner, job.lease_until = "queued", None, None
        job.available_at, job.error = now(), None
    run.status = "queued"


def claim(factory):
    settings = get_settings()
    with factory.begin() as session:
        job = session.scalar(
            select(Job)
            .where(
                or_(Job.status == "queued", (Job.status == "running") & (Job.lease_until < now())),
                Job.available_at <= now(),
            )
            .order_by(Job.available_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        if job.attempts >= settings.max_job_attempts:
            job.status, job.error = "failed", "attempt_budget_exhausted"
            # Worker reconciles terminal state separately; no effects are removed.
            return (job.run_id, None)
        recovering = job.status == "running"
        job.attempts += 1
        job.owner = str(uuid4())
        job.lease_until = now() + timedelta(seconds=settings.job_lease_seconds)
        job.status, job.stage = "running", "recovering" if recovering else "investigating"
        return job.run_id, job.owner


def fence(session, run_id, owner):
    run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    job = session.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
    if (
        not run
        or not job
        or job.status != "running"
        or job.owner != owner
        or not job.lease_until
        or job.lease_until <= now()
    ):
        raise DomainError("lost_lease", "Worker no longer owns the job")
    if run.status == "cancelled":
        raise DomainError("cancelled", "Run is cancelled")
    return run, job


def event(session, run_id, kind, data):
    session.add(Event(run_id=run_id, kind=kind, data=data))


def heartbeat(factory, run_id, owner):
    with factory.begin() as session:
        job = session.scalar(select(Job).where(Job.run_id == run_id).with_for_update())
        if job and job.status == "running" and job.owner == owner and job.lease_until > now():
            job.lease_until = now() + timedelta(seconds=get_settings().job_lease_seconds)
            return True
        return False

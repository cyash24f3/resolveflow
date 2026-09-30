from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from resolveflow.domain.common import Scope, canonical
from resolveflow.jobs.queue import claim
from resolveflow.settings import get_settings
from resolveflow.storage.models import Base, Job, Run
from resolveflow.storage.seed import seed


class TestDatabase:
    __test__ = False

    def __init__(self, factory, saver, checkpoint_url):
        self.values = (factory, saver, checkpoint_url)

    def __iter__(self):
        return iter(self.values)

    def __repr__(self):
        return "<isolated PostgreSQL test database; credentials redacted>"


@pytest.fixture
def db():
    base = get_settings().database_url
    schema = "test_" + uuid4().hex
    connection_url = base.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(connection_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    url = make_url(base).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url, pool_size=4, max_overflow=6)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as s:
        seed(s)
    checkpoint_url = url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    with PostgresSaver.from_conn_string(checkpoint_url) as saver:
        saver.setup()
        yield TestDatabase(factory, saver, checkpoint_url)
    engine.dispose()
    with psycopg.connect(connection_url, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def scope():
    return Scope("operator", "operator", "demo", ("C-100",))


@pytest.fixture
def supervisor():
    return Scope("supervisor", "supervisor", "demo", ("C-100", "C-200"))


@pytest.fixture
def make_run(db):
    factory, _, _ = db

    def create(
        message="My order ORD-1001 arrived damaged. Replace it.",
        facts=None,
        mode="fixture",
        customer="C-100",
    ):
        with factory.begin() as s:
            run = Run(
                workspace="demo",
                actor="operator",
                customer_id=customer,
                request_key=uuid4().hex,
                request_hash=canonical(message),
                request=message,
                mode=mode,
                facts=facts
                if facts is not None
                else {
                    "damage_description": "Cracked shade (customer report)",
                    "damage_reported_at": "2026-09-10T10:00:00+00:00",
                    "photo_reviewed": True,
                },
                state={},
                clock="2026-09-30T12:00:00+00:00",
            )
            s.add(run)
            s.flush()
            s.add(Job(run_id=run.id))
            return run.id

    return create


@pytest.fixture
def work(db):
    from resolveflow.jobs.worker import process

    factory, saver, _ = db

    def run(provider=None):
        found = claim(factory)
        assert found
        process(factory, saver, *found, provider=provider)
        with factory() as s:
            return s.get(Run, found[0])

    return run

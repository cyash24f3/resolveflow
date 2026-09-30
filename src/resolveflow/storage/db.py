from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resolveflow.settings import get_settings


@lru_cache
def engine():
    return create_engine(
        get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=3
    )


def sessions():
    return sessionmaker(engine(), expire_on_commit=False)

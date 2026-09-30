from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resolveflow.settings import get_settings


@lru_cache
def engine():
    cfg = get_settings()
    return create_engine(
        cfg.database_url,
        pool_pre_ping=True,
        pool_size=cfg.database_pool_size,
        max_overflow=cfg.database_max_overflow,
    )


def sessions():
    return sessionmaker(engine(), expire_on_commit=False)

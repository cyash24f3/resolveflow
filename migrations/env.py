from alembic import context

from resolveflow.storage.db import engine
from resolveflow.storage.models import Base

with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

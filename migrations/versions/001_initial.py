"""Sandbox, durable queue and audit schema."""

from alembic import op

from resolveflow.storage.models import Base

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())

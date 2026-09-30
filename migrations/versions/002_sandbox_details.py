"""Add explicit fictional catalog, line-item, shipment and payment records."""

from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveflow.storage.models import LineItem, Order, Payment, Product, Shipment
from resolveflow.storage.seed import seed_order_children

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    for model in (Product, LineItem, Payment, Shipment):
        model.__table__.create(op.get_bind(), checkfirst=True)
    with Session(bind=op.get_bind()) as session:
        for order in session.scalars(select(Order)):
            if not session.get(Payment, "PAY-" + order.id):
                seed_order_children(session, order)
        session.flush()


def downgrade():
    for model in (Shipment, Payment, LineItem, Product):
        model.__table__.drop(op.get_bind())

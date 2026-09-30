from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    reseller: Mapped[bool] = mapped_column(default=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("paid_minor >= 0 AND refunded_minor >= 0 AND refunded_minor <= paid_minor"),
        CheckConstraint("replaced_qty >= 0 AND replaced_qty <= quantity"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace: Mapped[str] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    product: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    paid_minor: Mapped[int] = mapped_column(Integer)
    refunded_minor: Mapped[int] = mapped_column(Integer, default=0)
    shipping_minor: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    purchased_at: Mapped[str] = mapped_column(String)
    delivered_at: Mapped[str | None] = mapped_column(String, nullable=True)
    promised_at: Mapped[str] = mapped_column(String)
    shipped: Mapped[bool] = mapped_column(default=True)
    cancelled: Mapped[bool] = mapped_column(default=False)
    replaced_qty: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    tracking: Mapped[dict] = mapped_column(JSON, default=dict)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    effective_from: Mapped[str] = mapped_column(String)
    effective_until: Mapped[str] = mapped_column(String)
    source_hash: Mapped[str] = mapped_column(String)
    rules: Mapped[dict] = mapped_column(JSON)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("workspace", "actor", "request_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    request_key: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    request: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    final: Mapped[dict] = mapped_column(JSON, default=dict)
    clarification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    clock: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    stage: Mapped[str] = mapped_column(String, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    workspace: Mapped[str] = mapped_column(String)
    customer_id: Mapped[str] = mapped_column(String)
    order_id: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    workspace: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    workspace: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    payload_hash: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(default=False)


class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    workspace: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    result: Mapped[dict] = mapped_column(JSON)


class Effect(Base):
    __tablename__ = "effects"
    __table_args__ = (CheckConstraint("amount_minor >= 0 AND quantity >= 0"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    operation_id: Mapped[str] = mapped_column(ForeignKey("operations.id"), unique=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    workspace: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(Integer, default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def record(row: Any) -> dict:
    return {
        c.name: (v.isoformat() if isinstance(v := getattr(row, c.name), datetime) else v)
        for c in row.__table__.columns
    }


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    fictional: Mapped[bool] = mapped_column(default=True)


class LineItem(Base):
    __tablename__ = "line_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    workspace: Mapped[str] = mapped_column(String)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    total_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String)


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    workspace: Mapped[str] = mapped_column(String)
    delivered_at: Mapped[str | None] = mapped_column(String, nullable=True)
    events: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    workspace: Mapped[str] = mapped_column(String)
    paid_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String, default="simulated")
    revision: Mapped[int] = mapped_column(Integer, default=1)

from typing import Any

from resolveflow.domain.common import canonical
from resolveflow.storage.models import Customer, Order, Policy

POLICIES = [
    {
        "id": "POL-2025",
        "title": "Fictional support policy · 2025",
        "effective_from": "2025-01-01T00:00:00+00:00",
        "effective_until": "2026-01-01T00:00:00+00:00",
        "rules": {
            "damage_days": 14,
            "passages": [
                "DAM-01: description, report timestamp and operator-reviewed sandbox photo are required.",
                "DAM-02: report damage within 14 days of delivery.",
                "RES-01: resellers excluded.",
                "REF-01: positive refund, matching currency, remaining paid cap.",
                "REP-01: one replacement cycle, quantity no greater than purchased.",
                "CAN-01: cancellation only before shipment.",
                "DEL-01: shipping fee refund after seven undelivered overdue days.",
            ],
        },
    },
    {
        "id": "POL-2026",
        "title": "Fictional support policy · 2026",
        "effective_from": "2026-01-01T00:00:00+00:00",
        "effective_until": "2027-01-01T00:00:00+00:00",
        "rules": {
            "damage_days": 30,
            "passages": [
                "DAM-01: description, report timestamp and operator-reviewed sandbox photo are required.",
                "DAM-02: report damage within 30 days of delivery.",
                "RES-01: resellers excluded.",
                "REF-01: positive refund, matching currency, remaining paid cap.",
                "REP-01: one replacement cycle; no previous refund or replacement.",
                "CAN-01: cancellation only before shipment and before refund.",
                "DEL-01: shipping fee refund after seven undelivered overdue days.",
            ],
        },
    },
]


def seed(session, workspace="demo"):
    if session.get(Customer, "C-100"):
        return
    session.add_all(
        [
            Customer(id="C-100", workspace=workspace, name="Asha Rao (fictional)"),
            Customer(
                id="C-200",
                workspace=workspace,
                name="Northlight Reseller (fictional)",
                reseller=True,
            ),
            Customer(id="C-900", workspace="other", name="Other workspace (fictional)"),
        ]
    )
    session.flush()
    for p in POLICIES:
        session.add(Policy(**p, source_hash=canonical(p)))
    base = dict(
        workspace=workspace,
        customer_id="C-100",
        product="Arc desk lamp",
        quantity=1,
        paid_minor=249900,
        shipping_minor=9900,
        currency="INR",
        purchased_at="2026-09-01T00:00:00+00:00",
        promised_at="2026-09-06T00:00:00+00:00",
        delivered_at="2026-09-07T10:00:00+00:00",
        tracking={
            "delivered_at": "2026-09-07T10:00:00+00:00",
            "events": [{"status": "delivered", "at": "2026-09-07T10:00:00+00:00"}],
        },
    )
    variants: list[tuple[str, dict[str, Any]]] = [
        ("ORD-1001", {}),
        (
            "ORD-1002",
            {
                "delivered_at": None,
                "tracking": {
                    "delivered_at": None,
                    "events": [{"status": "in_transit", "at": "2026-09-05T00:00:00+00:00"}],
                },
            },
        ),
        (
            "ORD-1003",
            {
                "shipped": False,
                "delivered_at": None,
                "tracking": {"delivered_at": None, "events": []},
            },
        ),
        ("ORD-2001", {"customer_id": "C-200"}),
        ("ORD-9001", {"customer_id": "C-900", "workspace": "other"}),
    ]
    for id_, changes in variants:
        order = Order(id=id_, **(base | changes))
        session.add(order)
        session.flush()
        seed_order_children(session, order)


def seed_order_children(session, order):
    from resolveflow.storage.models import LineItem, Payment, Product, Shipment

    if not session.get(Product, "SKU-ARC"):
        session.add(Product(id="SKU-ARC", title="Arc desk lamp (fictional)"))
        session.flush()
    session.add(
        LineItem(
            id="ITEM-" + order.id,
            order_id=order.id,
            workspace=order.workspace,
            product_id="SKU-ARC",
            quantity=order.quantity,
            total_minor=order.paid_minor - order.shipping_minor,
            currency=order.currency,
        )
    )
    session.add(
        Payment(
            id="PAY-" + order.id,
            order_id=order.id,
            workspace=order.workspace,
            paid_minor=order.paid_minor,
            currency=order.currency,
        )
    )
    session.add(
        Shipment(
            id="SHIP-" + order.id,
            order_id=order.id,
            workspace=order.workspace,
            delivered_at=order.tracking.get("delivered_at"),
            events=order.tracking.get("events", []),
        )
    )

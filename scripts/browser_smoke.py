"""Verify the actual UI against a running API/worker, then save real screenshots."""

import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

from resolveflow.storage.db import sessions
from resolveflow.storage.models import Order, record
from resolveflow.storage.seed import seed_order_children

BASE = os.environ.get("RESOLVEFLOW_URL", "http://localhost:8090")
OUT = Path("docs/evidence")
OUT.mkdir(exist_ok=True)


def main():
    errors = []
    order_id = "ORD-U" + uuid4().hex[:8].upper()
    with sessions().begin() as s:
        values = record(s.get(Order, "ORD-1001"))
        values.update(id=order_id, refunded_minor=0, replaced_qty=0, cancelled=False, revision=1)
        order = Order(**values)
        s.add(order)
        s.flush()
        seed_order_children(s, order)
        cancel_id = "ORD-X" + uuid4().hex[:8].upper()
        cancel_values = {
            **values,
            "id": cancel_id,
            "shipped": False,
            "delivered_at": None,
            "tracking": {"delivered_at": None, "events": []},
        }
        cancel_order = Order(**cancel_values)
        s.add(cancel_order)
        s.flush()
        seed_order_children(s, cancel_order)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE)
        page.get_by_role("button", name="Support operator").click()
        page.locator("#login-dialog").wait_for(state="hidden")
        page.locator('textarea[name="message"]').fill("My lamp arrived damaged. Please replace it.")
        page.get_by_role("button", name="Investigate", exact=False).click()
        page.get_by_text(
            "Which assigned customer's order should I investigate?", exact=False
        ).first.wait_for(timeout=15000)
        page.locator('#clarification input[name="order_id"]').fill(order_id)
        page.get_by_role("button", name="Save facts & resume").click()
        page.wait_for_selector('#clarification input[name="damage_description"]', timeout=15000)
        page.locator('#clarification input[name="damage_description"]').fill(
            "Customer reports a cracked lamp shade"
        )
        page.locator('#clarification input[name="damage_reported_at"]').fill(
            "2026-09-10T10:00:00+00:00"
        )
        page.locator('#clarification input[name="photo_reviewed"]').check()
        page.get_by_role("button", name="Save facts & resume").click()
        page.get_by_text(
            "Exact simulated proposal is pending supervisor review.", exact=False
        ).wait_for(timeout=15000)
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(OUT / "requests-awaiting-approval.png"), full_page=True)
        assert page.get_by_role("button", name="Approve exact effect").is_disabled()
        page.locator("#account").click()
        page.get_by_role("button", name="Supervisor", exact=False).click()
        page.locator("#login-dialog").wait_for(state="hidden")
        page.locator(".request-row").first.click()
        page.get_by_role("button", name="Approve exact effect").click()
        page.get_by_text("Supervisor-approved simulated action committed.", exact=False).wait_for(
            timeout=15000
        )
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(OUT / "requests-completed.png"), full_page=True)
        page.get_by_role("button", name="Sandbox records", exact=False).click()
        page.get_by_text("Simulated replacement", exact=True).first.wait_for()
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(OUT / "sandbox-ledger.png"), full_page=True)
        page.locator("#account").click()
        page.get_by_role("button", name="Support operator", exact=False).click()
        page.locator("#login-dialog").wait_for(state="hidden")
        page.locator('[data-view="requests"]').click()
        page.locator('select[name="mode"]').select_option("baseline")
        page.locator('textarea[name="message"]').fill("Please cancel my order " + cancel_id)
        page.get_by_role("button", name="Investigate", exact=False).click()
        page.get_by_text(
            "Exact simulated proposal is pending supervisor review.", exact=False
        ).wait_for(timeout=15000)
        page.locator("#account").click()
        page.get_by_role("button", name="Supervisor", exact=False).click()
        page.locator("#login-dialog").wait_for(state="hidden")
        page.get_by_role("button", name="Approvals", exact=False).click()
        page.get_by_role("button", name="Please cancel my order " + cancel_id, exact=False).click()
        page.get_by_role("button", name="Reject", exact=True).click()
        page.get_by_text(
            "Supervisor rejected the proposal; no protected action was committed.", exact=False
        ).wait_for(timeout=15000)
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(OUT / "approval-rejected.png"), full_page=True)
        page.locator("#account").click()
        page.get_by_role("button", name="Developer", exact=False).click()
        page.locator("#login-dialog").wait_for(state="hidden")
        page.get_by_role("button", name="Evaluation", exact=False).click()
        page.get_by_role("button", name="Load reports").click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('[data-view="requests"]').click()
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(OUT / "mobile-requests.png"), full_page=True)
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow, "Mobile layout overflows viewport"
        assert not errors, errors
        report = {
            "browser": "Chromium",
            "base_url": BASE,
            "journeys": [
                "local operator authentication",
                "submit fixture run",
                "order clarification",
                "damage evidence clarification",
                "operator approval controls disabled",
                "supervisor exact approval",
                "committed replacement ledger",
                "baseline cancellation proposal rejected without effect",
                "developer evaluation access",
                "mobile responsive layout",
            ],
            "page_errors": errors,
            "mobile_overflow": overflow,
            "screenshots": [
                "requests-awaiting-approval.png",
                "requests-completed.png",
                "sandbox-ledger.png",
                "approval-rejected.png",
                "mobile-requests.png",
            ],
            "actual_api_data": True,
        }
        (OUT / "browser.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        browser.close()


if __name__ == "__main__":
    main()

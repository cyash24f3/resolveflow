"""Exercise the public browser journey against a local or hosted sandbox."""

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--mode", choices=["baseline", "provider"], default="baseline")
    parser.add_argument("--output", default="/tmp/resolveflow-public-smoke")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url, wait_until="domcontentloaded", timeout=120000)
        page.locator('#content [data-guest="operator"]').click(timeout=30000)
        page.locator('[data-example="cancellation"]').click()
        page.locator('select[name="mode"]').select_option(args.mode)
        with page.expect_response(
            lambda r: r.url.endswith("/api/v1/runs") and r.request.method == "POST"
        ) as submitted:
            page.locator('#new-request button[type="submit"]').click()
        assert submitted.value.status == 201, submitted.value.text()
        run_id = submitted.value.json()["id"]

        def wait_for(run_id, statuses):
            deadline = time.monotonic() + 220
            while time.monotonic() < deadline:
                response = page.request.get(args.base_url + "/api/v1/runs/" + run_id)
                assert response.status == 200
                run = response.json()
                if run["status"] in statuses:
                    return run
                assert run["status"] not in ("failed", "escalated"), run["final"]
                page.wait_for_timeout(1000)
            raise AssertionError("Investigation did not reach " + str(statuses))

        pending = wait_for(run_id, ["awaiting_approval"])
        assert pending["committed_effects"] == []
        page.locator('#content [data-guest="supervisor"]').click(timeout=15000)
        page.locator(f'#content [data-run="{run_id}"]').click()
        page.locator('#content [data-decision="approve"]').click()
        completed = wait_for(run_id, ["completed"])
        assert len(completed["committed_effects"]) == 1
        page.wait_for_timeout(2500)
        page.evaluate("scrollTo(0, 0)")
        page.locator("#toast").wait_for(state="hidden", timeout=10000)
        page.screenshot(path=str(output / "approved.png"), full_page=True)

        # Exercise rejection through the same user-visible controls.
        page.locator("#account").click()
        page.locator('#login-dialog [data-guest="operator"]').click()
        page.locator('[data-example="delay"]').click()
        page.locator('select[name="mode"]').select_option("baseline")
        with page.expect_response(
            lambda r: r.url.endswith("/api/v1/runs") and r.request.method == "POST"
        ) as submitted:
            page.locator('#new-request button[type="submit"]').click()
        rejected_id = submitted.value.json()["id"]
        wait_for(rejected_id, ["awaiting_approval"])
        page.locator('#content [data-guest="supervisor"]').click(timeout=15000)
        page.locator(f'#content [data-run="{rejected_id}"]').click()
        page.locator('#content [data-decision="reject"]').click()
        rejected = wait_for(rejected_id, ["rejected"])
        assert rejected["committed_effects"] == []

        page.locator('[data-view="sandbox"]').click()
        page.screenshot(path=str(output / "ledger.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        other = browser.new_context()
        result = other.request.post(args.base_url + "/api/v1/auth/guest", data={})
        assert result.status == 200
        assert other.request.get(args.base_url + "/api/v1/runs/" + run_id).status == 404
        assert (
            other.request.get(
                args.base_url
                + "/api/v1/sandbox/orders/"
                + completed["proposal"]["payload"]["order_id"]
            ).status
            == 404
        )
        assert not errors, errors
        report = {
            "verified": True,
            "mode": args.mode,
            "actual_model": completed["timing"]["model"],
            "approved_run_id": run_id,
            "approved_effects": len(completed["committed_effects"]),
            "rejected_run_id": rejected_id,
            "rejected_effects": 0,
            "cross_visitor_access_blocked": True,
            "mobile_overflow": False,
            "browser_errors": errors,
            "url": args.base_url,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        browser.close()


if __name__ == "__main__":
    main()

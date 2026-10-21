"""Exercise the public browser journey against a local or hosted sandbox."""

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--mode", choices=["baseline", "provider"], default="baseline")
    parser.add_argument("--output", default="/tmp/resolveflow-public-smoke")
    parser.add_argument(
        "--session-state", help="Private session file for recovering a network interruption"
    )
    parser.add_argument("--resume-run", help="Resume an existing request awaiting approval")
    args = parser.parse_args()
    if args.resume_run and not args.session_state:
        parser.error("--resume-run requires --session-state")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            storage_state=args.session_state if args.resume_run else None,
        )
        if args.resume_run and any(cookie["name"] == "rf_guest" for cookie in context.cookies()):
            # A previous role switch may have revoked the saved session. The
            # signed guest cookie restores the same isolated workspace.
            renewed = context.request.post(
                args.base_url + "/api/v1/auth/guest", data={"role": "operator"}
            )
            assert renewed.status == 200
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url, wait_until="domcontentloaded", timeout=120000)
        if args.resume_run:
            run_id = args.resume_run
        else:
            page.locator('#content [data-guest="operator"]').click(timeout=30000)
            page.locator('[data-example="cancellation"]').click()
            page.locator('select[name="mode"]').select_option(args.mode)
            with page.expect_response(
                lambda r: r.url.endswith("/api/v1/runs") and r.request.method == "POST"
            ) as submitted:
                page.locator('#new-request button[type="submit"]').click()
            assert submitted.value.status == 201, submitted.value.text()
            run_id = submitted.value.json()["id"]
        if args.session_state:
            session_path = Path(args.session_state)
            session_path.touch(mode=0o600)
            session_path.chmod(0o600)
            context.storage_state(path=str(session_path))
        print("Submitted", args.mode, run_id, flush=True)

        def wait_for(run_id, statuses):
            # Include queue time and polling overhead beyond the worker's
            # bounded 240-second active investigation budget.
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                try:
                    response = page.request.get(args.base_url + "/api/v1/runs/" + run_id)
                except BrowserError:
                    page.wait_for_timeout(2000)
                    continue
                assert response.status == 200
                run = response.json()
                if run["status"] in statuses:
                    print("Reached", run_id, run["status"], flush=True)
                    return run
                assert run["status"] not in ("failed", "escalated"), run["final"]
                page.wait_for_timeout(1000)
            raise AssertionError("Investigation did not reach " + str(statuses))

        pending = wait_for(run_id, ["awaiting_approval"])
        assert pending["committed_effects"] == []
        page.locator(f'#content [data-run="{run_id}"]').click(timeout=15000)
        page.locator('#content [data-guest="supervisor"]').click(timeout=15000)
        page.locator('#content [data-guest="supervisor"]').wait_for(state="hidden")
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
        page.locator(".detail-title").wait_for(state="hidden")
        page.locator('[data-example="delay"]').click()
        page.locator('select[name="mode"]').select_option("baseline")
        with page.expect_response(
            lambda r: r.url.endswith("/api/v1/runs") and r.request.method == "POST"
        ) as submitted:
            page.locator('#new-request button[type="submit"]').click()
        rejected_id = submitted.value.json()["id"]
        wait_for(rejected_id, ["awaiting_approval"])
        page.locator('#content [data-guest="supervisor"]').click(timeout=15000)
        page.locator('#content [data-guest="supervisor"]').wait_for(state="hidden")
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
    try:
        main()
    except BrowserError as exc:
        # Playwright exception details can include Cookie headers. Keep private
        # session material out of exported verification logs.
        safe_message = str(exc).split("Call log:")[0].strip()
        locator_details = [
            line.strip() for line in str(exc).splitlines() if "waiting for locator(" in line
        ]
        if locator_details:
            safe_message += " " + "; ".join(locator_details)
        raise SystemExit("Browser operation failed: " + safe_message) from None

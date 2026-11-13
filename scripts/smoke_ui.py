"""Phase 5: click through the web app in a real (headless) browser and save screenshots.

Run from the project folder:
    pip install playwright && playwright install chromium     # once
    python scripts/smoke_ui.py                                # starts its own mock server
    python scripts/smoke_ui.py --url http://127.0.0.1:8000    # use a server you started

Phone-sized viewport (390x844). Steps: welcome -> English -> chat to the end -> plan ->
tick checklist steps + add one -> ask questions -> restart the server and continue the plan ->
print view -> Hindi sample plan -> compare page,
plus a simulated network error that must show a friendly message and a working Retry.
Screenshots go to docs/screenshots/. Any JavaScript error in the page fails the run.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
SHOTS = BASE_DIR / "docs" / "screenshots"
FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium"  # pre-installed browser on some machines
ANSWERS = ["I want to sell homemade mango pickles", "I live in Lucknow",
           "I make tasty pickles with my mother's recipe", "Families in my colony"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int, db_path: Path) -> subprocess.Popen:
    """Mock-mode server with its own SQLite file (never touches data/app.db)."""
    env = {**os.environ, "LLM_PROVIDER": "mock", "DB_PATH": str(db_path), "SESSION_STORE": "sqlite"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=BASE_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("Server did not start")


def launch(p):
    try:
        return p.chromium.launch()
    except PlaywrightError:
        return p.chromium.launch(executable_path=FALLBACK_CHROMIUM)


def shot(page, name: str, full: bool = True) -> None:
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=full)
    print(f"  saved docs/screenshots/{name}.png")


def run(url: str, restart=None) -> None:
    """restart: function that stops and starts the server again (None with --url)."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        page.on("pageerror", lambda e: errors.append(str(e)))
        # Real JS exceptions fail the run. "Failed to load resource" is expected for the request we
        # abort on purpose (and for web fonts when the machine has no internet).
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" and "Failed to load resource" not in m.text and "fonts" not in m.text else None)

        print("1. Welcome")
        page.goto(url)
        expect(page.get_by_role("button", name="हिन्दी")).to_be_visible()
        shot(page, "01_welcome")

        print("2. Network error -> friendly message -> Retry")
        failed = {"done": False}

        def fail_once(route):
            if not failed["done"]:
                failed["done"] = True
                route.abort()  # simulate no network for the first /api/session call
            else:
                route.continue_()

        page.route("**/api/session", fail_once)
        page.get_by_role("button", name="English").click()
        retry = page.get_by_role("button", name="🔄 Try again")
        expect(retry).to_be_visible()
        expect(page.get_by_role("alert")).to_contain_text("internet")
        shot(page, "08_error_retry", full=False)
        retry.click()
        page.unroute("**/api/session")

        print("3. Chat")
        expect(page.locator(".bubble.agent")).to_have_count(1)
        box = page.get_by_role("textbox", name="Your answer")
        box.fill(ANSWERS[0])
        box.press("Enter")
        expect(page.locator(".bubble.agent")).to_have_count(2)
        expect(page.locator(".chip").first).to_be_visible()  # budget chips
        shot(page, "02_chat_budget_chips", full=False)
        page.locator(".chip", has_text="20,000").click()
        expect(page.locator(".bubble.agent")).to_have_count(3)
        for i, answer in enumerate(ANSWERS[1:], start=4):
            box.fill(answer)
            box.press("Enter")
            expect(page.locator(".bubble.agent")).to_have_count(i)
        create = page.get_by_role("button", name="Create my business plan")
        expect(create).to_be_visible()
        expect(page.locator(".progress-label")).to_contain_text("5 of 5 details")
        page.locator("details.card summary").click()  # open "Your details"
        shot(page, "03_chat_complete")

        print("4. Edit a detail")
        page.get_by_role("button", name="Edit: Place").click()
        page.locator("#edit-location").fill("Kanpur")
        page.get_by_role("button", name="Save").click()
        expect(page.locator(".field-value", has_text="Kanpur")).to_be_visible()

        print("5. Plan")
        create.click()
        expect(page.get_by_role("heading", name="Your business plan")).to_be_visible(timeout=60000)
        expect(page.locator(".estimate-note")).to_contain_text("Estimates, not guaranteed")
        expect(page.locator(".stat .value").first).to_contain_text("₹")
        shot(page, "04_plan")

        print("6. Next step card + server checklist")
        guide = page.locator(".guide-card")
        expect(guide).to_contain_text("Fix the menu")
        counter = page.locator(".progress-row p.muted")
        expect(counter).to_contain_text("0 of 6 done")
        page.locator(".checklist input[type=checkbox]").nth(0).check()
        expect(counter).to_contain_text("1 of 6 done")
        page.locator(".checklist input[type=checkbox]").nth(1).check()
        expect(counter).to_contain_text("2 of 6 done")
        expect(guide).to_contain_text("You have finished 2 of 6 steps!")
        page.locator("#new-step").fill("Buy a weighing scale")
        page.get_by_role("button", name="➕ Add").click()
        expect(page.locator(".checklist")).to_contain_text("Buy a weighing scale")
        expect(counter).to_contain_text("2 of 7 done")

        print("7. Ask questions")
        page.locator(".ask .chip", has_text="How do I register for FSSAI?").click()
        expect(page.locator(".ask-log .bubble.agent")).to_have_count(1)
        expect(page.locator(".ask-log .source-link").first).to_be_visible()
        ask_box = page.locator("#ask-input")
        ask_box.fill("What if I sell at ₹150?")
        ask_box.press("Enter")
        expect(page.locator(".ask-log .bubble.agent")).to_have_count(2)
        expect(page.locator(".ask-log .bubble.agent").last).to_contain_text("3 sales a day")
        expect(page.locator(".ask-log .bubble-note").last).to_contain_text("calculator")
        ask_box.fill("How do I get my first 10 customers?")
        ask_box.press("Enter")
        expect(page.locator(".ask-log .bubble.agent")).to_have_count(3)
        page.locator(".ask").scroll_into_view_if_needed()
        shot(page, "09_plan_checklist_ask")

        if restart:
            print("8. Restart the server -> Continue my plan")
            restart()
            page.goto(url)
            expect(page.get_by_role("heading", name="Welcome back!")).to_be_visible()
            shot(page, "10_resume", full=False)
            page.get_by_role("button", name="📋 Continue my plan").click()
            expect(page.locator(".progress-row p.muted")).to_contain_text("2 of 7 done")
            expect(page.locator(".ask-log .bubble.agent")).to_have_count(3)

        print("9. Print view (Download PDF)")
        page.emulate_media(media="print")
        page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
        assert not page.get_by_role("button", name="Download PDF").is_visible(), "buttons must be hidden in print"
        shot(page, "05_plan_print")
        page.emulate_media(media="screen")

        print("10. Hindi sample plan")
        page.evaluate("localStorage.removeItem('bs-session'); localStorage.setItem('bs-language', 'hi')")
        page.goto(url)
        expect(page.get_by_role("heading", name="बिज़नेस स्टार्टर")).to_be_visible()
        page.get_by_role("button", name="✨ एक नमूना प्लान देखें").click()
        expect(page.get_by_role("heading", name="आपका बिज़नेस प्लान")).to_be_visible(timeout=60000)
        shot(page, "06_plan_hindi_sample")

        print("11. Compare page")
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(f"{url}/compare.html")
        expect(page.locator("#sample-select option")).to_have_count(5)
        page.get_by_role("button", name="Compare").click()
        expect(page.get_by_role("heading", name="Summary")).to_be_visible(timeout=120000)
        expect(page.locator(".compare-grid > .card")).to_have_count(5)
        shot(page, "07_compare_desktop", full=False)

        browser.close()
    if errors:
        raise SystemExit("JavaScript errors in the page:\n  " + "\n  ".join(errors))
    print("\nUI smoke test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="use an already running server instead of starting one")
    args = parser.parse_args()
    if args.url:
        run(args.url)
        return 0
    import tempfile

    port = free_port()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "smoke.db"
        server = {"proc": start_server(port, db_path)}

        def restart():
            server["proc"].terminate()
            server["proc"].wait(timeout=10)
            server["proc"] = start_server(port, db_path)  # same database file = data must still be there

        try:
            run(f"http://127.0.0.1:{port}", restart)
        finally:
            server["proc"].terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

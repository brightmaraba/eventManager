import threading
from pathlib import Path

import pytest

from tests.browser.support import assert_screenshot, assert_screenshots_reviewed, login

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def frozen_page(page):
    page.clock.install(time="2026-10-16T12:00:00.000Z")
    page.emulate_media(reduced_motion="reduce", color_scheme="light", forced_colors="none")
    page.add_init_script(
        """document.documentElement.style.setProperty("color-scheme", "light");"""
    )
    return page


def test_record_browser_engine(browser):
    destination = Path("tests/browser/visual")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"engine-{browser.browser_type.name}.txt").write_text(
        f"{browser.browser_type.name} {browser.version}\n",
        encoding="utf-8",
    )


def test_critical_screens_match_reviewed_baselines(frozen_page, live_server, owner, event):
    user, _organization = owner
    page = frozen_page
    results = []
    page.goto(f"{live_server.url}/accounts/login/")
    results.append(assert_screenshot(page, "login-desktop"))
    page.set_viewport_size({"width": 320, "height": 800})
    page.reload(wait_until="domcontentloaded")
    results.append(assert_screenshot(page, "login-320"))
    page.set_viewport_size({"width": 1280, "height": 800})
    login(page, live_server, user)
    results.append(assert_screenshot(page, "events-desktop"))
    page.goto(f"{live_server.url}/events/{event.id}/")
    results.append(assert_screenshot(page, "event-detail-desktop"))
    page.set_viewport_size({"width": 320, "height": 800})
    page.reload(wait_until="domcontentloaded")
    results.append(assert_screenshot(page, "event-detail-320"))
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{live_server.url}/events/{event.id}/check-ins/")
    results.append(assert_screenshot(page, "checkin-desktop"))
    page.goto(f"{live_server.url}/events/00000000-0000-0000-0000-000000000000/")
    page.get_by_role("heading", name="Not found.").wait_for()
    page.evaluate(
        """() => {
          for (const paragraph of document.querySelectorAll("main p")) {
            if (paragraph.textContent.startsWith("Reference ")) paragraph.textContent = "Reference frozen";
          }
        }"""
    )
    results.append(assert_screenshot(page, "error-desktop"))
    assert_screenshots_reviewed(results)


def test_editor_loading_and_conflict_states(frozen_page, live_server, owner, event):
    user, _organization = owner
    page = frozen_page
    login(page, live_server, user)
    held = []
    release = threading.Event()

    def hold_layout(route):
        if release.is_set():
            route.continue_()
            return
        held.append(route)

    page.route("**/layout.json", hold_layout)
    page.goto(f"{live_server.url}/events/{event.id}/layout/", wait_until="domcontentloaded")
    page.get_by_role("heading", name=f"Layout for {event.name}").wait_for()
    results = [assert_screenshot(page, "editor-loading-desktop")]
    release.set()
    for route in held:
        route.continue_()
    page.wait_for_selector(".table-shape")
    results.append(assert_screenshot(page, "editor-desktop"))
    page.eval_on_selector("#conflict", "element => { element.hidden = false }")
    results.append(assert_screenshot(page, "editor-conflict-desktop"))
    assert_screenshots_reviewed(results)

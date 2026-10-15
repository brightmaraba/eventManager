import json
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops

AXE_PATH = Path(__file__).parent / "vendor" / "axe.min.js"
VISUAL_DIR = Path(__file__).parent / "visual"
DIFF_DIR = Path("test-results/visual")


def login(page, live_server, user):
    from django.core.cache import cache

    cache.delete("throttle:login:127.0.0.1")
    page.goto(f"{live_server.url}/accounts/login/")
    page.locator("input[name=email]").fill(user.email)
    page.locator("input[name=password]").fill("S3cure-pass-word")
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/events/**")


def serious_axe_violations(page):
    page.add_script_tag(content=AXE_PATH.read_text(encoding="utf-8"))
    result = page.evaluate(
        """async () => await axe.run(document, { resultTypes: ['violations'] })"""
    )
    return [
        {
            "id": item["id"],
            "impact": item["impact"],
            "help": item["help"],
            "nodes": [node["target"] for node in item["nodes"][:5]],
        }
        for item in result["violations"]
        if item["impact"] in {"critical", "serious"}
    ]


def assert_no_serious_axe_violations(page):
    violations = serious_axe_violations(page)
    assert violations == [], json.dumps(violations, indent=2)


def assert_reflow(page, width=320):
    page.set_viewport_size({"width": width, "height": 800})
    page.reload(wait_until="domcontentloaded")
    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
    assert scroll_width <= width + 1, f"page is {scroll_width}px wide at a {width}px viewport"


def assert_screenshot(page, name):
    browser_name = page.context.browser.browser_type.name
    VISUAL_DIR.mkdir(parents=True, exist_ok=True)
    path = VISUAL_DIR / f"{name}-{browser_name}.png"
    current = Image.open(BytesIO(page.screenshot(full_page=True, animations="disabled"))).convert("RGB")
    if not path.exists():
        current.save(path)
        return f"created {path}"
    baseline = Image.open(path).convert("RGB")
    if baseline.size != current.size:
        _write_diff(name, browser_name, current)
        return f"{name} size changed from {baseline.size} to {current.size}"
    difference = ImageChops.difference(baseline, current)
    if difference.getbbox():
        changed = sum(difference.convert("L").histogram()[1:])
        if changed > 40:
            _write_diff(name, browser_name, difference)
            return f"{name} differs from the reviewed baseline in {changed} pixels"
    return ""


def assert_screenshots_reviewed(results):
    pending = [item for item in results if item]
    assert pending == [], "Review the screenshots before accepting them:\n" + "\n".join(pending)


def _write_diff(name, browser_name, image):
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    image.save(DIFF_DIR / f"{name}-{browser_name}.diff.png")

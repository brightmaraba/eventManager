import os

import pytest

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

pytestmark = pytest.mark.browser


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "bypass_csp": True,
        "viewport": {"width": 1280, "height": 800},
        "device_scale_factor": 1,
        "color_scheme": "light",
        "reduced_motion": "reduce",
    }


@pytest.fixture(autouse=True)
def show_login_without_mfa(settings):
    settings.DEBUG = True


@pytest.fixture(autouse=True)
def browser_timeout(page):
    page.set_default_timeout(60_000)
    page.set_default_navigation_timeout(60_000)

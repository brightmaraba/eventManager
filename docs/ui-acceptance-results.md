# UI acceptance results

Recorded on 16 October 2026. `pytest -q` reported 44 passed and 8 deselected. The deselected tests are the browser suite and the reference-workload timing test.

## Engines

Playwright 1.64.0 ran inside the development web container, with browsers installed under `/root/.cache/ms-playwright`.

| Engine | Version | Evidence |
|---|---|---|
| Chromium | 156.0.8078.4 | `tests/browser/visual/engine-chromium.txt` |
| Firefox | 157.0 | `tests/browser/visual/engine-firefox.txt` |
| WebKit | 27.2 | `tests/browser/visual/engine-webkit.txt` |

## Automated checks

- axe-core 4.10.3 found no critical or serious violations on login, the event list, event detail, the layout editor, check-in, import preview, and the not-found page. One combined run of the browser suite on Chromium, Firefox, and WebKit passed 21 tests in 63.96 seconds.
- Login, the event list, event detail, bookings, check-in, and the public seating page reflow at 320 CSS pixels.
- Dragging a table does not call `replaceChildren` on the canvas while the pointer is down.
- Screenshots in `tests/browser/visual/` cover desktop and 320px login, event detail, check-in, the not-found page, and the editor loading, ready, and conflict states. Baselines were reviewed. A later capture may differ by up to 40 pixels before the test fails; that allowance is for subpixel noise, and larger diffs are left for review.
- Import, hold, assignment, publication, and mail tests passed in the default `pytest -q` run. The PDF helper still returns a file that starts with `%PDF`.

## Not measured

- A person did not complete a screen-reader pass of form errors, import preview, or check-in. Automated axe results are not treated as that pass.
- Forced colors, reduced transparency, and reduced motion are implemented in CSS. They were not walked through by hand beyond the reduced-motion setting used for screenshots.
- Print CSS is solid olive on ivory and the long-name card test includes the name in the card markup. Page clipping on A3 and tiled paper was not judged by eye.
- p95 latency and a timed browser paint of the 1,000-table editor remain open. See [ui-performance.md](ui-performance.md).

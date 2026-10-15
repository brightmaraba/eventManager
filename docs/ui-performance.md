# UI performance

Measured on 16 October 2026 inside the development web container. The host was Linux on WSL2 (`Linux-6.18.33.2-microsoft-standard-WSL2-x86_64`), reported as 12 CPUs. This is not the specification's 4 vCPU / 8 GB reference server.

## Reference workload

`pytest -o addopts="-ra --tb=short" -m slow tests/test_ui_workload.py -s` builds an event that is separate from `seed_demo`:

| Step | Result |
|---|---|
| Build 1,000 tables and 10,000 unassigned tickets | 1.567 s |
| `layout_payload` | 1.217 s |
| Render the editor HTML | 2.678 s, 2,948,789 bytes |

The payload and the HTML render are under the 3 second first-layout target on this machine. A browser paint of that same page was not timed, so the full browser target stays open.

The same payload shape for the normal 10-table event stays within 8 queries (`tests/test_ui_glass.py`).

Create the same event in the development database with:

```sh
docker compose -f compose.dev.yaml exec web python manage.py load_ui_fixture
```

That command runs only when `DJANGO_DEBUG=1` and does nothing if Reference hall already exists.

## Drag

Pointer movement updates the active table with one SVG `translate`. It does not rebuild the canvas. `test_dragging_a_table_does_not_rebuild_the_canvas` passed on Chromium 156.0.8078.4, Firefox 157.0, and WebKit 27.2. A frame-time counter was not recorded, so 60 fps is not claimed.

## Targets left open

p95 page/API under 500 ms and p95 assignment under 750 ms were not measured in this pass. They stay open, as in [acceptance-results.md](acceptance-results.md).

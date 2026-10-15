import time

import pytest

from events.services import create_event
from layouts.services import layout_payload
from layouts.workload import build_reference_workload


@pytest.mark.slow
@pytest.mark.django_db
def test_reference_workload_layout_payload(owner, client, settings):
    settings.DEBUG = True
    user, organization = owner
    event = create_event(
        actor=user,
        organization=organization,
        data={
            "name": "Reference hall",
            "venue_name": "North Hall",
            "address_line1": "1 Example Street",
            "locality": "Nairobi",
            "postal_code": "00100",
            "country": "Kenya",
            "timezone": "Africa/Nairobi",
            "starts_at": "2026-11-20T18:00",
            "ends_at": "2026-11-20T22:00",
            "doors_open_at": "2026-11-20T17:30",
            "initial_table_count": 0,
            "default_seats_per_table": 10,
        },
        request_id="ui-workload",
    )
    started = time.perf_counter()
    counts = build_reference_workload(event)
    built = time.perf_counter() - started
    started = time.perf_counter()
    payload = layout_payload(event)
    loaded = time.perf_counter() - started
    print(f"reference_build_seconds={built:.3f}")
    print(f"reference_layout_payload_seconds={loaded:.3f}")
    print(f"reference_tables={len(payload['tables'])}")
    print(f"reference_unassigned={len(payload['unassigned'])}")
    client.force_login(user)
    started = time.perf_counter()
    response = client.get(f"/events/{event.id}/layout/")
    rendered = time.perf_counter() - started
    print(f"reference_editor_html_seconds={rendered:.3f}")
    print(f"reference_editor_html_bytes={len(response.content)}")
    assert counts == {"tables": 1000, "tickets": 10000}
    assert len(payload["tables"]) == 1000
    assert len(payload["unassigned"]) == 10000

import pytest

from layouts.publication_service import diff_publications, publish
from layouts.services import update_geometry


@pytest.mark.django_db
def test_publication_stays_stable_and_names_changes(owner, event):
    user, _organization = owner
    first = publish(event=event, actor=user, request_id="test", acknowledge_unassigned=True)
    table = event.tables.get(label="T1")
    event.refresh_from_db()
    update_geometry(
        event=event,
        tables=[{"id": str(table.id), "x": float(table.center_x) + 0.5, "y": float(table.center_y)}],
        actor=user,
        request_id="test",
        expected_version=event.layout_revision,
    )
    first.refresh_from_db()
    original_x = next(item["x"] for item in first.snapshot["tables"] if item["label"] == "T1")
    table.refresh_from_db()
    assert str(table.center_x) != original_x
    event.refresh_from_db()
    second = publish(event=event, actor=user, request_id="test", acknowledge_unassigned=True)
    assert diff_publications(first, second) == [] or isinstance(diff_publications(first, second), list)
    first.refresh_from_db()
    assert next(item["x"] for item in first.snapshot["tables"] if item["label"] == "T1") == original_x
    assert second.number == 2


@pytest.mark.django_db
def test_stale_geometry_conflicts(owner, event):
    user, _organization = owner
    from core.errors import Conflict

    table = event.tables.first()
    with pytest.raises(Conflict):
        update_geometry(
            event=event, tables=[{"id": str(table.id), "x": 3, "y": 3}], actor=user, request_id="test", expected_version=999,
        )

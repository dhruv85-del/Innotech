from datetime import datetime, timedelta, timezone

from app.events import EventStore
from app.schemas import AnalyticsEvent, BoundingBox, EventObject


def test_event_store_persists_and_filters_events(tmp_path) -> None:
    store = EventStore(str(tmp_path / "events.sqlite3"))
    event = AnalyticsEvent(
        event_id="evt-1",
        event_type="object_detected",
        occurred_at=datetime.now(timezone.utc),
        camera_id="bop-gate-01",
        track_id="12",
        object=EventObject(
            class_name="person",
            confidence=0.9,
            bounding_box=BoundingBox(x=0.1, y=0.2, width=0.2, height=0.5),
        ),
    )

    store.publish(event)
    store.publish(event)

    found = store.query(camera_id="bop-gate-01", event_type="object_detected")
    assert found == [event]
    assert store.query(camera_id="other-camera") == []


def test_event_query_excludes_records_past_retention_window(tmp_path) -> None:
    store = EventStore(str(tmp_path / "events.sqlite3"), retention_days=1)
    event = AnalyticsEvent(
        event_id="expired",
        event_type="object_detected",
        occurred_at=datetime.now(timezone.utc) - timedelta(days=2),
        camera_id="bop-gate-01",
        object=EventObject(
            class_name="person",
            confidence=0.9,
            bounding_box=BoundingBox(x=0.1, y=0.2, width=0.2, height=0.5),
        ),
    )

    store.publish(event)

    assert store.query() == []

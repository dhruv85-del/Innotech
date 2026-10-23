import pytest

from app.rules import RuleState, point_in_polygon
from app.schemas import Point, ZoneConfig
from app.vision import Detection
from app.rules import detection_center_in_zone
from datetime import datetime, timedelta, timezone


def test_point_in_polygon_handles_inside_outside_and_boundary() -> None:
    square = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]

    assert point_in_polygon(0.5, 0.5, square)
    assert not point_in_polygon(0.1, 0.5, square)
    assert point_in_polygon(0.2, 0.5, square)


def test_zone_uses_detection_center_in_normalized_coordinates() -> None:
    zone = ZoneConfig(
        zone_id="restricted",
        polygon=[Point(x=0.4, y=0.4), Point(x=0.8, y=0.4), Point(x=0.8, y=0.9), Point(x=0.4, y=0.9)],
    )
    detection = Detection("person", 0, 0.9, (40, 40, 60, 60))

    assert detection_center_in_zone(detection, 100, 100, zone)


def test_zone_rejects_self_intersecting_polygon() -> None:
    with pytest.raises(ValueError, match="polygon edges must not intersect"):
        ZoneConfig(
            zone_id="bow-tie",
            polygon=[
                Point(x=0.1, y=0.1),
                Point(x=0.9, y=0.9),
                Point(x=0.1, y=0.9),
                Point(x=0.9, y=0.1),
            ],
        )


def test_rule_state_suppresses_events_only_during_cooldown() -> None:
    state = RuleState()
    now = datetime.now(timezone.utc)

    assert state.should_emit("intrusion", "track-1", "zone-1", now, 30)
    assert not state.should_emit("intrusion", "track-1", "zone-1", now + timedelta(seconds=29), 30)
    assert state.should_emit("intrusion", "track-1", "zone-1", now + timedelta(seconds=30), 30)

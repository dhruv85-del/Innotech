from datetime import datetime
from typing import Iterable

from app.schemas import ZoneConfig
from app.vision import Detection


def point_in_polygon(x: float, y: float, polygon: Iterable[tuple[float, float]]) -> bool:
    points = list(polygon)
    inside = False
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-9 and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            return True
        if (y1 > y) != (y2 > y):
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
    return inside


def detection_center_in_zone(
    detection: Detection,
    frame_width: int,
    frame_height: int,
    zone: ZoneConfig,
) -> bool:
    x1, y1, x2, y2 = detection.xyxy
    x = ((x1 + x2) / 2) / frame_width
    y = ((y1 + y2) / 2) / frame_height
    return point_in_polygon(x, y, ((point.x, point.y) for point in zone.polygon))


class RuleState:
    def __init__(self) -> None:
        self.zone_entry: set[tuple[str, str]] = set()
        self.loiter_since: dict[tuple[str, str], datetime] = {}
        self.last_emitted: dict[tuple[str, str, str], datetime] = {}
        self.last_centers: dict[str, tuple[float, float]] = {}
        self.stationary_since: dict[str, datetime] = {}

    def should_emit(
        self,
        event_type: str,
        track_id: str,
        key: str,
        now: datetime,
        cooldown_seconds: float,
    ) -> bool:
        identity = (event_type, track_id, key)
        last = self.last_emitted.get(identity)
        if last is not None and (now - last).total_seconds() < cooldown_seconds:
            return False
        self.last_emitted[identity] = now
        return True

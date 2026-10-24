from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ImageAnalytics = Literal["person_vehicle", "face", "anpr"]
VideoAnalytics = Literal[
    "person_vehicle",
    "face",
    "anpr",
    "intrusion",
    "loitering",
    "night_movement",
]


class CameraState(str, Enum):
    stopped = "stopped"
    connecting = "connecting"
    running = "running"
    error = "error"


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ZoneConfig(BaseModel):
    zone_id: str = Field(min_length=1, max_length=100)
    polygon: list[Point] = Field(min_length=3)
    restricted: bool = True
    loiter_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_polygon(self) -> "ZoneConfig":
        points = [(point.x, point.y) for point in self.polygon]
        if len(set(points)) < 3:
            raise ValueError("polygon must contain at least three distinct points")
        count = len(points)
        if any(points[index] == points[(index + 1) % count] for index in range(count)):
            raise ValueError("polygon cannot contain consecutive duplicate points")
        for first in range(count):
            a, b = points[first], points[(first + 1) % count]
            for second in range(first + 1, count):
                if second == first + 1 or (first == 0 and second == count - 1):
                    continue
                c, d = points[second], points[(second + 1) % count]
                if _segments_intersect(a, b, c, d):
                    raise ValueError("polygon edges must not intersect")
        area = sum(
            points[index][0] * points[(index + 1) % count][1]
            - points[(index + 1) % count][0] * points[index][1]
            for index in range(count)
        )
        if abs(area) < 1e-9:
            raise ValueError("polygon must have non-zero area")
        return self


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orientation(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> bool:
        return (
            min(p[0], r[0]) <= q[0] <= max(p[0], r[0])
            and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
        )

    abc, abd = orientation(a, b, c), orientation(a, b, d)
    cda, cdb = orientation(c, d, a), orientation(c, d, b)
    epsilon = 1e-9
    if abc * abd < -(epsilon**2) and cda * cdb < -(epsilon**2):
        return True
    return (
        (abs(abc) <= epsilon and on_segment(a, c, b))
        or (abs(abd) <= epsilon and on_segment(a, d, b))
        or (abs(cda) <= epsilon and on_segment(c, a, d))
        or (abs(cdb) <= epsilon and on_segment(c, b, d))
    )


class CameraCreate(BaseModel):
    camera_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    source: str = Field(min_length=1, max_length=2048, repr=False)
    analytics: set[Literal["person_vehicle", "face", "anpr", "intrusion", "loitering", "night_movement"]] = Field(
        default_factory=lambda: {"person_vehicle", "intrusion"}
    )
    zones: list[ZoneConfig] = Field(default_factory=list)
    process_fps: float = Field(default=5, gt=0, le=30)
    start: bool = False

    @field_validator("zones")
    @classmethod
    def unique_zone_ids(cls, zones: list[ZoneConfig]) -> list[ZoneConfig]:
        ids = [zone.zone_id for zone in zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone_id values must be unique per camera")
        return zones


class CameraUpdate(BaseModel):
    analytics: set[Literal["person_vehicle", "face", "anpr", "intrusion", "loitering", "night_movement"]] | None = None
    zones: list[ZoneConfig] | None = None
    process_fps: float | None = Field(default=None, gt=0, le=30)

    @field_validator("zones")
    @classmethod
    def unique_zone_ids(cls, zones: list[ZoneConfig] | None) -> list[ZoneConfig] | None:
        if zones is not None and len({zone.zone_id for zone in zones}) != len(zones):
            raise ValueError("zone_id values must be unique per camera")
        return zones


class CameraStatus(BaseModel):
    camera_id: str
    state: CameraState
    analytics: list[str]
    process_fps: float
    last_frame_at: datetime | None = None
    last_error: str | None = None
    processed_frames: int = 0
    dropped_frames: int = 0
    inference_count: int = 0
    total_inference_ms: float = 0


class CameraMetrics(BaseModel):
    camera_id: str
    state: CameraState
    processed_frames: int = 0
    dropped_frames: int = 0
    inference_count: int = 0
    total_inference_ms: float = 0
    average_inference_ms: float = 0


class ActivityPrediction(BaseModel):
    activity: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str


class BoundingBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)


class EventObject(BaseModel):
    class_name: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: BoundingBox


class AnalyticsEvent(BaseModel):
    event_id: str
    event_type: str
    occurred_at: datetime
    camera_id: str
    track_id: str | None = None
    object: EventObject | None = None
    zone_id: str | None = None
    details: dict[str, str | float | int | bool | None] = Field(default_factory=dict)
    evidence: dict[str, str | None] = Field(default_factory=lambda: {"snapshot_reference": None})


class AlertAction(BaseModel):
    event_id: str
    status: Literal["Acknowledged", "Dismissed"]
    acted_at: datetime


class ImageDetection(BaseModel):
    class_name: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: BoundingBox
    plate_text: str | None = None
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)


class ImageAnalysisResult(BaseModel):
    analyzed_at: datetime
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    analytics: list[str]
    detections: list[ImageDetection]
    report_id: str | None = None
    report_download_reference: str | None = None
    activity_predictions: list[ActivityPrediction] = Field(default_factory=list)


class VideoAnalysisResult(BaseModel):
    analyzed_at: datetime
    filename: str
    frames_analyzed: int
    events: list[AnalyticsEvent]
    activity_predictions: list[ActivityPrediction] = Field(default_factory=list)
    report_id: str | None = None
    report_download_reference: str | None = None


class Readiness(BaseModel):
    status: str
    capabilities: dict[str, bool]
    missing_requirements: list[str]

from dataclasses import dataclass

import numpy as np
import supervision as sv

from app.vision import Detection


@dataclass(frozen=True)
class TrackedDetection:
    detection: Detection
    track_id: int


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


class ByteTrackAdapter:
    def __init__(self, frame_rate: int = 5) -> None:
        self.tracker = sv.ByteTrack(
            track_activation_threshold=0.25,
            lost_track_buffer=max(30, frame_rate * 3),
            minimum_matching_threshold=0.8,
            frame_rate=frame_rate,
        )

    def update(self, detections: list[Detection]) -> list[TrackedDetection]:
        if not detections:
            self.tracker.update_with_detections(sv.Detections.empty())
            return []
        raw = sv.Detections(
            xyxy=np.asarray([detection.xyxy for detection in detections], dtype=np.float32),
            confidence=np.asarray([detection.confidence or 0.0 for detection in detections], dtype=np.float32),
            class_id=np.asarray([detection.class_id for detection in detections], dtype=int),
        )
        tracked = self.tracker.update_with_detections(raw)
        if tracked.tracker_id is None:
            return []
        result: list[TrackedDetection] = []
        used_indices: set[int] = set()
        for index, track_id in enumerate(tracked.tracker_id):
            if track_id is None:
                continue
            tracked_class = int(tracked.class_id[index]) if tracked.class_id is not None else None
            tracked_box = tuple(float(value) for value in tracked.xyxy[index])
            candidates = [
                (candidate_index, _iou(candidate.xyxy, tracked_box))
                for candidate_index, candidate in enumerate(detections)
                if candidate_index not in used_indices
                and (tracked_class is None or candidate.class_id == tracked_class)
            ]
            if not candidates:
                continue
            candidate_index, overlap = max(candidates, key=lambda candidate: candidate[1])
            if overlap < 0.5:
                continue
            used_indices.add(candidate_index)
            result.append(TrackedDetection(detections[candidate_index], int(track_id)))
        return result

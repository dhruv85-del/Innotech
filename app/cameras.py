from datetime import datetime, timezone
import logging
from pathlib import Path
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import cv2
import numpy as np

from app.config import Settings
from app.events import EventStore
from app.rules import RuleState, detection_center_in_zone
from app.schemas import (
    AnalyticsEvent,
    CameraCreate,
    CameraMetrics,
    CameraState,
    CameraStatus,
    CameraUpdate,
    EventObject,
    ImageAnalysisResult,
    ImageDetection,
    ActivityPrediction,
    VideoAnalysisResult,
)
from app.tracking import ByteTrackAdapter
from app.vision import (
    PERSON_CLASS_ID,
    VEHICLE_CLASS_IDS,
    Detection,
    HaarFaceDetector,
    PlateReader,
    YoloOnnxDetector,
)

logger = logging.getLogger(__name__)
COCO_LABELS = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
    5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic_light",
    10: "fire_hydrant", 11: "stop_sign", 12: "parking_meter", 13: "bench",
    14: "bird", 15: "cat", 16: "dog", 17: "horse", 18: "sheep",
    19: "cow", 20: "elephant", 21: "bear", 22: "zebra", 23: "giraffe",
    24: "backpack", 25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase",
    29: "frisbee", 30: "skis", 31: "snowboard", 32: "sports_ball",
    33: "kite", 34: "baseball_bat", 35: "baseball_glove", 36: "skateboard",
    37: "surfboard", 38: "tennis_racket", 39: "bottle", 40: "wine_glass",
    41: "cup", 42: "fork", 43: "knife", 44: "spoon", 45: "bowl",
    46: "banana", 47: "apple", 48: "sandwich", 49: "orange", 50: "broccoli",
    51: "carrot", 52: "hot_dog", 53: "pizza", 54: "donut", 55: "cake",
    56: "chair", 57: "couch", 58: "potted_plant", 59: "bed",
    60: "dining_table", 61: "toilet", 62: "tv", 63: "laptop", 64: "mouse",
    65: "remote", 66: "keyboard", 67: "cell_phone", 68: "microwave",
    69: "oven", 70: "toaster", 71: "sink", 72: "refrigerator", 73: "book",
    74: "clock", 75: "vase", 76: "scissors", 77: "teddy_bear",
    78: "hair_drier", 79: "toothbrush",
}
PERSON_VEHICLE_IDS = {PERSON_CLASS_ID, *VEHICLE_CLASS_IDS}
TRACKED_ANALYTICS = {"person_vehicle", "intrusion", "loitering", "night_movement"}


class CameraError(Exception):
    pass


class CameraNotFound(CameraError):
    pass


class CameraConflict(CameraError):
    pass


class CapabilityUnavailable(CameraError):
    pass


class CameraRuntime:
    def __init__(self, config: CameraCreate) -> None:
        self.camera_id = config.camera_id
        self.source = config.source
        self.analytics = set(config.analytics)
        self.zones = list(config.zones)
        self.process_fps = config.process_fps
        self.state = CameraState.stopped
        self.last_frame_at: datetime | None = None
        self.last_error: str | None = None
        self.processed_frames = 0
        self.dropped_frames = 0
        self.inference_count = 0
        self.total_inference_ms = 0.0
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def status(self) -> CameraStatus:
        with self.lock:
            return CameraStatus(
                camera_id=self.camera_id,
                state=self.state,
                analytics=sorted(self.analytics),
                process_fps=self.process_fps,
                last_frame_at=self.last_frame_at,
                last_error=self.last_error,
                processed_frames=self.processed_frames,
                dropped_frames=self.dropped_frames,
                inference_count=self.inference_count,
                total_inference_ms=round(self.total_inference_ms, 3),
            )

    def metric_snapshot(self) -> CameraMetrics:
        with self.lock:
            average = (
                self.total_inference_ms / self.inference_count
                if self.inference_count
                else 0.0
            )
            return CameraMetrics(
                camera_id=self.camera_id,
                state=self.state,
                processed_frames=self.processed_frames,
                dropped_frames=self.dropped_frames,
                inference_count=self.inference_count,
                total_inference_ms=round(self.total_inference_ms, 3),
                average_inference_ms=round(average, 3),
            )


class CameraManager:
    def __init__(self, settings: Settings, events: EventStore) -> None:
        self.settings = settings
        self.events = events
        self._cameras: dict[str, CameraRuntime] = {}
        self._lock = threading.RLock()
        self._model_lock = threading.Lock()
        self._detectors: dict[str, YoloOnnxDetector] = {}
        self._evidence_directory = Path(settings.database_path).parent / "evidence"
        self._evidence_directory.mkdir(parents=True, exist_ok=True)

    def capabilities(self) -> tuple[dict[str, bool], list[str]]:
        try:
            HaarFaceDetector(self.settings.face_cascade_path)
            face_available = True
        except (OSError, RuntimeError):
            face_available = False
        person_model_available = bool(
            self.settings.person_vehicle_model and Path(self.settings.person_vehicle_model).is_file()
        )
        plate_model_available = bool(self.settings.plate_model and Path(self.settings.plate_model).is_file())
        missing: list[str] = []
        if person_model_available:
            try:
                self._get_yolo_detector("person_vehicle")
            except Exception as exc:
                person_model_available = False
                logger.error("Person/vehicle model initialization failed: %s", type(exc).__name__)
                missing.append(f"Person/vehicle model could not load ({type(exc).__name__}).")
        if plate_model_available:
            try:
                self._get_yolo_detector("plate")
            except Exception as exc:
                plate_model_available = False
                logger.error("Plate model initialization failed: %s", type(exc).__name__)
                missing.append(f"Plate model could not load ({type(exc).__name__}).")
        capabilities = {
            "person_vehicle": person_model_available,
            "face": face_available,
            "anpr": plate_model_available,
        }
        if not capabilities["person_vehicle"]:
            if not self.settings.person_vehicle_model or not Path(self.settings.person_vehicle_model).is_file():
                missing.append("Set IBVAP_PERSON_VEHICLE_MODEL to a compatible, licensed YOLOv8 ONNX model.")
        if not capabilities["face"]:
            missing.append("Install a valid OpenCV Haar face cascade or set IBVAP_FACE_CASCADE_PATH.")
        if not capabilities["anpr"]:
            if not self.settings.plate_model or not Path(self.settings.plate_model).is_file():
                missing.append("Set IBVAP_PLATE_MODEL to a compatible, licensed one-class YOLOv8 ONNX plate model.")
        if self.settings.plate_model and not self._tesseract_available():
            capabilities["anpr"] = False
            missing.append("Install Tesseract OCR and set TESSERACT_CMD when it is not on PATH.")
        return capabilities, missing

    def _tesseract_available(self) -> bool:
        import shutil

        if self.settings.tesseract_cmd and Path(self.settings.tesseract_cmd).is_file():
            return True
        if shutil.which("tesseract") is not None:
            return True
        return any(
            candidate.is_file()
            for candidate in (
                Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
                Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
            )
        )

    def _validate_source(self, source: str) -> None:
        parsed = urlsplit(source)
        if parsed.scheme.lower() in {"rtsp", "rtsps"} and parsed.hostname:
            return
        if self.settings.allow_file_sources and not parsed.netloc and Path(source).is_file():
            return
        raise ValueError(
            "source must be an rtsp:// or rtsps:// URL; local video files require IBVAP_ALLOW_FILE_SOURCES=true"
        )

    def _is_file_source(self, source: str) -> bool:
        parsed = urlsplit(source)
        return self.settings.allow_file_sources and not parsed.netloc and Path(source).is_file()

    def create(self, config: CameraCreate) -> CameraStatus:
        self._validate_source(config.source)
        runtime = CameraRuntime(config)
        if config.start:
            self._validate_capabilities(runtime)
        with self._lock:
            if config.camera_id in self._cameras:
                raise CameraConflict("camera_id already exists")
            self._cameras[config.camera_id] = runtime
        if config.start:
            self.start(config.camera_id)
        return runtime.status()

    def list_cameras(self) -> list[CameraStatus]:
        with self._lock:
            cameras = list(self._cameras.values())
        return [camera.status() for camera in cameras]

    def metric_snapshots(self) -> list[CameraMetrics]:
        with self._lock:
            cameras = list(self._cameras.values())
        return [camera.metric_snapshot() for camera in cameras]

    def get(self, camera_id: str) -> CameraRuntime:
        with self._lock:
            camera = self._cameras.get(camera_id)
        if camera is None:
            raise CameraNotFound("camera not found")
        return camera

    def update(self, camera_id: str, patch: CameraUpdate) -> CameraStatus:
        camera = self.get(camera_id)
        with camera.lock:
            if camera.state in {CameraState.connecting, CameraState.running}:
                raise CameraConflict("stop the camera before updating its analytics configuration")
            data = patch.model_dump(exclude_unset=True)
            if "analytics" in data and data["analytics"] is not None:
                camera.analytics = set(data["analytics"])
            if "zones" in data and data["zones"] is not None:
                camera.zones = patch.zones or []
            if "process_fps" in data and data["process_fps"] is not None:
                camera.process_fps = data["process_fps"]
        return camera.status()

    def start(self, camera_id: str) -> CameraStatus:
        camera = self.get(camera_id)
        with camera.lock:
            if camera.state in {CameraState.connecting, CameraState.running}:
                return camera.status()
        self._validate_capabilities(camera)
        with camera.lock:
            if camera.state in {CameraState.connecting, CameraState.running}:
                return camera.status()
            camera.stop_event.clear()
            camera.last_error = None
            camera.state = CameraState.connecting
            camera.thread = threading.Thread(
                target=self._run_camera,
                args=(camera,),
                name=f"camera-{camera.camera_id}",
                daemon=True,
            )
            camera.thread.start()
        return camera.status()

    def _validate_capabilities(self, camera: CameraRuntime) -> None:
        self._validate_analytics_capabilities(camera.analytics)

    def _validate_analytics_capabilities(self, analytics: set[str]) -> None:
        if analytics & TRACKED_ANALYTICS and (
            not self.settings.person_vehicle_model or not Path(self.settings.person_vehicle_model).is_file()
        ):
            raise CapabilityUnavailable("person/vehicle analytics require a valid IBVAP_PERSON_VEHICLE_MODEL file")
        if analytics & TRACKED_ANALYTICS:
            try:
                self._get_yolo_detector("person_vehicle")
            except Exception as exc:
                logger.error("Person/vehicle model initialization failed: %s", type(exc).__name__)
                raise CapabilityUnavailable(
                    f"person/vehicle model could not load ({type(exc).__name__})"
                ) from exc
        if "anpr" in analytics:
            if not self.settings.plate_model or not Path(self.settings.plate_model).is_file():
                raise CapabilityUnavailable("ANPR requires a valid IBVAP_PLATE_MODEL file")
            try:
                self._get_yolo_detector("plate")
            except Exception as exc:
                logger.error("Plate model initialization failed: %s", type(exc).__name__)
                raise CapabilityUnavailable(f"plate model could not load ({type(exc).__name__})") from exc
            if not self._tesseract_available():
                raise CapabilityUnavailable("ANPR requires the Tesseract OCR executable")
        if "face" in analytics:
            try:
                HaarFaceDetector(self.settings.face_cascade_path)
            except (OSError, RuntimeError) as exc:
                raise CapabilityUnavailable("face detector could not be initialized") from exc

    def analyze_image(self, image_bytes: bytes, analytics: set[str]) -> ImageAnalysisResult:
        if not image_bytes:
            raise ValueError("uploaded image is empty")
        try:
            frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        except cv2.error as exc:
            raise ValueError("uploaded file is not a supported image") from exc
        if frame is None:
            raise ValueError("uploaded file is not a supported image")
        height, width = frame.shape[:2]
        if width * height > 25_000_000:
            raise ValueError("image dimensions exceed the 25-megapixel limit")
        if not analytics:
            raise ValueError("select at least one image analytics capability")

        self._validate_analytics_capabilities(analytics)
        detections: list[ImageDetection] = []
        if "person_vehicle" in analytics:
            for detection in self._get_yolo_detector("person_vehicle").detect(frame):
                detections.append(_image_detection(detection, width, height))
        if "face" in analytics:
            face_detector = HaarFaceDetector(self.settings.face_cascade_path)
            for detection in face_detector.detect(frame):
                detections.append(_image_detection(detection, width, height))
        if "anpr" in analytics:
            plate_detector = self._get_yolo_detector("plate")
            plate_reader = PlateReader(self.settings.tesseract_cmd)
            for detection in plate_detector.detect(frame):
                recognized = plate_reader.read(
                    frame,
                    detection,
                    minimum_confidence=self.settings.anpr_min_ocr_confidence,
                    plate_pattern=self.settings.plate_pattern,
                )
                plate_text, ocr_confidence = recognized if recognized is not None else (None, None)
                detections.append(
                    _image_detection(detection, width, height, plate_text, ocr_confidence)
                )
        activity_predictions: list[ActivityPrediction] = []
        people = [detection for detection in detections if detection.class_name == "person"]
        vehicles = [detection for detection in detections if detection.class_name in VEHICLE_CLASS_IDS.values()]
        if people:
            activity_predictions.append(ActivityPrediction(activity="person_present", confidence=max((item.confidence or 0) for item in people), evidence=f"{len(people)} person detection(s)"))
        if vehicles:
            activity_predictions.append(ActivityPrediction(activity="vehicle_present", confidence=max((item.confidence or 0) for item in vehicles), evidence=f"{len(vehicles)} vehicle detection(s)"))
        if len(people) >= 3:
            activity_predictions.append(ActivityPrediction(activity="crowding", confidence=None, evidence=f"{len(people)} people detected in one image"))
        return ImageAnalysisResult(
            analyzed_at=datetime.now(timezone.utc),
            image_width=width,
            image_height=height,
            analytics=sorted(analytics),
            detections=detections,
            activity_predictions=activity_predictions,
        )

    def analyze_video(
        self,
        video_bytes: bytes,
        filename: str,
        analytics: set[str],
        zones: list[Any] | None = None,
    ) -> VideoAnalysisResult:
        if not video_bytes:
            raise ValueError("uploaded video is empty")
        if not analytics:
            raise ValueError("select at least one video analytics capability")
        self._validate_analytics_capabilities(analytics)
        from app.schemas import Point, ZoneConfig

        camera_zones: list[ZoneConfig] = list(zones) if zones else []
        if not camera_zones and (analytics & {"intrusion", "loitering"}):
            camera_zones = [
                ZoneConfig(
                    zone_id="perimeter-zone",
                    polygon=[
                        Point(x=0.05, y=0.15),
                        Point(x=0.95, y=0.15),
                        Point(x=0.95, y=0.95),
                        Point(x=0.05, y=0.95),
                    ],
                    restricted=True,
                    loiter_seconds=min(5.0, self.settings.loiter_seconds),
                )
            ]
        camera = CameraRuntime(
            CameraCreate(
                camera_id=f"upload-{uuid4().hex[:12]}",
                source="uploaded-video",
                analytics=analytics,
                zones=camera_zones,
                process_fps=self.settings.process_fps,
            )
        )
        try:
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".mp4", delete=False) as handle:
                handle.write(video_bytes)
                video_path = handle.name
            capture = cv2.VideoCapture(video_path)
            if not capture.isOpened():
                raise ValueError("uploaded video could not be opened")
            person_detector = self._get_yolo_detector("person_vehicle") if analytics & TRACKED_ANALYTICS else None
            face_detector = HaarFaceDetector(self.settings.face_cascade_path) if "face" in analytics else None
            plate_detector = self._get_yolo_detector("plate") if "anpr" in analytics else None
            plate_reader = PlateReader(self.settings.tesseract_cmd) if "anpr" in analytics else None
            tracker = ByteTrackAdapter(frame_rate=max(1, round(self.settings.process_fps)))
            rule_state = RuleState()
            frames_analyzed = 0
            frame_step = max(1, round((capture.get(cv2.CAP_PROP_FPS) or self.settings.process_fps) / self.settings.process_fps))
            frame_number = 0
            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                frame_number += 1
                if frame_number % frame_step:
                    continue
                self._process_frame(camera, frame, tracker, rule_state, person_detector, face_detector, plate_detector, plate_reader)
                frames_analyzed += 1
            capture.release()
            events = _aggregate_plate_events(self.events.query(camera_id=camera.camera_id, limit=1000))
            return VideoAnalysisResult(
                analyzed_at=datetime.now(timezone.utc),
                filename=filename,
                frames_analyzed=frames_analyzed,
                events=events,
                activity_predictions=_video_activity_predictions(events),
            )
        finally:
            if "video_path" in locals():
                Path(video_path).unlink(missing_ok=True)

    def _get_yolo_detector(self, capability: str) -> YoloOnnxDetector:
        with self._model_lock:
            if capability not in self._detectors:
                if capability == "person_vehicle":
                    model_path = self.settings.person_vehicle_model or ""
                    labels, allowed_ids = COCO_LABELS, PERSON_VEHICLE_IDS
                    confidence_threshold = self.settings.confidence_threshold
                elif capability == "plate":
                    model_path = self.settings.plate_model or ""
                    labels, allowed_ids = {0: "license_plate"}, {0}
                    confidence_threshold = self.settings.confidence_threshold
                else:
                    raise ValueError(f"unknown detector capability: {capability}")
                self._detectors[capability] = YoloOnnxDetector(
                    model_path,
                    labels,
                    allowed_ids,
                    self.settings.inference_size,
                    confidence_threshold,
                    self.settings.nms_threshold,
                    self.settings.inference_provider,
                )
            return self._detectors[capability]

    def stop(self, camera_id: str) -> CameraStatus:
        camera = self.get(camera_id)
        with camera.lock:
            if camera.thread is not None and camera.thread.is_alive():
                camera.stop_event.set()
                thread = camera.thread
            else:
                camera.state = CameraState.stopped
                camera.thread = None
                return camera.status()
        thread.join(timeout=10)
        if thread.is_alive():
            raise CameraConflict("camera worker did not stop within 10 seconds")
        with camera.lock:
            camera.state = CameraState.stopped
            camera.thread = None
        return camera.status()

    def stop_all(self) -> None:
        with self._lock:
            camera_ids = list(self._cameras)
        for camera_id in camera_ids:
            try:
                self.stop(camera_id)
            except CameraConflict:
                logger.error("Camera worker did not stop during shutdown: %s", camera_id)

    def _run_camera(self, camera: CameraRuntime) -> None:
        capture: cv2.VideoCapture | None = None
        try:
            person_detector = None
            face_detector = None
            plate_detector = None
            plate_reader = None
            if camera.analytics & TRACKED_ANALYTICS:
                person_detector = self._get_yolo_detector("person_vehicle")
            if "face" in camera.analytics:
                face_detector = HaarFaceDetector(self.settings.face_cascade_path)
            if "anpr" in camera.analytics:
                plate_detector = self._get_yolo_detector("plate")
                plate_reader = PlateReader(self.settings.tesseract_cmd)
            tracker = ByteTrackAdapter(frame_rate=max(1, round(camera.process_fps)))
            rule_state = RuleState()
            camera_source: str | int = camera.source
            while not camera.stop_event.is_set():
                capture = cv2.VideoCapture(
                    camera_source,
                    cv2.CAP_FFMPEG,
                    [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                        5000,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                        5000,
                    ],
                )
                if not capture.isOpened():
                    capture.release()
                    capture = None
                    with camera.lock:
                        camera.state = CameraState.error
                        camera.last_error = "stream_unavailable"
                    camera.stop_event.wait(2)
                    if not camera.stop_event.is_set():
                        with camera.lock:
                            camera.state = CameraState.connecting
                    continue
                with camera.lock:
                    camera.state = CameraState.running
                    camera.last_error = None
                last_processed = 0.0
                stream_failed = False
                while not camera.stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        stream_failed = True
                        break
                    now_monotonic = time.monotonic()
                    if now_monotonic - last_processed < 1 / camera.process_fps:
                        with camera.lock:
                            camera.dropped_frames += 1
                        continue
                    last_processed = now_monotonic
                    with camera.lock:
                        camera.last_frame_at = datetime.now(timezone.utc)
                    inference_started = time.perf_counter()
                    self._process_frame(
                        camera,
                        frame,
                        tracker,
                        rule_state,
                        person_detector,
                        face_detector,
                        plate_detector,
                        plate_reader,
                    )
                    inference_ms = (time.perf_counter() - inference_started) * 1000
                    with camera.lock:
                        camera.processed_frames += 1
                        camera.inference_count += 1
                        camera.total_inference_ms += inference_ms
                capture.release()
                capture = None
                if stream_failed and not camera.stop_event.is_set():
                    if self._is_file_source(camera.source) and camera.processed_frames > 0:
                        camera.stop_event.wait(0.5)
                        continue
                    if self._is_file_source(camera.source):
                        with camera.lock:
                            camera.state = CameraState.stopped
                            camera.last_error = None
                        break
                    with camera.lock:
                        camera.state = CameraState.error
                        camera.last_error = "stream_disconnected"
                    camera.stop_event.wait(2)
                    if not camera.stop_event.is_set():
                        with camera.lock:
                            camera.state = CameraState.connecting
        except Exception as exc:
            logger.error(
                "Camera analytics worker failed for camera_id=%s error_type=%s",
                camera.camera_id,
                type(exc).__name__,
            )
            with camera.lock:
                camera.state = CameraState.error
                camera.last_error = f"analytics_error:{type(exc).__name__}"
        finally:
            if capture is not None:
                capture.release()
            with camera.lock:
                if camera.stop_event.is_set():
                    camera.state = CameraState.stopped

    def _process_frame(
        self,
        camera: CameraRuntime,
        frame: Any,
        tracker: ByteTrackAdapter,
        rule_state: RuleState,
        person_detector: YoloOnnxDetector | None,
        face_detector: HaarFaceDetector | None,
        plate_detector: YoloOnnxDetector | None,
        plate_reader: PlateReader | None,
    ) -> None:
        height, width = frame.shape[:2]
        now = datetime.now(timezone.utc)
        detections = person_detector.detect(frame) if person_detector else []
        tracked = tracker.update(detections) if person_detector else []
        person_count = sum(item.detection.class_name == "person" for item in tracked)
        if person_count >= 3 and rule_state.should_emit(
            "crowding", "camera", "crowding", now, self.settings.event_cooldown_seconds
        ):
            self._emit_activity(camera, "crowding", now, width, height, {"person_count": person_count})
        for item in tracked:
            self._process_tracked_detection(camera, frame, item.detection, str(item.track_id), width, height, now, rule_state)
        if face_detector:
            for face in face_detector.detect(frame):
                if rule_state.should_emit("face_detected", "camera", "face", now, self.settings.event_cooldown_seconds):
                    self._emit(
                        camera,
                        "face_detected",
                        now,
                        face,
                        width,
                        height,
                        frame=frame,
                        details={"method": "haar_cascade"},
                    )
        if plate_detector and plate_reader:
            for plate in plate_detector.detect(frame):
                recognized = plate_reader.read(
                    frame,
                    plate,
                    minimum_confidence=self.settings.anpr_min_ocr_confidence,
                    plate_pattern=self.settings.plate_pattern,
                )
                if recognized is None:
                    continue
                text, confidence = recognized
                if rule_state.should_emit("plate_read", text, "plate", now, self.settings.event_cooldown_seconds):
                    self._emit(
                        camera,
                        "plate_read",
                        now,
                        plate,
                        width,
                        height,
                        frame=frame,
                        details={"plate_text": text, "ocr_confidence": confidence},
                    )

    def _process_tracked_detection(
        self,
        camera: CameraRuntime,
        frame: np.ndarray,
        detection: Detection,
        track_id: str,
        width: int,
        height: int,
        now: datetime,
        state: RuleState,
    ) -> None:
        if detection.confidence is not None and detection.confidence < self.settings.confidence_threshold:
            return
        if "person_vehicle" in camera.analytics and state.should_emit(
            "object_detected", track_id, "object", now, self.settings.event_cooldown_seconds
        ):
            self._emit(camera, "object_detected", now, detection, width, height, track_id=track_id, frame=frame)
        for zone in camera.zones:
            inside = detection_center_in_zone(detection, width, height, zone)
            key = (track_id, zone.zone_id)
            if zone.restricted and "intrusion" in camera.analytics:
                if inside and key not in state.zone_entry:
                    state.zone_entry.add(key)
                    self._emit(camera, "virtual_fence_intrusion", now, detection, width, height, track_id, zone.zone_id, frame)
                elif not inside:
                    state.zone_entry.discard(key)
            if "loitering" in camera.analytics:
                loiter_seconds = zone.loiter_seconds or self.settings.loiter_seconds
                if inside:
                    since = state.loiter_since.setdefault(key, now)
                    if (now - since).total_seconds() >= loiter_seconds and state.should_emit(
                        "loitering", track_id, zone.zone_id, now, self.settings.event_cooldown_seconds
                    ):
                        self._emit(camera, "loitering", now, detection, width, height, track_id, zone.zone_id, frame)
                else:
                    state.loiter_since.pop(key, None)
        if "night_movement" in camera.analytics and self._is_night(now):
            if state.should_emit("night_movement", track_id, "night", now, self.settings.event_cooldown_seconds):
                self._emit(camera, "night_movement", now, detection, width, height, track_id=track_id, frame=frame)
        if detection.class_name in VEHICLE_CLASS_IDS.values():
            center = ((detection.xyxy[0] + detection.xyxy[2]) / 2, (detection.xyxy[1] + detection.xyxy[3]) / 2)
            previous = state.last_centers.get(track_id)
            state.last_centers[track_id] = center
            if previous is not None and abs(center[0] - previous[0]) + abs(center[1] - previous[1]) <= 5:
                since = state.stationary_since.setdefault(track_id, now)
                if (now - since).total_seconds() >= 10 and state.should_emit(
                    "stopped_vehicle", track_id, "vehicle", now, self.settings.event_cooldown_seconds
                ):
                    self._emit(camera, "stopped_vehicle", now, detection, width, height, track_id=track_id, frame=frame)
            else:
                state.stationary_since.pop(track_id, None)

    def _emit_activity(
        self,
        camera: CameraRuntime,
        activity: str,
        now: datetime,
        width: int,
        height: int,
        details: dict[str, int],
    ) -> None:
        self.events.publish(AnalyticsEvent(
            event_id=str(uuid4()),
            event_type=activity,
            occurred_at=now,
            camera_id=camera.camera_id,
            details=details,
        ))

    def _is_night(self, now: datetime) -> bool:
        hour = now.hour
        start, end = self.settings.night_start_hour, self.settings.night_end_hour
        return (start > end and (hour >= start or hour < end)) or (start <= end and start <= hour < end)

    def _emit(
        self,
        camera: CameraRuntime,
        event_type: str,
        now: datetime,
        detection: Detection,
        width: int,
        height: int,
        track_id: str | None = None,
        zone_id: str | None = None,
        frame: np.ndarray | None = None,
        details: dict[str, str | float | int | bool | None] | None = None,
    ) -> None:
        event_id = str(uuid4())
        evidence: dict[str, str | None] = {"snapshot_reference": None}
        event_details = dict(details or {})
        if frame is not None:
            snapshot_path = self._evidence_directory / f"{event_id}.jpg"
            try:
                annotated = frame.copy()
                x1, y1, x2, y2 = (int(value) for value in detection.xyxy)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (249, 0, 213), 2)
                label = detection.class_name
                plate_text = event_details.get("plate_text")
                if plate_text:
                    label = f"{label}: {plate_text}"
                cv2.putText(
                    annotated,
                    label,
                    (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (249, 0, 213),
                    2,
                )
                if cv2.imwrite(str(snapshot_path), annotated):
                    evidence["snapshot_reference"] = f"/api/v1/events/{event_id}/snapshot"
                else:
                    logger.error("Could not write evidence snapshot for event_id=%s", event_id)
                if event_type == "plate_read":
                    padding_x = max(2, round((x2 - x1) * 0.12))
                    padding_y = max(2, round((y2 - y1) * 0.35))
                    crop = frame[
                        max(0, y1 - padding_y) : min(height, y2 + padding_y),
                        max(0, x1 - padding_x) : min(width, x2 + padding_x),
                    ]
                    plate_snapshot_path = self._evidence_directory / f"{event_id}_plate.jpg"
                    if crop.size and cv2.imwrite(str(plate_snapshot_path), crop):
                        evidence["plate_snapshot_reference"] = (
                            f"/api/v1/events/{event_id}/plate-snapshot"
                        )
                        event_details["plate_snapshot_reference"] = evidence["plate_snapshot_reference"]
                    else:
                        logger.error("Could not write plate snapshot for event_id=%s", event_id)
            except (OSError, cv2.error) as exc:
                logger.error("Evidence snapshot failed for event_id=%s error_type=%s", event_id, type(exc).__name__)
        self.events.publish(
            AnalyticsEvent(
                event_id=event_id,
                event_type=event_type,
                occurred_at=now,
                camera_id=camera.camera_id,
                track_id=track_id,
                object=EventObject(
                    class_name=detection.class_name,
                    confidence=detection.confidence,
                    bounding_box=detection.normalized_box(width, height),
                ),
                zone_id=zone_id,
                details=event_details,
                evidence=evidence,
            )
        )


def _image_detection(
    detection: Detection,
    width: int,
    height: int,
    plate_text: str | None = None,
    ocr_confidence: float | None = None,
) -> ImageDetection:
    return ImageDetection(
        class_name=detection.class_name,
        confidence=detection.confidence,
        bounding_box=detection.normalized_box(width, height),
        plate_text=plate_text,
        ocr_confidence=ocr_confidence,
    )


def _video_activity_predictions(events: list[AnalyticsEvent]) -> list[ActivityPrediction]:
    predictions: list[ActivityPrediction] = []
    activity_evidence = {
        "virtual_fence_intrusion": "tracked object entered a restricted zone",
        "loitering": "tracked object remained in a zone for the configured duration",
        "night_movement": "tracked movement occurred during the configured night window",
        "crowding": "three or more people were detected together",
        "stopped_vehicle": "a tracked vehicle remained nearly stationary for at least 10 seconds",
    }
    for activity, evidence in activity_evidence.items():
        matches = [event for event in events if event.event_type == activity]
        if matches:
            predictions.append(ActivityPrediction(activity=activity, confidence=None, evidence=f"{len(matches)} event(s); {evidence}"))
    return predictions


def _aggregate_plate_events(events: list[AnalyticsEvent]) -> list[AnalyticsEvent]:
    """Keep the strongest OCR observation for each plate read across video frames."""
    best_by_plate: dict[str, AnalyticsEvent] = {}
    non_plate_events: list[AnalyticsEvent] = []
    for event in events:
        if event.event_type != "plate_read":
            non_plate_events.append(event)
            continue
        plate = str(event.details.get("plate_text") or "").upper()
        if not plate:
            non_plate_events.append(event)
            continue
        current = best_by_plate.get(plate)
        current_confidence = current.details.get("ocr_confidence") if current else -1
        confidence = event.details.get("ocr_confidence")
        if current is None or (
            isinstance(confidence, (int, float))
            and (not isinstance(current_confidence, (int, float)) or confidence > current_confidence)
        ):
            best_by_plate[plate] = event
    return non_plate_events + list(best_by_plate.values())

import cv2
import numpy as np
import pytest

from app.cameras import CameraManager
from app.config import Settings
from app.events import EventStore
from app.vision import Detection, YoloOnnxDetector
from app.vision import PlateReader


class FakeSession:
    def __init__(self, output: np.ndarray) -> None:
        self.output = output

    def run(self, output_names, inputs):
        return [self.output]


def test_yolo_parser_keeps_overlapping_different_classes_and_unpads_boxes() -> None:
    output = np.zeros((1, 6, 8), dtype=np.float32)
    output[0, 0, :2] = 320
    output[0, 1, :2] = 320
    output[0, 2, :2] = 100
    output[0, 3, :2] = 100
    output[0, 4, 0] = 0.9
    output[0, 5, 1] = 0.9

    detector = object.__new__(YoloOnnxDetector)
    detector.session = FakeSession(output)
    detector.input_name = "images"
    detector.labels = {0: "person", 1: "vehicle"}
    detector.allowed_class_ids = {0, 1}
    detector.input_size = 640
    detector.confidence_threshold = 0.35
    detector.nms_threshold = 0.45

    detections = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    by_class = {detection.class_name: detection for detection in detections}
    assert set(by_class) == {"person", "vehicle"}
    assert by_class["person"].xyxy == (270.0, 190.0, 370.0, 290.0)
    assert by_class["vehicle"].xyxy == (270.0, 190.0, 370.0, 290.0)


def test_camera_manager_uses_configured_detector_threshold(tmp_path, monkeypatch) -> None:
    model_path = tmp_path / "person-vehicle.onnx"
    model_path.write_bytes(b"not-a-real-model")
    settings = Settings(
        database_path=str(tmp_path / "events.sqlite3"),
        event_retention_days=30,
        person_vehicle_model=str(model_path),
        plate_model=None,
        face_cascade_path=None,
        inference_provider="CPUExecutionProvider",
        inference_size=640,
        confidence_threshold=0.72,
        nms_threshold=0.45,
        anpr_min_ocr_confidence=0.5,
        process_fps=5,
        loiter_seconds=30,
        event_cooldown_seconds=30,
        night_start_hour=20,
        night_end_hour=6,
        allow_file_sources=False,
        tesseract_cmd=None,
        api_token="test-token-for-unit-tests-not-production-1234",
    )
    manager = CameraManager(settings, EventStore(str(tmp_path / "events.sqlite3")))
    captured: dict[str, float] = {}

    class FakeYoloDetector:
        def __init__(self, *args, **kwargs):
            captured["threshold"] = args[4]

    monkeypatch.setattr("app.cameras.YoloOnnxDetector", FakeYoloDetector)

    manager._get_yolo_detector("person_vehicle")

    assert captured["threshold"] == 0.72


def test_camera_manager_analyzes_uploaded_image_without_camera_stream(tmp_path, monkeypatch) -> None:
    model_path = tmp_path / "person-vehicle.onnx"
    model_path.write_bytes(b"test-model")
    settings = Settings(
        database_path=str(tmp_path / "events.sqlite3"),
        event_retention_days=30,
        person_vehicle_model=str(model_path),
        plate_model=None,
        face_cascade_path=None,
        inference_provider="CPUExecutionProvider",
        inference_size=640,
        confidence_threshold=0.35,
        nms_threshold=0.45,
        anpr_min_ocr_confidence=0.5,
        process_fps=5,
        loiter_seconds=30,
        event_cooldown_seconds=30,
        night_start_hour=20,
        night_end_hour=6,
        allow_file_sources=False,
        tesseract_cmd=None,
        api_token="test-token-for-unit-tests-not-production-1234",
    )
    manager = CameraManager(settings, EventStore(str(tmp_path / "events.sqlite3")))
    detection = Detection("person", 0, 0.9, (10, 20, 60, 70))

    class FakeDetector:
        def detect(self, frame):
            assert frame.shape == (100, 200, 3)
            return [detection]

    monkeypatch.setattr(manager, "_get_yolo_detector", lambda capability: FakeDetector())
    with pytest.raises(ValueError, match="not a supported image"):
        manager.analyze_image(b"not-an-image", {"person_vehicle"})

    success, encoded_image = cv2.imencode(".jpg", np.zeros((100, 200, 3), dtype=np.uint8))
    assert success

    result = manager.analyze_image(encoded_image.tobytes(), {"person_vehicle"})

    assert (result.image_width, result.image_height) == (200, 100)
    assert result.analytics == ["person_vehicle"]
    assert len(result.detections) == 1
    assert result.detections[0].class_name == "person"
    assert result.detections[0].bounding_box.model_dump() == {
        "x": 0.05,
        "y": 0.2,
        "width": 0.25,
        "height": 0.5,
    }


def test_plate_reader_uses_standard_windows_tesseract_path(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakePytesseract:
        class pytesseract:
            tesseract_cmd = ""

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: str(self).endswith("Tesseract-OCR\\tesseract.exe"))
    monkeypatch.setattr("pytesseract.pytesseract.tesseract_cmd", "", raising=False)

    reader = PlateReader()

    captured["path"] = reader.pytesseract.pytesseract.tesseract_cmd
    assert captured["path"].endswith("Tesseract-OCR\\tesseract.exe")


def test_plate_reader_ignores_low_confidence_ocr_tokens(monkeypatch) -> None:
    reader = object.__new__(PlateReader)

    class FakePytesseract:
        class Output:
            DICT = "dict"

        @staticmethod
        def image_to_data(image, config, output_type):
            return {"text": ["ABC", "1235"], "conf": ["85", "0"]}

    reader.pytesseract = FakePytesseract

    result = reader.read(
        np.zeros((40, 120, 3), dtype=np.uint8),
        Detection("license_plate", 0, 0.9, (0, 0, 120, 40)),
    )

    assert result == ("ABC", 0.85)

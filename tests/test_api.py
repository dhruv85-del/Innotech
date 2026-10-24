from fastapi.testclient import TestClient

from app.cameras import CameraManager
from app.config import Settings
from app.main import create_app


def test_api_protects_camera_routes_and_does_not_return_source(tmp_path, monkeypatch) -> None:
    settings = Settings(
        database_path=str(tmp_path / "events.sqlite3"),
        event_retention_days=30,
        person_vehicle_model=None,
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
        allow_file_sources=True,
        tesseract_cmd=None,
        api_token="test-token-for-unit-tests-not-production-1234",
    )
    app = create_app(settings)
    video = tmp_path / "placeholder.mp4"
    video.touch()

    def analyze_image(self, image_bytes, analytics):
        assert isinstance(self, CameraManager)
        assert image_bytes == b"demo-image"
        return {
            "analyzed_at": "2026-01-01T00:00:00Z",
            "image_width": 200,
            "image_height": 100,
            "analytics": sorted(analytics),
            "detections": [],
        }

    monkeypatch.setattr("app.cameras.CameraManager.analyze_image", analyze_image)

    with TestClient(app) as client:
        demo_page = client.get("/")
        assert demo_page.status_code == 200
        assert "Image Analytics Demo" in demo_page.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/ready").json()["capabilities"]["face"] is True
        assert client.get("/health").status_code == 200
        assert client.post(
            "/api/v1/images/analyze",
            files={"image": ("sample.jpg", b"demo-image", "image/jpeg")},
            data={"analytics": "person_vehicle"},
        ).status_code == 401
        assert client.get(
            "/api/v1/metrics/cameras",
            headers={"X-API-Key": "test-token-for-unit-tests-not-production-1234"},
        ).json() == []
        readiness = client.get("/ready")
        assert readiness.status_code == 200
        assert readiness.json()["status"] == "degraded"
        assert client.get("/api/v1/cameras").status_code == 401
        invalid = client.post(
            "/api/v1/cameras",
            headers={"X-API-Key": "test-token-for-unit-tests-not-production-1234"},
            json={
                "camera_id": "invalid id",
                "source": "rtsp://operator:top-secret@camera.example/live",
                "analytics": [],
            },
        )
        response = client.post(
            "/api/v1/cameras",
            headers={"X-API-Key": "test-token-for-unit-tests-not-production-1234"},
            json={
                "camera_id": "test-camera",
                "source": str(video),
                "analytics": [],
            },
        )
        update = client.patch(
            "/api/v1/cameras/test-camera",
            headers={"X-API-Key": "test-token-for-unit-tests-not-production-1234"},
            json={"analytics": ["person_vehicle"]},
        )
        start = client.post(
            "/api/v1/cameras/test-camera/start",
            headers={"X-API-Key": "test-token-for-unit-tests-not-production-1234"},
        )
        image_analysis = client.post(
            "/api/v1/images/analyze",
            headers={"X-API-Key": "test-token-for-unit-tests-not-production-1234"},
            files={"image": ("sample.jpg", b"demo-image", "image/jpeg")},
            data={"analytics": "person_vehicle"},
        )

    assert invalid.status_code == 422
    assert "top-secret" not in invalid.text
    assert response.status_code == 201
    assert str(video) not in response.text
    assert update.status_code == 200
    assert start.status_code == 503
    assert start.json()["detail"] == "person/vehicle analytics require a valid IBVAP_PERSON_VEHICLE_MODEL file"
    assert image_analysis.status_code == 200
    assert image_analysis.json()["analytics"] == ["person_vehicle"]
    assert image_analysis.json()["detections"] == []


def test_service_api_requires_configured_token(tmp_path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "events.sqlite3"),
        event_retention_days=30,
        person_vehicle_model=None,
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
        api_token=None,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/cameras")

    assert response.status_code == 503


def test_ui_route_serves_frontend(tmp_path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "events.sqlite3"),
        event_retention_days=30,
        person_vehicle_model=None,
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
        allow_file_sources=True,
        tesseract_cmd=None,
        api_token="test-token-for-unit-tests-not-production-1234",
    )
    with TestClient(create_app(settings)) as client:
        res = client.get("/ui")
        assert res.status_code == 200
        assert "IBVAP" in res.text

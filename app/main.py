from contextlib import asynccontextmanager
from collections.abc import Callable
from datetime import datetime
import base64
import hmac
from html import escape
from pathlib import Path
from typing import Annotated, TypeVar
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.cameras import (
    CameraConflict,
    CameraManager,
    CameraMetrics,
    CameraNotFound,
    CapabilityUnavailable,
)
from app.config import Settings
from app.events import EventStore
from app.schemas import (
    AnalyticsEvent,
    CameraCreate,
    CameraStatus,
    CameraUpdate,
    ImageAnalytics,
    ImageAnalysisResult,
    ImageDetection,
    VideoAnalytics,
    VideoAnalysisResult,
    EventObject,
    AlertAction,
    Readiness,
)

T = TypeVar("T")
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 250 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    service_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.event_store = EventStore(
            service_settings.database_path,
            service_settings.event_retention_days,
        )
        application.state.camera_manager = CameraManager(service_settings, application.state.event_store)
        yield
        application.state.camera_manager.stop_all()

    application = FastAPI(
        title="IBVAP AI Video Analytics Service",
        version="0.1.0",
        description="Local image and video analytics for sample images, IP cameras, and test video sources.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.state.service_api_token = service_settings.api_token
    static_directory = Path(__file__).with_name("static")
    application.mount("/static", StaticFiles(directory=static_directory), name="static")

    @application.get("/", include_in_schema=False)
    def demo_home() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_token)])

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready", response_model=Readiness)
    def readiness(request: Request) -> Readiness:
        manager: CameraManager = request.app.state.camera_manager
        capabilities, missing = manager.capabilities()
        return Readiness(
            status="ready" if capabilities["person_vehicle"] else "degraded",
            capabilities=capabilities,
            missing_requirements=missing,
        )

    @router.post("/cameras", response_model=CameraStatus, status_code=status.HTTP_201_CREATED)
    def create_camera(config: CameraCreate, request: Request) -> CameraStatus:
        return _call_manager(lambda: request.app.state.camera_manager.create(config))

    @router.get("/cameras", response_model=list[CameraStatus])
    def list_cameras(request: Request) -> list[CameraStatus]:
        return request.app.state.camera_manager.list_cameras()

    @router.get("/metrics/cameras", response_model=list[CameraMetrics])
    def camera_metrics(request: Request) -> list[CameraMetrics]:
        return request.app.state.camera_manager.metric_snapshots()

    @router.get("/cameras/{camera_id}", response_model=CameraStatus)
    def get_camera(camera_id: str, request: Request) -> CameraStatus:
        try:
            return request.app.state.camera_manager.get(camera_id).status()
        except CameraNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.patch("/cameras/{camera_id}", response_model=CameraStatus)
    def update_camera(camera_id: str, patch: CameraUpdate, request: Request) -> CameraStatus:
        return _call_manager(lambda: request.app.state.camera_manager.update(camera_id, patch))

    @router.post("/cameras/{camera_id}/start", response_model=CameraStatus)
    def start_camera(camera_id: str, request: Request) -> CameraStatus:
        return _call_manager(lambda: request.app.state.camera_manager.start(camera_id))

    @router.post("/cameras/{camera_id}/stop", response_model=CameraStatus)
    def stop_camera(camera_id: str, request: Request) -> CameraStatus:
        return _call_manager(lambda: request.app.state.camera_manager.stop(camera_id))

    @router.get("/events", response_model=list[AnalyticsEvent])
    def get_events(
        request: Request,
        camera_id: str | None = None,
        event_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[AnalyticsEvent]:
        since_dt = _parse_datetime(since, "since")
        until_dt = _parse_datetime(until, "until")
        if since_dt and until_dt and since_dt > until_dt:
            raise HTTPException(status_code=422, detail="since must be earlier than or equal to until")
        return request.app.state.event_store.query(camera_id, event_type, since_dt, until_dt, limit)

    @router.get("/alert-actions", response_model=list[AlertAction])
    def get_alert_actions(request: Request) -> list[AlertAction]:
        return request.app.state.event_store.list_alert_actions()

    @router.post("/events/{event_id}/action", response_model=AlertAction)
    def record_alert_action(event_id: str, action: AlertAction, request: Request) -> AlertAction:
        if action.event_id != event_id:
            raise HTTPException(status_code=422, detail="event_id does not match the URL")
        try:
            return request.app.state.event_store.record_alert_action(event_id, action.status)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="event not found") from exc

    @router.get("/events/{event_id}/snapshot")
    def get_event_snapshot(event_id: str, request: Request) -> FileResponse:
        event = request.app.state.event_store.get(event_id)
        if event is None or not event.evidence.get("snapshot_reference"):
            raise HTTPException(status_code=404, detail="snapshot not found")
        snapshot_path = Path(request.app.state.camera_manager.settings.database_path).parent / "evidence" / f"{event_id}.jpg"
        if not snapshot_path.is_file():
            raise HTTPException(status_code=404, detail="snapshot not found")
        return FileResponse(snapshot_path, media_type="image/jpeg", filename=f"{event_id}.jpg")

    @router.get("/events/{event_id}/plate-snapshot")
    def get_plate_snapshot(event_id: str, request: Request) -> FileResponse:
        event = request.app.state.event_store.get(event_id)
        if event is None or event.event_type != "plate_read":
            raise HTTPException(status_code=404, detail="plate snapshot not found")
        snapshot_path = (
            Path(request.app.state.camera_manager.settings.database_path).parent
            / "evidence"
            / f"{event_id}_plate.jpg"
        )
        if not snapshot_path.is_file():
            raise HTTPException(status_code=404, detail="plate snapshot not found")
        return FileResponse(snapshot_path, media_type="image/jpeg", filename=f"{event_id}_plate.jpg")

    @router.get("/image-reports/{report_id}/download")
    def download_image_report(report_id: str, request: Request) -> FileResponse:
        report_path = Path(request.app.state.camera_manager.settings.database_path).parent / "reports" / f"{report_id}.html"
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="image report not found")
        return FileResponse(report_path, media_type="text/html", filename=f"ibvap-image-report-{report_id}.html")

    @router.get("/video-reports/{report_id}/download")
    def download_video_report(report_id: str, request: Request) -> FileResponse:
        report_path = Path(request.app.state.camera_manager.settings.database_path).parent / "reports" / f"{report_id}.html"
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="video report not found")
        return FileResponse(report_path, media_type="text/html", filename=f"ibvap-video-report-{report_id}.html")

    @router.post("/images/analyze", response_model=ImageAnalysisResult)
    def analyze_image(
        request: Request,
        image: UploadFile = File(...),
        analytics: Annotated[list[ImageAnalytics], Form()] = ["person_vehicle"],
    ) -> ImageAnalysisResult:
        image_bytes = image.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        if len(image_bytes) > MAX_IMAGE_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="image upload exceeds the 10 MiB limit")
        return _call_manager(
            lambda: _analyze_image_and_publish(
                request.app.state.camera_manager,
                image_bytes,
                set(analytics),
                image.filename or "uploaded-image",
            )
        )

    @router.post("/videos/analyze", response_model=VideoAnalysisResult)
    def analyze_video(
        request: Request,
        video: UploadFile = File(...),
        analytics: Annotated[list[VideoAnalytics], Form()] = ["person_vehicle"],
        zones: Annotated[str | None, Form()] = None,
    ) -> VideoAnalysisResult:
        video_bytes = video.file.read(MAX_VIDEO_UPLOAD_BYTES + 1)
        if len(video_bytes) > MAX_VIDEO_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="video upload exceeds the 250 MiB limit")
        parsed_zones = None
        if zones:
            try:
                import json
                from app.schemas import ZoneConfig

                raw_zones = json.loads(zones)
                parsed_zones = [ZoneConfig.model_validate(z) for z in raw_zones]
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"invalid zones format: {exc}") from exc
        return _call_manager(
            lambda: _analyze_video_and_create_report(
                request.app.state.camera_manager,
                video_bytes,
                video.filename or "uploaded-video",
                set(analytics),
                parsed_zones,
            )
        )

    application.include_router(router)

    frontend_dist = Path(__file__).resolve().parent.parent / "Frontend_IBVAP" / "dist"
    if (frontend_dist / "index.html").is_file():
        application.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @application.get("/ui", include_in_schema=False)
        @application.get("/ui/{full_path:path}", include_in_schema=False)
        def ui_spa(full_path: str = "") -> FileResponse:
            candidate = frontend_dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return application


def require_api_token(
    request: Request,
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    expected = getattr(request.app.state, "service_api_token", None)
    if expected is None:
        raise HTTPException(status_code=503, detail="IBVAP_API_TOKEN is not configured")
    if api_key is None or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _parse_datetime(value: str | None, parameter: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{parameter} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{parameter} must include a timezone")
    return parsed


def _call_manager(function: Callable[[], T]) -> T:
    try:
        return function()
    except CameraNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CameraConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CapabilityUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _analyze_image_and_publish(
    manager: CameraManager,
    image_bytes: bytes,
    analytics: set[ImageAnalytics],
    filename: str,
) -> ImageAnalysisResult:
    result = ImageAnalysisResult.model_validate(manager.analyze_image(image_bytes, analytics))
    report_id = str(uuid4())
    report_directory = Path(manager.settings.database_path).parent / "reports"
    report_directory.mkdir(parents=True, exist_ok=True)
    frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        if result.detections:
            raise ValueError("uploaded file is not a supported image")
        frame = np.zeros((result.image_height, result.image_width, 3), dtype=np.uint8)
    annotated = frame.copy()
    colors = {"person": (255, 229, 0), "face": (0, 234, 255), "car": (0, 230, 118), "license_plate": (249, 0, 213)}
    for detection in result.detections:
        box = detection.bounding_box
        x1, y1 = int(box.x * result.image_width), int(box.y * result.image_height)
        x2, y2 = int((box.x + box.width) * result.image_width), int((box.y + box.height) * result.image_height)
        color = colors.get(detection.class_name, (0, 230, 118))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, max(2, result.image_width // 400))
        label = detection.class_name
        if detection.confidence is not None:
            label += f" {detection.confidence:.0%}"
        if detection.plate_text:
            label += f" [{detection.plate_text}"
            if detection.ocr_confidence is not None:
                label += f" OCR {detection.ocr_confidence:.0%}"
            label += "]"
        cv2.putText(annotated, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, max(0.5, result.image_width / 1600), color, 2)
    try:
        encoded_image = cv2.imencode(".jpg", annotated)[1].tobytes()
    except cv2.error as exc:
        raise ValueError("could not create annotated image report") from exc
    image_data = base64.b64encode(encoded_image).decode("ascii")

    def plate_crop_html(detection: ImageDetection) -> str:
        if not detection.plate_text:
            return "—"
        box = detection.bounding_box
        crop = frame[
            max(0, int(box.y * result.image_height) - 8) : min(
                result.image_height, int((box.y + box.height) * result.image_height) + 8
            ),
            max(0, int(box.x * result.image_width) - 8) : min(
                result.image_width, int((box.x + box.width) * result.image_width) + 8
            ),
        ]
        if crop.size == 0:
            return "Not available"
        ok, encoded_crop = cv2.imencode(".jpg", crop)
        if not ok:
            return "Not available"
        crop_data = base64.b64encode(encoded_crop.tobytes()).decode("ascii")
        return f'<img src="data:image/jpeg;base64,{crop_data}" alt="OCR plate crop" style="max-width:240px">'

    rows = "".join(
        f"<tr><td>{index}</td><td>{escape(detection.class_name)}</td>"
        f"<td>{'' if detection.confidence is None else f'{detection.confidence:.1%}'}</td>"
        f"<td>{escape(detection.plate_text or '—')}</td>"
        f"<td>{'' if detection.ocr_confidence is None else f'{detection.ocr_confidence:.1%}'}</td>"
        f"<td>{plate_crop_html(detection)}</td></tr>"
        for index, detection in enumerate(result.detections, 1)
    )
    predictions_html = "".join(
        f"<li><strong>{escape(prediction.activity)}</strong>: {escape(prediction.evidence)}"
        + (f" ({prediction.confidence:.1%} confidence)" if prediction.confidence is not None else "")
        + "</li>"
        for prediction in result.activity_predictions
    ) or "<li>No supported activity pattern found in this image.</li>"
    report_html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>IBVAP Image Analysis Report</title>
<style>body{{font-family:Arial,sans-serif;color:#172033;max-width:1100px;margin:32px auto;padding:0 20px}}
img{{max-width:100%;border:1px solid #ccd3df}}table{{border-collapse:collapse;width:100%;margin-top:20px}}
th,td{{border:1px solid #ccd3df;padding:9px;text-align:left}}th{{background:#edf2f7}}
.notice{{padding:12px;background:#fff7df;border-left:4px solid #e5a900}}</style></head>
<body><h1>IBVAP Image Analysis Report</h1><p>Report ID: {report_id}</p>
<p>Analyzed at (UTC): {escape(result.analyzed_at.isoformat())}</p>
<p>Image size: {result.image_width} × {result.image_height} · Detections: {len(result.detections)}</p>
<div class="notice">Results are advisory. This report lists model detections only; it does not identify people or prove that a person is inside a vehicle.</div>
<h2>Activity predictions</h2><ul>{predictions_html}</ul>
<h2>Registry lookup</h2><p>Registry lookup unavailable: no authorized vehicle registry API is configured. Owner details are restricted and are not inferred from OCR.</p>
<h2>Annotated image</h2><img src="data:image/jpeg;base64,{image_data}" alt="Annotated detection image">
<h2>Detection details</h2><table><thead><tr><th>#</th><th>Detection</th><th>Confidence</th><th>Plate text</th><th>OCR confidence</th><th>OCR object image</th></tr></thead>
<tbody>{rows or '<tr><td colspan="6">No detections</td></tr>'}</tbody></table></body></html>"""
    report_path = report_directory / f"{report_id}.html"
    report_path.write_text(report_html, encoding="utf-8")
    result.report_id = report_id
    result.report_download_reference = f"/api/v1/image-reports/{report_id}/download"
    for detection in result.detections:
        manager.events.publish(
            AnalyticsEvent(
                event_id=str(uuid4()),
                event_type="image_detection",
                occurred_at=result.analyzed_at,
                camera_id="image-upload",
                object=EventObject(
                    class_name=detection.class_name,
                    confidence=detection.confidence,
                    bounding_box=detection.bounding_box,
                ),
                details={
                    "filename": filename,
                    "plate_text": detection.plate_text,
                    "ocr_confidence": detection.ocr_confidence,
                    "report_id": report_id,
                },
            )
        )
    return result


def _analyze_video_and_create_report(
    manager: CameraManager,
    video_bytes: bytes,
    filename: str,
    analytics: set[VideoAnalytics],
    zones: list[object] | None,
) -> VideoAnalysisResult:
    result = VideoAnalysisResult.model_validate(
        manager.analyze_video(video_bytes, filename, analytics, zones=zones)
    )
    report_id = str(uuid4())
    report_directory = Path(manager.settings.database_path).parent / "reports"
    report_directory.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    evidence_directory = Path(manager.settings.database_path).parent / "evidence"
    for event in result.events:
        plate = event.details.get("plate_text")
        ocr_confidence = event.details.get("ocr_confidence")
        plate_text = escape(str(plate)) if plate else "Vehicle number not captured"
        ocr_text = f"{float(ocr_confidence):.1%}" if isinstance(ocr_confidence, (int, float)) else "Not available"
        snapshot_path = evidence_directory / f"{event.event_id}.jpg"
        image_html = "Not available"
        if snapshot_path.is_file():
            image_data = base64.b64encode(snapshot_path.read_bytes()).decode("ascii")
            image_html = f'<img src="data:image/jpeg;base64,{image_data}" alt="Detected event" style="max-width:240px">'
        plate_snapshot_path = evidence_directory / f"{event.event_id}_plate.jpg"
        if plate_snapshot_path.is_file():
            plate_data = base64.b64encode(plate_snapshot_path.read_bytes()).decode("ascii")
            image_html += f'<br><img src="data:image/jpeg;base64,{plate_data}" alt="OCR plate object" style="max-width:240px">'
        rows.append(
            f"<tr><td>{image_html}</td><td>{escape(event.event_type.replace('_', ' '))}</td>"
            f"<td>{escape(event.object.class_name if event.object else 'activity')}</td>"
            f"<td>{plate_text}</td><td>{ocr_text}</td>"
            f"<td>{escape(event.occurred_at.isoformat())}</td></tr>"
        )
    activities = "".join(
        f"<li><strong>{escape(prediction.activity)}</strong>: {escape(prediction.evidence)}</li>"
        for prediction in result.activity_predictions
    ) or "<li>No supported activity pattern found in this video.</li>"
    plate_reading_rows: list[str] = []
    for event in result.events:
        if event.event_type != "plate_read":
            continue
        ocr_confidence = event.details.get("ocr_confidence")
        ocr_text = f"{float(ocr_confidence):.1%}" if isinstance(ocr_confidence, (int, float)) else "Not available"
        plate_reading_rows.append(
            f"<li><strong>{escape(str(event.details.get('plate_text') or 'Vehicle number not captured'))}</strong>"
            f" ({escape(event.occurred_at.isoformat())}; OCR confidence: {ocr_text})</li>"
        )
    plate_readings = "".join(plate_reading_rows) or "<li>Vehicle number not captured</li>"
    report_html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>IBVAP Video Analysis Report</title>
<style>body{{font-family:Arial,sans-serif;color:#172033;max-width:1200px;margin:32px auto;padding:0 20px}}
table{{border-collapse:collapse;width:100%;margin-top:20px}}th,td{{border:1px solid #ccd3df;padding:9px;text-align:left}}
th{{background:#edf2f7}}.notice{{padding:12px;background:#fff7df;border-left:4px solid #e5a900}}</style></head>
<body><h1>IBVAP Video Analysis Report</h1><p>Report ID: {report_id}</p>
<p>Video: {escape(filename)} · Analyzed frames: {result.frames_analyzed}</p>
<div class="notice">Results are advisory. “Vehicle number not captured” means no accepted OCR text was produced for that event.</div>
<h2>Activity predictions</h2><ul>{activities}</ul>
<h2>Vehicle plate readings</h2><ul>{plate_readings}</ul>
<h2>Registry lookup</h2><p>Registry lookup unavailable: no authorized vehicle registry API is configured. Owner details are restricted and are not inferred from OCR.</p>
<h2>Detected events</h2><table><thead><tr><th>Detected image</th><th>Activity</th><th>Object</th><th>Vehicle number</th><th>OCR confidence</th><th>Time (UTC)</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="6">No events detected</td></tr>'}</tbody></table></body></html>"""
    report_path = report_directory / f"{report_id}.html"
    report_path.write_text(report_html, encoding="utf-8")
    result.report_id = report_id
    result.report_download_reference = f"/api/v1/video-reports/{report_id}/download"
    return result


app = create_app()

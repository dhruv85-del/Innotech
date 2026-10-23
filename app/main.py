from contextlib import asynccontextmanager
from collections.abc import Callable
from datetime import datetime
import hmac
from pathlib import Path
from typing import Annotated, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
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
    VideoAnalytics,
    VideoAnalysisResult,
    EventObject,
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
        return request.app.state.camera_manager.list()

    @router.get("/metrics/cameras", response_model=list[CameraMetrics])
    def camera_metrics(request: Request) -> list[CameraMetrics]:
        return request.app.state.camera_manager.metrics()

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
    ) -> VideoAnalysisResult:
        video_bytes = video.file.read(MAX_VIDEO_UPLOAD_BYTES + 1)
        if len(video_bytes) > MAX_VIDEO_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="video upload exceeds the 250 MiB limit")
        return _call_manager(
            lambda: request.app.state.camera_manager.analyze_video(
                video_bytes,
                video.filename or "uploaded-video",
                set(analytics),
            )
        )

    application.include_router(router)
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
                details={"filename": filename, "plate_text": detection.plate_text},
            )
        )
    return result


app = create_app()

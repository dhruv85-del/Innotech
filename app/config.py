from dataclasses import dataclass
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.is_file():
        load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_path: str
    event_retention_days: int
    person_vehicle_model: str | None
    plate_model: str | None
    face_cascade_path: str | None
    inference_provider: str
    inference_size: int
    confidence_threshold: float
    nms_threshold: float
    anpr_min_ocr_confidence: float
    process_fps: float
    loiter_seconds: float
    event_cooldown_seconds: float
    night_start_hour: int
    night_end_hour: int
    allow_file_sources: bool
    tesseract_cmd: str | None
    api_token: str | None
    plate_pattern: str = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$"

    def __post_init__(self) -> None:
        if self.inference_size <= 0:
            raise ValueError("IBVAP_INFERENCE_SIZE must be positive")
        if not 0 <= self.confidence_threshold <= 1:
            raise ValueError("IBVAP_CONFIDENCE_THRESHOLD must be between 0 and 1")
        if not 0 <= self.nms_threshold <= 1:
            raise ValueError("IBVAP_NMS_THRESHOLD must be between 0 and 1")
        if not 0 <= self.anpr_min_ocr_confidence <= 1:
            raise ValueError("IBVAP_ANPR_MIN_OCR_CONFIDENCE must be between 0 and 1")
        if not 0 < self.process_fps <= 30:
            raise ValueError("IBVAP_PROCESS_FPS must be greater than 0 and no more than 30")
        if self.loiter_seconds <= 0 or self.event_cooldown_seconds < 0:
            raise ValueError("loiter duration must be positive and event cooldown cannot be negative")
        if self.event_retention_days <= 0:
            raise ValueError("IBVAP_EVENT_RETENTION_DAYS must be positive")
        if not 0 <= self.night_start_hour <= 23 or not 0 <= self.night_end_hour <= 23:
            raise ValueError("night window hours must be between 0 and 23")
        if self.api_token is not None and len(self.api_token) < 32:
            raise ValueError("IBVAP_API_TOKEN must contain at least 32 characters")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=os.getenv("IBVAP_DATABASE_PATH", "data/events.sqlite3"),
            event_retention_days=int(os.getenv("IBVAP_EVENT_RETENTION_DAYS", "30")),
            person_vehicle_model=os.getenv("IBVAP_PERSON_VEHICLE_MODEL") or None,
            plate_model=os.getenv("IBVAP_PLATE_MODEL") or None,
            face_cascade_path=os.getenv("IBVAP_FACE_CASCADE_PATH") or None,
            inference_provider=os.getenv("IBVAP_INFERENCE_PROVIDER", "CPUExecutionProvider"),
            inference_size=int(os.getenv("IBVAP_INFERENCE_SIZE", "640")),
            confidence_threshold=float(os.getenv("IBVAP_CONFIDENCE_THRESHOLD", "0.35")),
            nms_threshold=float(os.getenv("IBVAP_NMS_THRESHOLD", "0.45")),
            anpr_min_ocr_confidence=float(os.getenv("IBVAP_ANPR_MIN_OCR_CONFIDENCE", "0.5")),
            plate_pattern=os.getenv(
                "IBVAP_PLATE_PATTERN",
                r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$",
            ),
            process_fps=float(os.getenv("IBVAP_PROCESS_FPS", "5")),
            loiter_seconds=float(os.getenv("IBVAP_LOITER_SECONDS", "30")),
            event_cooldown_seconds=float(os.getenv("IBVAP_EVENT_COOLDOWN_SECONDS", "30")),
            night_start_hour=int(os.getenv("IBVAP_NIGHT_START_HOUR", "20")),
            night_end_hour=int(os.getenv("IBVAP_NIGHT_END_HOUR", "6")),
            allow_file_sources=_env_bool("IBVAP_ALLOW_FILE_SOURCES"),
            tesseract_cmd=os.getenv("TESSERACT_CMD") or None,
            api_token=os.getenv("IBVAP_API_TOKEN") or None,
        )

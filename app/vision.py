from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import re

import cv2
import numpy as np

from app.schemas import BoundingBox

PERSON_CLASS_ID = 0
VEHICLE_CLASS_IDS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


@dataclass(frozen=True)
class Detection:
    class_name: str
    class_id: int
    confidence: float | None
    xyxy: tuple[float, float, float, float]

    def normalized_box(self, frame_width: int, frame_height: int) -> BoundingBox:
        x1, y1, x2, y2 = self.xyxy
        return BoundingBox(
            x=max(0.0, min(1.0, x1 / frame_width)),
            y=max(0.0, min(1.0, y1 / frame_height)),
            width=max(0.0, min(1.0, (x2 - x1) / frame_width)),
            height=max(0.0, min(1.0, (y2 - y1) / frame_height)),
        )


class YoloOnnxDetector:
    """Parser for raw YOLOv8 ONNX output: [1, 4 + classes, candidates]."""

    def __init__(
        self,
        model_path: str,
        labels: dict[int, str],
        allowed_class_ids: set[int],
        input_size: int = 640,
        confidence_threshold: float = 0.35,
        nms_threshold: float = 0.45,
        provider: str = "CPUExecutionProvider",
    ) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"ONNX model file does not exist: {model_path}")
        import onnxruntime as ort

        providers = ort.get_available_providers()
        if provider not in providers:
            raise RuntimeError(f"ONNX Runtime provider is unavailable: {provider}")
        self.session = ort.InferenceSession(model_path, providers=[provider])
        self.input_name = self.session.get_inputs()[0].name
        self.labels = labels
        self.allowed_class_ids = allowed_class_ids
        self.input_size = input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold

    def detect(self, frame: np.ndarray) -> list[Detection]:
        height, width = frame.shape[:2]
        scale = min(self.input_size / width, self.input_size / height)
        resized_width, resized_height = round(width * scale), round(height * scale)
        scale_x, scale_y = resized_width / width, resized_height / height
        resized = cv2.resize(frame, (resized_width, resized_height))
        canvas = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        pad_x = (self.input_size - resized_width) // 2
        pad_y = (self.input_size - resized_height) // 2
        canvas[pad_y : pad_y + resized_height, pad_x : pad_x + resized_width] = resized
        tensor = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        output = self.session.run(None, {self.input_name: tensor})[0]
        if output.ndim != 3 or output.shape[0] != 1:
            raise RuntimeError(f"Unsupported YOLO ONNX output shape: {output.shape}")
        predictions = output[0]
        if predictions.shape[0] < predictions.shape[1]:
            predictions = predictions.T
        if predictions.shape[1] != 4 + len(self.labels):
            raise RuntimeError(
                "Expected raw YOLOv8 output with 4 box values and one score per configured class; "
                f"got shape {output.shape} and {len(self.labels)} configured classes"
            )
        boxes: list[list[int]] = []
        scores: list[float] = []
        class_ids: list[int] = []
        for row in predictions:
            class_id = int(np.argmax(row[4:]))
            score = float(row[4 + class_id])
            if class_id not in self.allowed_class_ids or score < self.confidence_threshold:
                continue
            center_x, center_y, box_width, box_height = row[:4]
            left = (float(center_x) - float(box_width) / 2 - pad_x) / scale_x
            top = (float(center_y) - float(box_height) / 2 - pad_y) / scale_y
            right = (float(center_x) + float(box_width) / 2 - pad_x) / scale_x
            bottom = (float(center_y) + float(box_height) / 2 - pad_y) / scale_y
            x1 = max(0, min(width - 1, round(left)))
            y1 = max(0, min(height - 1, round(top)))
            x2 = max(x1 + 1, min(width, round(right)))
            y2 = max(y1 + 1, min(height, round(bottom)))
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            scores.append(score)
            class_ids.append(class_id)
        kept_indices: list[int] = []
        for class_id in set(class_ids):
            class_indices = [index for index, candidate in enumerate(class_ids) if candidate == class_id]
            class_kept = cv2.dnn.NMSBoxes(
                [boxes[index] for index in class_indices],
                [scores[index] for index in class_indices],
                self.confidence_threshold,
                self.nms_threshold,
            )
            kept_indices.extend(class_indices[int(index)] for index in np.asarray(class_kept).reshape(-1))
        if not kept_indices:
            return []
        return [
            Detection(
                class_name=self.labels[class_ids[int(index)]],
                class_id=class_ids[int(index)],
                confidence=scores[int(index)],
                xyxy=(
                    float(boxes[int(index)][0]),
                    float(boxes[int(index)][1]),
                    float(boxes[int(index)][0] + boxes[int(index)][2]),
                    float(boxes[int(index)][1] + boxes[int(index)][3]),
                ),
            )
            for index in kept_indices
        ]


class HaarFaceDetector:
    def __init__(self, cascade_path: str | None = None) -> None:
        path = cascade_path or (Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        self.classifier = cv2.CascadeClassifier(str(path))
        if self.classifier.empty():
            raise RuntimeError(f"Could not load face cascade: {path}")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
        return [
            Detection(
                class_name="face",
                class_id=-1,
                confidence=None,
                xyxy=(float(x), float(y), float(x + width), float(y + height)),
            )
            for x, y, width, height in faces
        ]


class PlateReader:
    def __init__(self, tesseract_cmd: str | None = None) -> None:
        import pytesseract

        self.pytesseract = pytesseract
        executable = tesseract_cmd or shutil.which("tesseract")
        if executable is None:
            for candidate in (
                Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
                Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
            ):
                if candidate.is_file():
                    executable = str(candidate)
                    break
        if executable:
            self.pytesseract.pytesseract.tesseract_cmd = executable

    def read(
        self,
        frame: np.ndarray,
        detection: Detection,
        minimum_confidence: float = 0.5,
        plate_pattern: str | None = None,
    ) -> tuple[str, float] | None:
        x1, y1, x2, y2 = (int(value) for value in detection.xyxy)
        height, width = frame.shape[:2]
        padding_x = max(2, round((x2 - x1) * 0.12))
        padding_y = max(2, round((y2 - y1) * 0.35))
        x1 = max(0, x1 - padding_x)
        y1 = max(0, y1 - padding_y)
        x2 = min(width, x2 + padding_x)
        y2 = min(height, y2 + padding_y)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        denoised = cv2.bilateralFilter(clahe, 5, 40, 40)
        variants = [
            gray,
            clahe,
            denoised,
            cv2.normalize(denoised, None, 0, 255, cv2.NORM_MINMAX),
            cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
            cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
            ),
        ]
        candidates: list[tuple[str, float]] = []
        for variant in variants:
            for page_mode in (6, 7, 8, 13):
                result = self.pytesseract.image_to_data(
                    variant,
                    config=(
                        f"--psm {page_mode} "
                        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                    ),
                    output_type=self.pytesseract.Output.DICT,
                )
                text_parts: list[str] = []
                scores: list[float] = []
                for text, confidence in zip(result["text"], result["conf"]):
                    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
                    try:
                        score = float(confidence) / 100
                    except (TypeError, ValueError):
                        continue
                    if cleaned and score >= minimum_confidence and score >= 0:
                        text_parts.append(cleaned)
                        scores.append(score)
                if text_parts:
                    candidates.append(("".join(text_parts), sum(scores) / len(scores)))
        if not candidates:
            return None
        valid = [
            candidate for candidate in candidates
            if plate_pattern is None or re.fullmatch(plate_pattern, candidate[0])
        ]
        if plate_pattern is not None and not valid:
            return None
        selected = max(
            valid or candidates,
            key=lambda candidate: (
                bool(plate_pattern and re.fullmatch(plate_pattern, candidate[0])),
                candidate[1],
                len(candidate[0]),
            ),
        )
        if selected[1] < minimum_confidence:
            return None
        return selected

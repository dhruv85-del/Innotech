# IBVAP AI Video Analytics Service

This repository contains the first runnable AI-service phase described in [AI_SERVICE_PHASE.md](./AI_SERVICE_PHASE.md). It is a local, separately deployable FastAPI service for camera stream decoding, on-premises inference, tracking, basic configurable events, and event logging.

For a code-grounded visual explanation of the runtime components, live camera
pipeline, upload paths, dashboard polling, and storage lifecycle, see
[ARCHITECTURE.md](./ARCHITECTURE.md).

## Current capability and limits

- RTSP/RTSPS stream workers are isolated per camera and reconnect after stream failures.
- Person and common vehicle detection use a raw-output YOLOv8 ONNX model trained/exported for the COCO 80-class layout. ByteTrack associates detections per camera.
- Face detection uses OpenCV's Haar cascade as a baseline only. It does not identify people; its output has no calibrated confidence score. Evaluate a better-licensed detector on representative footage before operational use.
- ANPR uses a separate one-class license-plate YOLOv8 ONNX detector followed by local Tesseract OCR. OCR only reports strings above the configured confidence floor; this does not establish vehicle identity.
- Virtual-fence entry, zone loitering (zone override or service default), and configured-UTC-hour night movement are implemented as deterministic rules. A confidence threshold or rule event is not a guarantee of detection.
- Events are persisted in SQLite with a configurable 30-day default retention (`IBVAP_EVENT_RETENTION_DAYS`); expiry is enforced at startup, event cleanup batches, and event queries. The API offers polling; no command-center connector or event push delivery is configured yet.
- Camera configurations and worker state are in memory and must be registered again after a service restart; stream credentials are not written to the database.
- Video frames are not persisted, but event JPEG snapshots are retained internally as evidence. Plate text is included in `plate_read` event details and must be protected and retained according to the deployment's policy.
- Image and video analysis reports include detected vehicle numbers and OCR confidence. CSV alert exports expose vehicle number and OCR confidence as dedicated columns. If OCR does not produce an accepted result, reports state `Vehicle number not captured`.
- ANPR preprocessing uses multiple scaled/thresholded crops and Tesseract page modes with an alphanumeric whitelist. Plate text is validated against `IBVAP_PLATE_PATTERN`, which defaults to a broad Indian registration format and can be customized.
- Reports embed the annotated image for image analysis and available event snapshots for video analysis. The vehicle-registry adapter is disabled until an authorized API is configured; it does not infer owner details from a plate.

The service intentionally has no face-recognition, biometric matching, watchlist, or identity lookup capability. Alerts are advisory and require human review.

## Requirements

- Python 3.11 or newer.
- FFmpeg-capable OpenCV build; install the FFmpeg executable/runtime required by your operating system and camera environment.
- Tesseract OCR installed locally if ANPR is enabled.
- Compatible model files at the configured model paths. Model weights are not included or downloaded automatically: review their licenses and export format before deployment.

No external AI-provider API key is needed. `IBVAP_API_TOKEN` is a locally generated service-access secret, not a provider key; it is required for all `/api/v1` operations. Do not send it to anyone or commit it.

## Install and run on Windows PowerShell

From the project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

Set a strong, unique API token in the shell or your approved secret manager:

```powershell
$env:IBVAP_API_TOKEN = "<locally-generated-random-secret>"
$env:IBVAP_DATABASE_PATH = "data\events.sqlite3"
$env:IBVAP_PERSON_VEHICLE_MODEL = "C:\models\person-vehicle-yolov8.onnx"
$env:IBVAP_PLATE_MODEL = "C:\models\license-plate-yolov8.onnx"
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Only configure paths for capabilities you have installed. For local video-file testing, set `$env:IBVAP_ALLOW_FILE_SOURCES = "true"`; it is disabled by default. Keep the API bound to loopback during local development. Before any network deployment, configure the service token, restrict network access, and add the platform's authentication/authorization and transport controls.

On Windows, the service also auto-detects Tesseract in the standard `C:\Program Files\Tesseract-OCR\tesseract.exe` or `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe` location. Set `TESSERACT_CMD` when using a non-standard installation.

Health check: `GET http://127.0.0.1:8000/health`  
Readiness/model capability check: `GET http://127.0.0.1:8000/ready`  
Image-analysis showcase: `http://127.0.0.1:8000/`  
Interactive API schema: `http://127.0.0.1:8000/docs`

Use `X-API-Key: <IBVAP_API_TOKEN>` for every `/api/v1` request. For example, PowerShell:

```powershell
$headers = @{ "X-API-Key" = $env:IBVAP_API_TOKEN }
$camera = @{
  camera_id = "bop-gate-01"
  source = "rtsp://camera-host:554/path"
  analytics = @("person_vehicle", "intrusion", "loitering", "night_movement")
  process_fps = 5
  zones = @(@{
    zone_id = "restricted-area"
    polygon = @(
      @{ x = 0.2; y = 0.2 },
      @{ x = 0.8; y = 0.2 },
      @{ x = 0.8; y = 0.8 },
      @{ x = 0.2; y = 0.8 }
    )
    restricted = $true
    loiter_seconds = 30
  })
}
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/cameras" `
  -Headers $headers -ContentType "application/json" -Body ($camera | ConvertTo-Json -Depth 8)
```

Camera stream URLs are accepted in request bodies but are never included in camera responses. Keep credentials out of shell history when possible, prefer secret references or network-level camera credentials, and use RTSPS where supported.

Create with analytics set to `[]` to register a camera before installing models, then enable analytics after setup. Starting person/vehicle, intrusion, loitering, or night analytics requires the person/vehicle model. ANPR requires its plate model and Tesseract. Missing weights or runtimes are reported as unavailable; the service does not fabricate empty detections.

Other useful calls:

- `POST /api/v1/cameras/{camera_id}/start`
- `POST /api/v1/cameras/{camera_id}/stop`
- `PATCH /api/v1/cameras/{camera_id}` (camera must be stopped)
- `GET /api/v1/cameras`
- `GET /api/v1/events?camera_id=bop-gate-01&limit=100`
- `GET /api/v1/events/{event_id}/snapshot` (authenticated event evidence image)
- `GET /api/v1/metrics/cameras`
- `POST /api/v1/videos/analyze` (authenticated multipart upload, maximum 250 MiB)

## Sample-image demo

The image-analysis page at `http://127.0.0.1:8000/` offers upload, analytics selection, and annotated detection results. It calls the authenticated `POST /api/v1/images/analyze` endpoint and keeps the API token in page memory only. The endpoint accepts one image upload for demonstrations when a live camera or video clip is unavailable. Select one or more analytics: `person_vehicle`, `face`, or `anpr`. The response contains image dimensions and normalized detection boxes; ANPR results include OCR text only when it meets the configured confidence floor. Images are processed in memory and are not saved, and this endpoint does not create event records.

The endpoint requires the corresponding configured model/runtime. Person and vehicle detection needs `IBVAP_PERSON_VEHICLE_MODEL`; ANPR additionally needs `IBVAP_PLATE_MODEL` and Tesseract. Uploads are limited to 10 MiB and decoded images to 25 megapixels. Sample images can demonstrate per-image detections, but cannot validate tracking, loitering duration, night movement, live-stream reliability, or real-world accuracy. Label demo inputs and results as illustrative, not operationally validated.

After image analysis, the service creates a standalone HTML report with the annotated image, detected classes, confidence scores, plate text, and OCR confidence. The response includes a report ID and authenticated download reference, and the React upload page provides a **Download detailed report** button. The report does not infer identities or claim that a detected person is inside a vehicle unless a future model explicitly supports that relationship.

Uploaded video analysis uses the same configured detectors and rule engine as a temporary camera pipeline. It samples frames at the configured processing rate, returns generated events, and does not retain the uploaded video. Video uploads are limited to 250 MiB; use licensed test clips because this route is a validation/demo tool, not a substitute for live-stream qualification.

Video analysis also creates a downloadable HTML report. The report lists every detected activity/event, vehicle number, OCR confidence, event time, and a dedicated vehicle plate readings section. If a plate is not detected or accepted by OCR, the report explicitly states **Vehicle number not captured**. The video response includes a report download reference.

When `anpr` is enabled with a compatible plate model and Tesseract, recognized plate text and OCR confidence are included in `plate_read` events. The report displays the plate text, detected vehicle/object, confidence, zone, and event status. Plate OCR is advisory and must be validated against the target jurisdiction, camera angles, lighting, and vehicle speeds.

Camera processing metrics are available through the authenticated `GET /api/v1/metrics/cameras` endpoint. They report processed/dropped frames and inference timing per registered camera; they are observational metrics, not a capacity guarantee.

Example PowerShell request:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/images/analyze" `
  -H "X-API-Key: $env:IBVAP_API_TOKEN" `
  -F "image=@C:\path\to\sample.jpg" `
  -F "analytics=person_vehicle"
```

You can also use the interactive API page at `http://127.0.0.1:8000/docs`; enter the service token in the `X-API-Key` field for the request.

The repository can also use a public sample image for a local demonstration:

```powershell
New-Item -ItemType Directory -Force samples | Out-Null
curl.exe -L --fail -o samples\bus.jpg https://ultralytics.com/images/bus.jpg
```

With the demo model and sample image configured, restart the service and open the showcase page. The sample should produce person and bus detections on a CPU, although confidence and latency depend on the machine.

## Model input contract

The built-in detector adapter expects an ONNX model with raw YOLOv8 output, no embedded NMS:

- Person/vehicle model: exactly 80 COCO class scores after the four box values; class IDs follow the standard COCO ordering.
- Plate model: exactly one class score after the four box values; class `0` means `license_plate`.
- Input is letterboxed to the configured square `IBVAP_INFERENCE_SIZE` (default 640), converted BGR-to-RGB, normalized to `[0,1]`, and passed as NCHW float32.
- The adapter applies class filtering and OpenCV NMS. Models with different output layouts, class maps, input normalization, or embedded NMS are not compatible without an adapter change.

Verify the model export against known images before connecting operational streams. Model quality, plate jurisdiction, camera placement, lighting, and image compression materially affect accuracy.

## Configuration

See [.env.example](./.env.example) for the full list. Environment variables are read directly; the application does not automatically load `.env` files.

Notable settings:

- `IBVAP_API_TOKEN`: required API secret.
- `IBVAP_EVENT_RETENTION_DAYS`: age after which event records are removed (default 30 days).
- `IBVAP_PERSON_VEHICLE_MODEL`, `IBVAP_PLATE_MODEL`: external ONNX model file paths.
- `IBVAP_INFERENCE_PROVIDER`: defaults to `CPUExecutionProvider`; the matching ONNX Runtime provider must be installed and available. The supplied Docker image is CPU-only; GPU deployment requires replacing its ONNX Runtime package and configuring compatible CUDA/cuDNN drivers.
- `IBVAP_PROCESS_FPS`: maximum inference sampling rate; frames can be dropped to avoid growing processing latency.
- `IBVAP_ANPR_MIN_OCR_CONFIDENCE`: Tesseract confidence floor from 0 to 1.
- `IBVAP_NIGHT_START_HOUR` and `IBVAP_NIGHT_END_HOUR`: UTC hours in this baseline; camera/site timezone configuration is not yet implemented.
- `IBVAP_ALLOW_FILE_SOURCES`: enables local video files for controlled testing; leave disabled in production.

The API token must be at least 32 characters. Generate and store it locally; do not send it in chat or commit it.

### Local person/vehicle demo model

For a local technical demonstration only, the official Ultralytics `yolov8n.onnx` asset can be downloaded into the ignored `models` directory:

```powershell
New-Item -ItemType Directory -Force models | Out-Null
curl.exe -L --fail -o models\yolov8n.onnx `
  https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.onnx
$env:IBVAP_PERSON_VEHICLE_MODEL = (Resolve-Path models\yolov8n.onnx)
```

This public asset is suitable for a technical demo and uses the COCO class layout expected by this service. Review the current Ultralytics license (AGPL-3.0 or a separately purchased commercial license, depending on the intended use) before any government, commercial, or distributed deployment. Do not describe this demo asset as custom border-security training or as production-validated accuracy.

## Tests

```powershell
python -m pytest
```

The automated tests cover zone geometry, cooldown behavior, event persistence/retention/deduplication, API token enforcement, source-URL redaction, synthetic YOLO output parsing, and synthetic ByteTrack continuity. They do not measure detector, tracker, OCR, night, or multi-camera accuracy. Those require licensed, representative video, ground-truth labels, and benchmarks on the actual target hardware.

## Operational rollout gates

Before production use, select and license the detector/plate weights, evaluate face and plate detection on representative local footage, confirm the supported plate jurisdiction and operating conditions, benchmark camera count and event latency on target hardware, configure retention/access for event and plate data, and integrate authorized command-and-control event delivery. Do not use these prototype outputs as a sole basis for enforcement or response decisions.

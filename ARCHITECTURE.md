# IBVAP Architecture

This document describes the current runtime architecture of the IBVAP AI Video
Analytics Service. The diagrams are intentionally based on the implementation
in this repository, not on a future production design.

## 1. System overview

```mermaid
flowchart LR
    operator[Operator]
    dashboard["React dashboard<br/>Frontend_IBVAP"]
    demo["Image demo page<br/>app/static/index.html"]
    api["FastAPI application<br/>app/main.py"]
    auth["X-API-Key<br/>authentication"]
    manager["CameraManager<br/>app/cameras.py"]
    workers["Per-camera worker threads"]
    streams["RTSP / RTSPS cameras<br/>or opt-in local video files"]
    uploads["Image and video uploads"]
    vision["Vision adapters<br/>YOLO ONNX / Haar / Tesseract"]
    tracking["ByteTrack<br/>per-camera tracking"]
    rules["Rule engine<br/>intrusion, loitering, night movement"]
    store["EventStore<br/>app/events.py"]
    sqlite[("SQLite<br/>data/events.sqlite3")]
    evidence[("JPEG evidence<br/>data/evidence/")]
    models["Local model/runtime files<br/>models/*.onnx + Tesseract"]
    config["Environment configuration<br/>app/config.py / .env"]

    operator --> dashboard
    operator --> demo
    dashboard -->|polls API every 4s| api
    demo --> api
    api --> auth
    auth --> manager
    auth --> store
    api -->|upload analysis| manager
    manager --> workers
    workers --> streams
    workers --> vision
    uploads --> manager
    manager --> vision
    vision --> tracking
    tracking --> rules
    vision --> rules
    rules -->|analytics events| store
    store --> sqlite
    manager -->|event snapshots| evidence
    store -->|event metadata| api
    evidence -->|authenticated snapshot endpoint| api
    config --> api
    config --> manager
    vision --> models
```

### Main responsibilities

| Area | Responsibility | Implementation |
| --- | --- | --- |
| Web/API boundary | Serves health/readiness, camera management, analysis, event, metrics, and snapshot endpoints | [`app/main.py`](./app/main.py) |
| Camera orchestration | Keeps camera configuration in memory and owns one worker thread per active camera | [`app/cameras.py`](./app/cameras.py) |
| Detection | Runs local ONNX object/plate detection, Haar face detection, and local OCR | [`app/vision.py`](./app/vision.py) |
| Tracking | Assigns stable IDs to person/vehicle detections for each camera | [`app/tracking.py`](./app/tracking.py) |
| Rules | Converts tracked detections into intrusion, loitering, and night-movement decisions | [`app/rules.py`](./app/rules.py), [`app/cameras.py`](./app/cameras.py) |
| Persistence | Stores event JSON and operator alert actions in SQLite; removes expired events | [`app/events.py`](./app/events.py) |
| Dashboard | Presents camera, alert, report, upload, and settings views; polls the API | [`Frontend_IBVAP/src/App.tsx`](./Frontend_IBVAP/src/App.tsx), [`Frontend_IBVAP/src/api.ts`](./Frontend_IBVAP/src/api.ts) |

## 2. Live camera flow

Each registered camera has its own worker thread. Camera configuration and
worker state are in memory, so cameras must be registered again after a service
restart.

```mermaid
sequenceDiagram
    autonumber
    participant UI as React dashboard
    participant API as FastAPI API
    participant CM as CameraManager
    participant W as Camera worker
    participant SRC as RTSP/RTSPS source
    participant D as Detectors
    participant T as ByteTrack
    participant R as Rule engine
    participant DB as SQLite EventStore
    participant FS as Evidence JPEG

    UI->>API: POST /api/v1/cameras
    API->>CM: validate config and capabilities
    CM-->>API: camera status
    UI->>API: POST /api/v1/cameras/{id}/start
    API->>CM: start camera
    CM->>W: create daemon worker thread
    W->>SRC: open stream with FFmpeg timeouts
    loop Until stopped or stream fails
        SRC-->>W: frame
        W->>W: sample at process_fps<br/>and count dropped frames
        W->>D: person/vehicle, face, or plate detection
        D-->>W: bounding boxes and confidence
        W->>T: update tracked person/vehicle detections
        T-->>W: track IDs
        W->>R: evaluate zones, cooldowns, and UTC night window
        R-->>W: zero or more event decisions
        W->>FS: write event frame snapshot
        W->>DB: persist event metadata and evidence reference
    end
    UI->>API: GET /api/v1/events and /metrics/cameras
    API->>DB: query retained events and actions
    DB-->>API: event data
    API-->>UI: dashboard data
    UI->>API: GET /api/v1/events/{id}/snapshot
    API->>FS: read evidence JPEG
    FS-->>UI: authenticated image
```

### Event decision details

1. **Person/vehicle analytics** use the configured raw-output YOLOv8 ONNX
   model, class filtering, and non-maximum suppression.
2. **Tracking** uses ByteTrack independently for each camera worker.
3. **Virtual-fence intrusion** is emitted when a tracked detection enters a
   restricted polygon.
4. **Loitering** is emitted after a tracked detection remains in a zone for
   the configured duration.
5. **Night movement** is emitted for a tracked detection inside the configured
   UTC-hour window.
6. **Face detection** uses OpenCV Haar cascades and is not identity matching.
7. **ANPR** detects a plate with the plate YOLO model, then uses Tesseract OCR.
8. Event cooldown state prevents repeated events for the same event/track/key.

## 3. Image and video upload flows

Uploads are temporary analysis inputs. The uploaded bytes are not retained
after processing. Image analysis publishes `image_detection` events; video
analysis creates a temporary camera runtime so it can reuse the live pipeline.

```mermaid
flowchart TD
    start{Operator selects upload}
    start -->|image| imageForm["POST /api/v1/images/analyze<br/>multipart/form-data"]
    start -->|video| videoForm["POST /api/v1/videos/analyze<br/>multipart/form-data"]

    imageForm --> imageDecode["Decode in memory<br/>max 10 MiB / 25 MP"]
    imageDecode --> imageDetect["Run selected detectors"]
    imageDetect --> imageResult["Return detections + report download reference"]
    imageDetect --> imageEvents["Publish image_detection events<br/>camera_id = image-upload"]
    imageEvents --> db[(SQLite)]
    imageDetect --> imageReport["Create annotated HTML report<br/>with embedded detection image and OCR details"]
    imageReport --> reports[("HTML reports<br/>data/reports/")]
    reports -->|authenticated download endpoint| imageResult

    videoForm --> videoTemp["Write upload to temporary file<br/>max 250 MiB"]
    videoTemp --> videoRuntime["Create temporary CameraRuntime"]
    videoRuntime --> videoCapture["Read and sample video frames"]
    videoCapture --> shared["Shared _process_frame pipeline"]
    shared --> videoResult["Return analyzed frame count<br/>and generated events"]
    shared --> db
    videoResult --> cleanup["Release capture and delete<br/>temporary video file"]
```

Image and video reports include detected vehicle plate text and OCR confidence.
When no accepted plate reading is available, the report explicitly states
`Vehicle number not captured`. CSV alert exports expose vehicle number and OCR
confidence as dedicated columns. Reports embed annotated image results and
available video event snapshots. The vehicle-registry adapter is disabled until
an authorized API is configured; owner details are never inferred from OCR.

## 4. Dashboard request flow

The dashboard does not receive a push stream. After the token is configured,
[`App.tsx`](./Frontend_IBVAP/src/App.tsx) refreshes readiness, cameras, events,
and alert actions every four seconds.

```mermaid
flowchart LR
    app["App context"]
    layout["Layout and routes"]
    pages["Dashboard / Cameras / Alerts<br/>Reports / Uploads / Settings"]
    client["API client<br/>Frontend_IBVAP/src/api.ts"]
    api["FastAPI endpoints"]
    state["React state"]
    voice["Browser speech alerts<br/>voiceAlerts.ts"]

    app --> layout
    layout --> pages
    app --> client
    client -->|X-API-Key| api
    api --> client
    client --> state
    state --> pages
    state -->|new suspicious event| voice
    pages -->|camera, action, upload commands| client
```

The production-style dashboard is served at `/ui` when
`Frontend_IBVAP/dist/index.html` exists. The lightweight image-analysis
showcase is served at `/`. During frontend development, Vite serves the React
application separately.

## 5. Storage and lifecycle

```mermaid
flowchart TD
    startup["FastAPI startup"] --> settings["Settings.from_env()"]
    startup --> eventStore["EventStore initialization"]
    eventStore --> schema["Create events and alert_actions tables"]
    eventStore --> purge["Delete events older than retention window"]
    eventStore --> sqlite[("data/events.sqlite3")]
    emit["Analytics event"] --> persist["EventStore.publish()"]
    persist --> sqlite
    emit --> snapshot["CameraManager._emit()"]
    snapshot --> evidence[("data/evidence/{event_id}.jpg")]
    query["GET /api/v1/events"] --> cleanup["Retention cleanup"]
    cleanup --> sqlite
    shutdown["FastAPI shutdown"] --> stop["CameraManager.stop_all()"]
    stop --> workers["Camera worker threads"]
```

- Event rows and alert actions are durable in SQLite.
- Camera registrations, credentials, detector instances, trackers, and rule
  state are process-local.
- Evidence JPEGs are stored beside the configured database path in an
  `evidence` directory.
- Plate-read events store an annotated full-frame evidence JPEG and a separate
  cropped plate JPEG; image and video HTML reports embed the detected plate
  crop beside the OCR text and confidence.
- The default event retention is 30 days and is configurable with
  `IBVAP_EVENT_RETENTION_DAYS`.
- No video frames or uploaded source videos are retained as part of normal
  processing.

## 6. Configuration and deployment boundary

```mermaid
flowchart LR
    env["Environment / .env"] --> settings["Settings"]
    settings --> server["Uvicorn + FastAPI"]
    settings --> database["SQLite path"]
    settings --> detector["ONNX Runtime"]
    settings --> ocr["Tesseract executable"]
    models["Configured ONNX model files"] --> detector
    cameras["Network camera URLs"] --> server
    browser["Browser"] -->|HTTP + X-API-Key| server
```

The service is designed to run locally or on-premises. It does not call an
external AI provider. The API token is a service secret and must be configured
before `/api/v1` operations are available. See [`README.md`](./README.md) and
[`.env.example`](./.env.example) for setup and configuration details.

## 7. Important boundaries and limitations

- **Authentication:** `/api/v1/*` requires `X-API-Key`; `/health`, `/ready`,
  `/`, and `/docs` are outside that router-level dependency.
- **Source types:** RTSP/RTSPS are accepted by default. Local video files
  require `IBVAP_ALLOW_FILE_SOURCES=true`.
- **Inference:** models are loaded from local paths and are cached by
  `CameraManager`; model licenses and output compatibility must be verified
  before deployment.
- **Identity:** the service has no face recognition, biometric matching,
  watchlist, or identity lookup.
- **Delivery:** event consumption is polling-based. There is no websocket,
  message queue, command-center connector, or push notification integration.
- **Scaling:** camera workers and state live inside one process. Horizontal
  scaling would require an explicit ownership and shared-state design.
- **Evidence:** snapshots are evidence images, not a video archive. Protect
  plate text, event records, and snapshot access according to deployment
  policy.

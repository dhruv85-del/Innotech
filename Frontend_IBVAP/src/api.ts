export type Analytics = 'person_vehicle' | 'face' | 'anpr' | 'intrusion' | 'loitering' | 'night_movement'

export type Readiness = {
  status: string
  capabilities: Record<string, boolean>
  missing_requirements: string[]
}

export type CameraStatus = {
  camera_id: string
  state: 'stopped' | 'connecting' | 'running' | 'error'
  analytics: string[]
  process_fps: number
  last_frame_at: string | null
  last_error: string | null
  processed_frames: number
  dropped_frames: number
  inference_count: number
  total_inference_ms: number
}

export type CameraMetrics = CameraStatus & { average_inference_ms: number }

export type AnalyticsEvent = {
  event_id: string
  event_type: string
  occurred_at: string
  camera_id: string
  track_id: string | null
  zone_id: string | null
  object: { class_name: string; confidence: number | null } | null
  details: Record<string, string | number | boolean | null>
  evidence: { snapshot_reference: string | null }
}

export type AlertAction = {
  event_id: string
  status: 'Acknowledged' | 'Dismissed'
  acted_at: string
}

export type ImageAnalysisResult = {
  analyzed_at: string
  image_width: number
  image_height: number
  analytics: string[]
  detections: Array<{
    class_name: string
    confidence: number | null
    bounding_box: { x: number; y: number; width: number; height: number }
    plate_text: string | null
    ocr_confidence: number | null
  }>
  report_id: string | null
  report_download_reference: string | null
  activity_predictions: Array<{ activity: string; confidence: number | null; evidence: string }>
}

export type VideoAnalysisResult = {
  analyzed_at: string
  filename: string
  frames_analyzed: number
  events: AnalyticsEvent[]
  activity_predictions: Array<{ activity: string; confidence: number | null; evidence: string }>
  report_id: string | null
  report_download_reference: string | null
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')

async function request<T>(path: string, options: RequestInit = {}, token: string): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('X-API-Key', token)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}.`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // Preserve the HTTP error when the service does not return JSON.
    }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export const api = {
  readiness: (token: string) => request<Readiness>('/ready', {}, token),
  cameras: (token: string) => request<CameraStatus[]>('/api/v1/cameras', {}, token),
  metrics: (token: string) => request<CameraMetrics[]>('/api/v1/metrics/cameras', {}, token),
  events: (token: string) => request<AnalyticsEvent[]>('/api/v1/events?limit=1000', {}, token),
  alertActions: (token: string) => request<AlertAction[]>('/api/v1/alert-actions', {}, token),
  recordAlertAction: (token: string, eventId: string, status: AlertAction['status']) =>
    request<AlertAction>(`/api/v1/events/${encodeURIComponent(eventId)}/action`, {
      method: 'POST',
      body: JSON.stringify({ event_id: eventId, status, acted_at: new Date().toISOString() }),
    }, token),
  eventSnapshot: async (token: string, eventId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/v1/events/${encodeURIComponent(eventId)}/snapshot`, {
      headers: { 'X-API-Key': token },
    })
    if (!response.ok) throw new ApiError(response.status, 'Snapshot unavailable')
    return response.blob()
  },
  imageReport: async (token: string, reportId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/v1/image-reports/${encodeURIComponent(reportId)}/download`, {
      headers: { 'X-API-Key': token },
    })
    if (!response.ok) throw new ApiError(response.status, 'Image report unavailable')
    return response.blob()
  },
  videoReport: async (token: string, reportId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/v1/video-reports/${encodeURIComponent(reportId)}/download`, {
      headers: { 'X-API-Key': token },
    })
    if (!response.ok) throw new ApiError(response.status, 'Video report unavailable')
    return response.blob()
  },
  createCamera: (token: string, body: { camera_id: string; source: string; analytics: string[]; start: boolean }) =>
    request<CameraStatus>('/api/v1/cameras', { method: 'POST', body: JSON.stringify(body) }, token),
  updateCamera: (token: string, cameraId: string, body: { analytics?: string[]; process_fps?: number }) =>
    request<CameraStatus>(`/api/v1/cameras/${encodeURIComponent(cameraId)}`, { method: 'PATCH', body: JSON.stringify(body) }, token),
  startCamera: (token: string, cameraId: string) =>
    request<CameraStatus>(`/api/v1/cameras/${encodeURIComponent(cameraId)}/start`, { method: 'POST' }, token),
  stopCamera: (token: string, cameraId: string) =>
    request<CameraStatus>(`/api/v1/cameras/${encodeURIComponent(cameraId)}/stop`, { method: 'POST' }, token),
  analyzeImage: (token: string, image: File, analytics: Analytics[]) => {
    const body = new FormData()
    body.append('image', image)
    analytics.forEach((item) => body.append('analytics', item))
    return request<ImageAnalysisResult>('/api/v1/images/analyze', { method: 'POST', body }, token)
  },
  analyzeVideo: (token: string, video: File, analytics: Analytics[]) => {
    const body = new FormData()
    body.append('video', video)
    analytics.forEach((item) => body.append('analytics', item))
    return request<VideoAnalysisResult>('/api/v1/videos/analyze', { method: 'POST', body }, token)
  },
}

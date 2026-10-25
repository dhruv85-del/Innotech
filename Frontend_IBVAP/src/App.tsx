import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, type AlertAction, type AnalyticsEvent, type CameraStatus, type Readiness } from './api'
import { Layout } from './components/Layout'
import { AlertsPage } from './pages/AlertsPage'
import { DashboardPage } from './pages/DashboardPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'
import { MediaUploadPage, UploadHistoryPage } from './pages/UploadsPage'
import { initialMedia, type UploadedMedia } from './data'
import { CamerasPage } from './pages/CamerasPage'
import { announceSecurityEvent, speakAlert } from './voiceAlerts'

type AppContextValue = {
  token: string
  setToken: (token: string) => void
  readiness: Readiness | null
  cameras: CameraStatus[]
  events: AnalyticsEvent[]
  alertActions: AlertAction[]
  recordAlertAction: (eventId: string, status: AlertAction['status']) => Promise<void>
  apiError: string
  refresh: () => Promise<void>
}

const AppContext = createContext<AppContextValue | null>(null)

export function useAppContext() {
  const context = useContext(AppContext)
  if (!context) throw new Error('useAppContext must be used inside App')
  return context
}

export default function App() {
  const [media, setMedia] = useState(initialMedia)
  const [token, setTokenState] = useState(
    () => sessionStorage.getItem('ibvap-api-token') ?? ''
  )
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [cameras, setCameras] = useState<CameraStatus[]>([])
  const [events, setEvents] = useState<AnalyticsEvent[]>([])
  const [alertActions, setAlertActions] = useState<AlertAction[]>([])
  const [apiError, setApiError] = useState('')
  const setToken = (value: string) => {
    setTokenState(value)
    if (value) sessionStorage.setItem('ibvap-api-token', value)
    else sessionStorage.removeItem('ibvap-api-token')
  }
  const seenEventsRef = useRef<Set<string>>(new Set())
  const isInitialLoadRef = useRef(true)

  const refresh = async () => {
    if (!token) {
      setApiError('Add the service API token in Settings to connect to IBVAP.')
      return
    }
    try {
      const [nextReadiness, nextCameras, nextEvents, nextAlertActions] = await Promise.all([
        api.readiness(token),
        api.cameras(token),
        api.events(token),
        api.alertActions(token),
      ])
      setReadiness(nextReadiness)
      setCameras(nextCameras)

      if (isInitialLoadRef.current) {
        nextEvents.forEach((ev) => seenEventsRef.current.add(ev.event_id))
        isInitialLoadRef.current = false
      } else {
        const newEvents = nextEvents.filter((ev) => !seenEventsRef.current.has(ev.event_id))
        if (newEvents.length > 0) {
          newEvents.forEach((ev) => seenEventsRef.current.add(ev.event_id))
          // Upload analysis announces its own summary; do not announce the
          // persisted upload events a second time from the live poller.
          const liveEvents = newEvents.filter((ev) => !ev.camera_id.startsWith('upload-') && ev.camera_id !== 'image-upload')
          const liveSuspicious = liveEvents.filter(
            (ev) => ev.event_type.includes('intrusion') || ev.event_type.includes('loiter') || ev.event_type.includes('night')
          )
          if (liveSuspicious.length === 1) {
            announceSecurityEvent(liveSuspicious[0])
          } else if (liveSuspicious.length > 1) {
            speakAlert(`Security Warning! ${liveSuspicious.length} new suspicious perimeter events detected!`, true)
          } else if (liveEvents.length === 1 && liveEvents[0].event_type === 'plate_read') {
            announceSecurityEvent(liveEvents[0])
          }
        }
      }

      setEvents(nextEvents)
      setAlertActions(nextAlertActions)
      setApiError('')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Unable to connect to the IBVAP service.')
    }
  }
  const recordAlertAction = async (eventId: string, status: AlertAction['status']) => {
    const action = await api.recordAlertAction(token, eventId, status)
    setAlertActions((current) => [action, ...current.filter((item) => item.event_id !== eventId)])
  }
  useEffect(() => {
    void refresh()
    const interval = setInterval(() => { void refresh() }, 4000)
    return () => clearInterval(interval)
  }, [token])

  const addMedia = (files: File[]) => {
    const uploaded = files.map((file, index): UploadedMedia => ({
      id: `MED-${Date.now()}-${index}`,
      name: file.name,
      kind: file.type.startsWith('video/') ? 'Video' : 'Image',
      size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
      uploadedAt: 'Just now',
      location: 'Unassigned',
      previewUrl: URL.createObjectURL(file),
      file,
    }))
    setMedia((current) => [...uploaded, ...current])
  }

  const removeMedia = (id: string) => {
    setMedia((current) => {
      const item = current.find((entry) => entry.id === id)
      if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl)
      return current.filter((entry) => entry.id !== id)
    })
  }

  const context = useMemo(() => ({ token, setToken, readiness, cameras, events, alertActions, recordAlertAction, apiError, refresh }), [token, readiness, cameras, events, alertActions, apiError])
  return <AppContext.Provider value={context}><Routes><Route element={<Layout />}><Route index element={<DashboardPage media={media} />} /><Route path="uploads" element={<MediaUploadPage media={media} onUpload={addMedia} />} /><Route path="uploads/history" element={<UploadHistoryPage media={media} onRemove={removeMedia} />} /><Route path="cameras/live" element={<CamerasPage />} /><Route path="cameras" element={<CamerasPage />} /><Route path="alerts" element={<AlertsPage />} /><Route path="reports" element={<ReportsPage />} /><Route path="settings" element={<SettingsPage />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes></AppContext.Provider>
}

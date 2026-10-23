import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, type AnalyticsEvent, type CameraStatus, type Readiness } from './api'
import { Layout } from './components/Layout'
import { AlertsPage } from './pages/AlertsPage'
import { DashboardPage } from './pages/DashboardPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'
import { MediaUploadPage, UploadHistoryPage } from './pages/UploadsPage'
import { initialMedia, type UploadedMedia } from './data'
import { CamerasPage } from './pages/CamerasPage'

type AppContextValue = {
  token: string
  setToken: (token: string) => void
  readiness: Readiness | null
  cameras: CameraStatus[]
  events: AnalyticsEvent[]
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
  const [token, setTokenState] = useState(() => sessionStorage.getItem('ibvap-api-token') ?? '')
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [cameras, setCameras] = useState<CameraStatus[]>([])
  const [events, setEvents] = useState<AnalyticsEvent[]>([])
  const [apiError, setApiError] = useState('')
  const setToken = (value: string) => {
    setTokenState(value)
    if (value) sessionStorage.setItem('ibvap-api-token', value)
    else sessionStorage.removeItem('ibvap-api-token')
  }
  const refresh = async () => {
    if (!token) {
      setApiError('Add the service API token in Settings to connect to IBVAP.')
      return
    }
    try {
      const [nextReadiness, nextCameras, nextEvents] = await Promise.all([
        api.readiness(token),
        api.cameras(token),
        api.events(token),
      ])
      setReadiness(nextReadiness)
      setCameras(nextCameras)
      setEvents(nextEvents)
      setApiError('')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Unable to connect to the IBVAP service.')
    }
  }
  useEffect(() => { void refresh() }, [token])

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

  const context = useMemo(() => ({ token, setToken, readiness, cameras, events, apiError, refresh }), [token, readiness, cameras, events, apiError])
  return <AppContext.Provider value={context}><Routes><Route element={<Layout />}><Route index element={<DashboardPage media={media} />} /><Route path="uploads" element={<MediaUploadPage media={media} onUpload={addMedia} />} /><Route path="uploads/history" element={<UploadHistoryPage media={media} onRemove={removeMedia} />} /><Route path="cameras/live" element={<CamerasPage />} /><Route path="cameras" element={<CamerasPage />} /><Route path="alerts" element={<AlertsPage />} /><Route path="reports" element={<ReportsPage />} /><Route path="settings" element={<SettingsPage />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes></AppContext.Provider>
}

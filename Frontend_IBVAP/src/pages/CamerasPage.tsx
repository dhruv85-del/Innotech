import { useState } from 'react'
import { Camera, Play, Plus, Square } from 'lucide-react'
import { api } from '../api'
import { useAppContext } from '../App'
import { PageTitle } from '../components/Primitives'

export function CamerasPage() {
  const { token, cameras, refresh, apiError } = useAppContext()
  const [cameraId, setCameraId] = useState('')
  const [source, setSource] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setMessage('')
    try { await action(); await refresh(); setMessage('Camera state updated.') }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Camera operation failed.') }
    finally { setBusy(false) }
  }
  return <div className="page">
    <PageTitle eyebrow="LIVE OPERATIONS" title="Cameras" description="Manage configured sources and control analytics processing." />
    {(apiError || message) && <p className="upload-message" role="status">{apiError || message}</p>}
    <section className="panel settings-panel">
      <div className="settings-section-heading"><div className="settings-heading-icon"><Plus size={17} /></div><div><h2>Add camera source</h2><p>Sources are stored by the local IBVAP service.</p></div></div>
      <div className="regional-fields"><label>CAMERA ID<input value={cameraId} onChange={(event) => setCameraId(event.target.value)} placeholder="north-gate" /></label><label>SOURCE<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="rtsp:// or local file path" /></label></div>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
        <button className="button button-primary" disabled={busy || !token || !cameraId || !source} onClick={() => run(() => api.createCamera(token, { camera_id: cameraId, source, analytics: ['person_vehicle', 'intrusion'], start: true }))}><Plus size={15} /> Add & Start Camera</button>
        <button type="button" className="button button-secondary" onClick={() => { setCameraId(`sim-gate-${Math.floor(Math.random() * 900 + 100)}`); setSource('samples/videos/bus-test.mp4') }}>Use Sample Video Source</button>
      </div>
    </section>
    <section className="panel table-panel"><div className="table-toolbar"><div><h2>Configured sources <span className="heading-count">{cameras.length}</span></h2><p>Runtime status from the analytics service</p></div></div><div className="table-scroll"><table><thead><tr><th>CAMERA</th><th>STATE</th><th>ANALYTICS</th><th>FPS</th><th>ACTIONS</th></tr></thead><tbody>{cameras.map((camera) => <tr key={camera.camera_id}><td><div className="table-camera"><span className={`camera-status-icon ${camera.state === 'running' ? 'online' : 'maintenance'}`}><Camera size={15} /></span><div><strong>{camera.camera_id}</strong><span>{camera.last_error ?? 'Service source'}</span></div></div></td><td>{camera.state}</td><td>{camera.analytics.join(', ') || 'None'}</td><td>{camera.process_fps}</td><td><button className="button button-small" disabled={busy} onClick={() => run(() => camera.state === 'running' ? api.stopCamera(token, camera.camera_id) : api.startCamera(token, camera.camera_id))}>{camera.state === 'running' ? <><Square size={13} /> Stop</> : <><Play size={13} /> Start</>}</button></td></tr>)}</tbody></table>{!cameras.length && <div className="table-empty">No cameras configured in the service.</div>}</div></section>
  </div>
}

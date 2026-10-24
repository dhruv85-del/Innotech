import { useMemo, useRef, useState } from 'react'
import { FileImage, FileVideo, Image, MoreHorizontal, Upload, X } from 'lucide-react'
import type { UploadedMedia } from '../data'
import { PageTitle, SearchField, SelectField } from '../components/Primitives'
import { api, type Analytics, type ImageAnalysisResult, type VideoAnalysisResult } from '../api'
import { useAppContext } from '../App'
import { speakAlert } from '../voiceAlerts'

function MediaPreview({ item, index, analysis }: { item: UploadedMedia; index: number; analysis?: AnalysisResult }) {
  if (item.previewUrl && item.kind === 'Image') {
    return (
      <div style={{ position: 'relative', width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#090e17' }}>
        <img className="media-real-preview" src={item.previewUrl} alt={item.name} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        {analysis?.kind === 'image' && analysis.result.detections.length > 0 && (
          <svg
            viewBox={`0 0 ${analysis.result.image_width} ${analysis.result.image_height}`}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
          >
            {analysis.result.detections.map((detection, dIdx) => {
              const box = detection.bounding_box
              const x = box.x * analysis.result.image_width
              const y = box.y * analysis.result.image_height
              const w = box.width * analysis.result.image_width
              const h = box.height * analysis.result.image_height
              const isPerson = detection.class_name === 'person'
              const isPlate = detection.class_name.includes('plate')
              const isFace = detection.class_name === 'face'
              const strokeColor = isPerson ? '#00e5ff' : isFace ? '#ffea00' : isPlate ? '#d500f9' : '#00e676'
              const label = `${detection.class_name}${detection.confidence ? ` ${(detection.confidence * 100).toFixed(0)}%` : ''}${detection.plate_text ? ` [${detection.plate_text}]` : ''}`
              const fontSize = Math.max(12, Math.round(analysis.result.image_width * 0.024))
              return (
                <g key={dIdx}>
                  <rect
                    x={x}
                    y={y}
                    width={w}
                    height={h}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth={Math.max(2, Math.round(analysis.result.image_width * 0.004))}
                  />
                  <rect
                    x={x}
                    y={Math.max(0, y - fontSize - 6)}
                    width={Math.round(label.length * (fontSize * 0.62) + 10)}
                    height={fontSize + 6}
                    fill={strokeColor}
                    rx="3"
                  />
                  <text
                    x={x + 5}
                    y={Math.max(fontSize, y - 4)}
                    fill="#000000"
                    fontSize={fontSize}
                    fontWeight="bold"
                    fontFamily="monospace"
                  >
                    {label}
                  </text>
                </g>
              )
            })}
          </svg>
        )}
      </div>
    )
  }
  if (item.previewUrl && item.kind === 'Video') return <video className="media-real-preview" src={item.previewUrl} controls preload="metadata" aria-label={`Preview ${item.name}`} />
  return <div className={`media-placeholder media-placeholder-${index % 4}`}>
    <div className="media-placeholder-lines" />
    {item.kind === 'Video' ? <FileVideo size={28} /> : <FileImage size={28} />}
    <span>{item.kind === 'Video' ? 'VIDEO FILE' : 'IMAGE FILE'}</span>
    {item.duration && <b>{item.duration}</b>}
  </div>
}

type AnalysisResult = { kind: 'image'; result: ImageAnalysisResult } | { kind: 'video'; result: VideoAnalysisResult }

const capabilityNames: Record<string, string> = {
  person_vehicle: 'People and vehicles',
  face: 'Faces',
  anpr: 'License plates and OCR',
  intrusion: 'Restricted-zone intrusion',
  loitering: 'Loitering',
  night_movement: 'Night movement',
}

export function MediaUploadPage({ media, onUpload }: { media: UploadedMedia[]; onUpload: (files: File[]) => void }) {
  const { token, refresh, readiness } = useAppContext()
  const inputRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState('All media')
  const [isDragging, setIsDragging] = useState(false)
  const [message, setMessage] = useState('')
  const [analyzing, setAnalyzing] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, AnalysisResult>>({})
  const filtered = useMemo(() => media.filter((item) => `${item.name} ${item.location}`.toLowerCase().includes(search.toLowerCase()) && (kind === 'All media' || item.kind === kind.slice(0, -1))), [media, search, kind])

  const acceptFiles = (files: FileList | File[]) => {
    const supported: File[] = []
    let rejected = 0
    Array.from(files).forEach((file) => {
      if (file.type.startsWith('video/') || file.type.startsWith('image/')) supported.push(file)
      else rejected += 1
    })
    if (supported.length) {
      onUpload(supported)
      setMessage(`${supported.length} file${supported.length === 1 ? '' : 's'} added to this session${rejected ? ` · ${rejected} unsupported file${rejected === 1 ? '' : 's'} skipped` : ''}.`)
    } else if (rejected) {
      setMessage('Only image and video files can be uploaded.')
    }
    if (inputRef.current) inputRef.current.value = ''
  }

  const analyze = async (item: UploadedMedia) => {
    if (!item.file || !token) {
      setMessage('Add the service API token in Settings before analyzing media.')
      return
    }
    const analytics: Analytics[] = []
    if (readiness?.capabilities.person_vehicle) analytics.push('person_vehicle')
    if (readiness?.capabilities.face) analytics.push('face')
    if (readiness?.capabilities.anpr) analytics.push('anpr')
    if (item.kind === 'Video' && readiness?.capabilities.person_vehicle) {
      analytics.push('intrusion', 'loitering', 'night_movement')
    }
    if (!analytics.length) {
      setMessage('No analytics capability is ready. Configure a model or face cascade, then restart the backend.')
      return
    }
    setAnalyzing(item.id)
    try {
      if (item.kind === 'Video') {
        const result = await api.analyzeVideo(token, item.file, analytics)
        setResults((current) => ({ ...current, [item.id]: { kind: 'video', result } }))
        setMessage(`${item.name}: analysis complete. ${result.events.length} alert${result.events.length === 1 ? '' : 's'} generated from ${result.frames_analyzed} analyzed frames.`)
        if (result.events.length > 0) {
          const intrusions = result.events.filter((ev) => ev.event_type.includes('intrusion')).length
          if (intrusions > 0) {
            speakAlert(`Warning! Perimeter intrusion detected in analyzed video. ${intrusions} security alert${intrusions === 1 ? '' : 's'} recorded.`, true)
          } else {
            speakAlert(`Video analysis complete. ${result.events.length} security alert${result.events.length === 1 ? '' : 's'} detected.`, true)
          }
        } else {
          speakAlert(`Video analysis complete. No suspicious events detected in this clip.`, false)
        }
      } else {
        const imageAnalytics = analytics.filter((entry): entry is 'person_vehicle' | 'face' | 'anpr' => ['person_vehicle', 'face', 'anpr'].includes(entry))
        const result = await api.analyzeImage(token, item.file, imageAnalytics)
        setResults((current) => ({ ...current, [item.id]: { kind: 'image', result } }))
        setMessage(`${item.name}: analysis complete. ${result.detections.length} detection${result.detections.length === 1 ? '' : 's'} returned and report created.`)
        if (result.detections.length > 0) {
          speakAlert(`Image analysis complete. ${result.detections.length} object${result.detections.length === 1 ? '' : 's'} detected.`, false)
        } else {
          speakAlert('Image analysis complete. No objects detected.', false)
        }
      }
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Media analysis failed. Check the service connection and token.')
    } finally {
      setAnalyzing(null)
    }
  }
  const downloadImageReport = async (reportId: string) => {
    try {
      const blob = await api.imageReport(token, reportId)
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `ibvap-image-report-${reportId}.html`
      link.click()
      URL.revokeObjectURL(link.href)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Image report download failed.')
    }
  }
  const downloadVideoReport = async (reportId: string) => {
    try {
      const blob = await api.videoReport(token, reportId)
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `ibvap-video-report-${reportId}.html`
      link.click()
      URL.revokeObjectURL(link.href)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Video report download failed.')
    }
  }
  return <div className="page">
    <PageTitle eyebrow="MEDIA WORKSPACE" title="Upload media" description="Add video clips and images for review. Images can be analyzed by the IBVAP service." action={<span className="local-only-badge">SESSION LIBRARY</span>} />
    <section className={`upload-dropzone${isDragging ? ' upload-dropzone-active' : ''}`} onDragOver={(event) => { event.preventDefault(); setIsDragging(true) }} onDragLeave={() => setIsDragging(false)} onDrop={(event) => { event.preventDefault(); setIsDragging(false); acceptFiles(event.dataTransfer.files) }}>
      <input ref={inputRef} id="media-file-input" className="file-input-hidden" type="file" accept="image/*,video/*" multiple onChange={(event) => { if (event.target.files) acceptFiles(event.target.files) }} />
      <div className="upload-icon"><Upload size={21} /></div>
      <div className="upload-copy"><strong>Upload videos and images</strong><span>Drag and drop files here, or <label htmlFor="media-file-input">browse your device</label></span><small>Images and videos · Files remain in this browser session</small></div>
      <label className="button button-primary upload-browse" htmlFor="media-file-input">Choose files</label>
    </section>
    {message && <p className="upload-message" role="status">{message}</p>}
    <div className="media-library-heading"><div><h2>Your media <span className="heading-count">{media.length}</span></h2><p>Uploaded files available in this session</p></div><div className="toolbar-left"><SearchField value={search} onChange={setSearch} placeholder="Search files..." /><SelectField value={kind} onChange={setKind} options={['All media', 'Videos', 'Images']} ariaLabel="Filter uploaded media by type" /></div></div>
    {filtered.length ? <div className="media-grid">{filtered.map((item, index) => {
      const analysis = results[item.id]
      return <article className="media-card" key={item.id}><div className="media-card-preview"><MediaPreview item={item} index={index} analysis={analysis} /><span className="media-kind-badge">{item.kind === 'Video' ? <FileVideo size={12} /> : <Image size={12} />}{item.kind}</span><button className="media-more icon-button" aria-label={`Options for ${item.name}`}><MoreHorizontal size={18} /></button></div><div className="media-card-info"><strong title={item.name}>{item.name}</strong><span>{item.size}{item.duration ? ` · ${item.duration}` : ''}</span><div className="media-card-meta"><span>{item.location}</span><span>{item.uploadedAt}</span></div>{item.file && <button className="button button-small" disabled={analyzing === item.id} onClick={() => void analyze(item)}>{analyzing === item.id ? 'Analyzing…' : `Analyze ${item.kind.toLowerCase()}`}</button>}{analysis?.kind === 'image' && <div className="analysis-result" role="status">      <strong>Image analysis complete</strong><span>Activities: {analysis.result.activity_predictions.length ? analysis.result.activity_predictions.map((prediction) => prediction.activity.replace(/_/g, ' ')).join(', ') : 'No supported activity pattern'}</span><span>Capabilities: {analysis.result.analytics.map((entry) => capabilityNames[entry] ?? entry).join(', ')}</span><span>{analysis.result.image_width} × {analysis.result.image_height}px</span>{analysis.result.detections.length ? analysis.result.detections.map((detection, detectionIndex) => <span key={`${detection.class_name}-${detectionIndex}`}>{detection.class_name}{detection.plate_text ? ` · plate ${detection.plate_text} · OCR confidence ${detection.ocr_confidence === null ? 'n/a' : `${(detection.ocr_confidence * 100).toFixed(1)}%`}` : ''} · detection confidence {detection.confidence === null ? 'n/a' : `${(detection.confidence * 100).toFixed(1)}%`}</span>) : <span>No people, vehicles, faces, or plates detected.</span>}{analysis.result.report_id && <button className="button button-small" onClick={() => void downloadImageReport(analysis.result.report_id as string)}>Download detailed report</button>}</div>}{analysis?.kind === 'video' && <div className="analysis-result" role="status"><strong>Video analysis complete</strong><span>Frames analyzed: {analysis.result.frames_analyzed}</span><span>Activities: {analysis.result.activity_predictions.length ? analysis.result.activity_predictions.map((prediction) => prediction.activity.replace(/_/g, ' ')).join(', ') : 'No supported activity pattern'}</span><span>Capabilities: People/vehicles, faces, plates, intrusion, loitering, night movement</span>{analysis.result.events.length ? analysis.result.events.map((event) => <span key={event.event_id}>{event.event_type.replace(/_/g, ' ')} · {event.object?.class_name ?? 'activity'} · {event.event_type === 'plate_read' ? `vehicle number: ${event.details.plate_text ?? 'Vehicle number not captured'} · OCR confidence: ${typeof event.details.ocr_confidence === 'number' ? `${(event.details.ocr_confidence * 100).toFixed(1)}%` : 'Not available'} · ` : ''}{new Date(event.occurred_at).toLocaleTimeString()}</span>) : <span>No alerts detected in this video clip.</span>}{analysis.result.report_id && <button className="button button-small" onClick={() => void downloadVideoReport(analysis.result.report_id as string)}>Download video report</button>}</div>}</div></article>
    })}</div> : <div className="empty-state"><Image size={28} /><strong>No media found</strong><span>Choose a video or image to begin analysis.</span></div>}
  </div>
}

export function UploadHistoryPage({ media, onRemove }: { media: UploadedMedia[]; onRemove: (id: string) => void }) {
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState('All types')
  const filtered = useMemo(() => media.filter((item) => `${item.name} ${item.location} ${item.id}`.toLowerCase().includes(search.toLowerCase()) && (kind === 'All types' || item.kind === kind.slice(0, -1))), [media, search, kind])
  return <div className="page">
    <PageTitle eyebrow="MEDIA WORKSPACE" title="Upload history" description="Browse and manage videos and images added to this session." action={<span className="local-only-badge">LOCAL SESSION ONLY</span>} />
    <section className="stats-grid compact-stats"><article className="stat-card compact-stat"><span className="stat-label">Total files</span><strong>{media.length.toString().padStart(2, '0')}</strong><span className="compact-stat-note">Available this session</span></article><article className="stat-card compact-stat"><span className="stat-label">Videos</span><strong className="cyan-text">{media.filter((item) => item.kind === 'Video').length.toString().padStart(2, '0')}</strong><span className="compact-stat-note">Uploaded video clips</span></article><article className="stat-card compact-stat"><span className="stat-label">Images</span><strong className="green-text">{media.filter((item) => item.kind === 'Image').length.toString().padStart(2, '0')}</strong><span className="compact-stat-note">Uploaded still images</span></article><article className="stat-card compact-stat"><span className="stat-label">Storage</span><strong className="amber-text">Session</strong><span className="compact-stat-note">Not stored on a server</span></article></section>
    <section className="panel table-panel"><div className="table-toolbar"><div><h2>All uploads <span className="heading-count">{filtered.length}</span></h2><p>Files uploaded during this browser session</p></div><div className="toolbar-left"><SearchField value={search} onChange={setSearch} placeholder="Search files..." /><SelectField value={kind} onChange={setKind} options={['All types', 'Videos', 'Images']} ariaLabel="Filter uploads by type" /></div></div><div className="table-scroll"><table><thead><tr><th>FILE</th><th>TYPE</th><th>SIZE</th><th>LOCATION</th><th>UPLOADED</th><th aria-label="Actions" /></tr></thead><tbody>{filtered.map((item) => <tr key={item.id}><td><div className="table-camera"><span className={`camera-status-icon ${item.kind === 'Video' ? 'online' : 'maintenance'}`}>{item.kind === 'Video' ? <FileVideo size={15} /> : <FileImage size={15} />}</span><div><strong>{item.name}</strong><span>{item.id}</span></div></div></td><td>{item.kind}</td><td>{item.size}</td><td>{item.location}</td><td className="last-seen">{item.uploadedAt}</td><td><button className="icon-button table-more" aria-label={`Remove ${item.name}`} title="Remove file from this session" onClick={() => onRemove(item.id)}><X size={16} /></button></td></tr>)}</tbody></table>{filtered.length === 0 && <div className="table-empty">No uploads match your search.</div>}</div><div className="table-footer"><span>Showing {filtered.length} of {media.length} files</span><span>Files are available only in this browser session</span></div></section>
  </div>
}

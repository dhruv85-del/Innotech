import { useState } from 'react'
import { ArrowRight, ArrowUpRight, Clock3, FileVideo, Image, ShieldAlert, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import { activity, type UploadedMedia } from '../data'
import { PageTitle, StatCard, StatusBadge } from '../components/Primitives'
import { useAppContext } from '../App'

const alertColors: Record<string, string> = { Critical: 'alert-marker-critical', High: 'alert-marker-high', Medium: 'alert-marker-medium', Low: 'alert-marker-low' }

function ActivityChart() {
  const points = activity.length > 1
    ? activity.map((value, index) => `${index * (300 / (activity.length - 1))},${100 - value}`).join(' ')
    : '0,100 300,100'
  return <div className="chart-wrap">
    <div className="chart-y-labels"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
    <div className="chart-main">
      <div className="chart-grid"><i /><i /><i /><i /><i /></div>
      <svg className="activity-chart" viewBox="0 0 300 100" preserveAspectRatio="none" role="img" aria-label="Daily upload activity chart"><defs><linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#34c8d4" stopOpacity=".2" /><stop offset="100%" stopColor="#34c8d4" stopOpacity="0" /></linearGradient></defs><polygon points={`0,100 ${points} 300,100`} fill="url(#areaFill)" /><polyline points={points} fill="none" stroke="#39c3d1" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" /></svg>
      <div className="chart-x-labels"><span>00:00</span><span>04:00</span><span>08:00</span><span>12:00</span><span>16:00</span><span>20:00</span><span>24:00</span></div>
    </div>
  </div>
}

function UploadSummary({ media }: { media: UploadedMedia[] }) {
  const videos = media.filter((item) => item.kind === 'Video').length
  const images = media.filter((item) => item.kind === 'Image').length
  return <div className="upload-summary-content">
    <div className="upload-summary-total"><div><span>FILES IN THIS SESSION</span><strong>{media.length.toString().padStart(2, '0')}</strong></div><Link to="/uploads" className="summary-upload-button"><Upload size={15} /> Upload files</Link></div>
    <div className="upload-breakdown"><div className="upload-breakdown-row"><span className="upload-type-icon video-type"><FileVideo size={16} /></span><div><strong>Videos</strong><span>Uploaded clips</span></div><b>{videos.toString().padStart(2, '0')}</b></div><div className="upload-breakdown-row"><span className="upload-type-icon image-type"><Image size={16} /></span><div><strong>Images</strong><span>Uploaded stills</span></div><b>{images.toString().padStart(2, '0')}</b></div></div>
    <div className="upload-session-note"><span className="health-dot" /> Files stay in this browser session and are not sent to a server.</div>
  </div>
}

export function DashboardPage({ media }: { media: UploadedMedia[] }) {
  const { cameras, events, readiness } = useAppContext()
  const [range, setRange] = useState('Last 24 hours')
  const recentMedia = media.slice(0, 4)
  const recentEvents = events.slice(0, 4)
  const today = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(new Date())
  const greeting = new Intl.DateTimeFormat(undefined, { hour: 'numeric', hour12: false }).format(new Date())
  const hour = Number(greeting)
  const salutation = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  return <div className="page">
    <PageTitle eyebrow={today.toUpperCase()} title={`${salutation}, Jordan`} description="Review uploaded videos, images, and flagged items in your workspace." action={<button className="button button-secondary" onClick={() => setRange(range === 'Last 24 hours' ? 'Last 7 days' : 'Last 24 hours')}><Clock3 size={15} />{range}<span className="button-caret">⌄</span></button>} />
    <section className="stats-grid">
      <StatCard label="Uploaded media" value={media.length.toString().padStart(2, '0')} icon={<Upload size={18} />} tone="cyan" note="Available in this session" />
      <StatCard label="Videos" value={media.filter((item) => item.kind === 'Video').length.toString().padStart(2, '0')} icon={<FileVideo size={18} />} tone="green" note="Uploaded video clips" />
      <StatCard label="Images" value={media.filter((item) => item.kind === 'Image').length.toString().padStart(2, '0')} icon={<Image size={18} />} tone="amber" note="Uploaded still images" />
      <StatCard label="Service events" value={events.length.toString().padStart(2, '0')} icon={<ShieldAlert size={18} />} tone="red" note={`${cameras.length} cameras · ${readiness?.status ?? 'not connected'}`} />
    </section>
    <section className="dashboard-grid">
      <article className="panel activity-panel">
        <div className="panel-heading"><div><h2>Upload activity</h2><p>Files added to the workspace over time</p></div><div className="panel-heading-side"><span className="chart-legend"><i /> Uploads</span><button className="icon-button small-more" aria-label="Upload chart options">···</button></div></div>
        <div className="chart-summary"><strong>{media.length}</strong><span className="muted-text">files in this session</span></div>
        <ActivityChart />
      </article>
      <article className="panel map-panel upload-summary-panel">
        <div className="panel-heading"><div><h2>Media overview</h2><p>Files added to this session</p></div><Link to="/uploads/history" className="text-link">History <ArrowRight size={14} /></Link></div>
        <UploadSummary media={media} />
      </article>
    </section>
    <section className="dashboard-grid lower-grid">
      <article className="panel alerts-panel">
        <div className="panel-heading"><div><h2>Recent alerts <span className="heading-count">{events.length}</span></h2><p>Flagged items for manual review</p></div><Link to="/alerts" className="text-link">View all <ArrowRight size={14} /></Link></div>
        <div className="recent-alerts">{recentEvents.map((event) => {
          const severity = event.event_type.includes('intrusion') ? 'Critical' : 'Medium'
          return <div className="recent-alert" key={event.event_id}><span className={`alert-marker ${alertColors[severity]}`}><ShieldAlert size={15} /></span><div className="recent-alert-content"><div className="alert-title-row"><strong>{event.event_type.replace(/_/g, ' ')}</strong><StatusBadge status={severity} /></div><p>{event.camera_id} <span>·</span> {new Date(event.occurred_at).toLocaleString()}</p></div><ArrowUpRight size={15} className="alert-open-icon" /></div>
        })}</div>
        {!recentEvents.length && <div className="table-empty">No service events yet.</div>}
      </article>
      <article className="panel camera-status-panel recent-uploads-panel">
        <div className="panel-heading"><div><h2>Recent uploads</h2><p>Latest videos and images</p></div><Link to="/uploads" className="text-link">View all <ArrowRight size={14} /></Link></div>
        <div className="camera-status-list">{recentMedia.map((item) => <div className="camera-status-row" key={item.id}><span className={`camera-status-icon ${item.kind === 'Video' ? 'online' : 'maintenance'}`}>{item.kind === 'Video' ? <FileVideo size={15} /> : <Image size={15} />}</span><div className="camera-status-info"><strong>{item.name}</strong><span>{item.kind} · {item.uploadedAt}</span></div></div>)}</div>
        <Link to="/uploads" className="camera-status-footer"><span><Upload size={13} /> Add media to this session</span><span>Upload <ArrowRight size={12} /></span></Link>
      </article>
    </section>
  </div>
}

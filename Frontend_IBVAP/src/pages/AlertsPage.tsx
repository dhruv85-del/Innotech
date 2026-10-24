import { useMemo, useState } from 'react'
import { Check, CheckCheck, Filter, ShieldAlert, Trash2 } from 'lucide-react'
import type { AlertItem } from '../data'
import { useAppContext } from '../App'
import { PageTitle, SearchField, SelectField, StatusBadge } from '../components/Primitives'

export function AlertsPage() {
  const { events, alertActions, recordAlertAction } = useAppContext()
  const alerts: AlertItem[] = events.map((event) => ({
    id: event.event_id,
    title: event.event_type.replace(/_/g, ' '),
    detail: `Detected ${event.object?.class_name ?? 'activity'} by the IBVAP analytics service`,
    media: String(event.details.filename ?? event.camera_id),
    location: event.camera_id,
    time: new Date(event.occurred_at).toLocaleString(),
    severity: event.event_type.includes('intrusion') ? 'Critical' : 'Medium',
    status: alertActions.find((action) => action.event_id === event.event_id)?.status ?? 'New',
  }))
  const [search, setSearch] = useState('')
  const [severity, setSeverity] = useState('All severity')
  const [status, setStatus] = useState('All alerts')
  const filtered = useMemo(() => alerts.filter((alert) => `${alert.title} ${alert.media} ${alert.location}`.toLowerCase().includes(search.toLowerCase()) && (severity === 'All severity' || alert.severity === severity) && (status === 'All alerts' || alert.status === status)), [alerts, search, severity, status])
  const updateAlert = async (id: string, nextStatus: AlertItem['status']) => {
    if (nextStatus === 'Acknowledged' || nextStatus === 'Dismissed') await recordAlertAction(id, nextStatus)
  }
  const dismissAll = () => Promise.all(alerts.filter((alert) => alert.status === 'New').map((alert) => recordAlertAction(alert.id, 'Dismissed')))
  return <div className="page">
    <PageTitle eyebrow="MANUAL REVIEW" title="Alerts" description="Review flagged items linked to uploaded videos and images." action={<button className="button button-secondary" onClick={dismissAll}><CheckCheck size={15} /> Clear new alerts</button>} />
    <section className="stats-grid compact-stats alert-stats"><article className="stat-card compact-stat"><span className="stat-label">New alerts</span><strong className="red-text">{alerts.filter((alert) => alert.status === 'New').length.toString().padStart(2, '0')}</strong><span className="compact-stat-note">Require your attention</span></article><article className="stat-card compact-stat"><span className="stat-label">Critical & high</span><strong className="amber-text">{alerts.filter((alert) => ['Critical', 'High'].includes(alert.severity) && alert.status !== 'Dismissed').length.toString().padStart(2, '0')}</strong><span className="compact-stat-note">Priority incidents</span></article><article className="stat-card compact-stat"><span className="stat-label">Acknowledged</span><strong className="cyan-text">{alerts.filter((alert) => alert.status === 'Acknowledged').length.toString().padStart(2, '0')}</strong><span className="compact-stat-note">Being investigated</span></article><article className="stat-card compact-stat"><span className="stat-label">Dismissed</span><strong>{alerts.filter((alert) => alert.status === 'Dismissed').length.toString().padStart(2, '0')}</strong><span className="compact-stat-note">Closed alerts</span></article></section>
    <section className="panel alert-list-panel"><div className="table-toolbar"><div><h2>Flagged items <span className="heading-count">{filtered.length}</span></h2><p>Items associated with uploaded media</p></div><div className="toolbar-left"><SearchField value={search} onChange={setSearch} placeholder="Search alerts..." /><SelectField value={severity} onChange={setSeverity} options={['All severity', 'Critical', 'High', 'Medium', 'Low']} ariaLabel="Filter by severity" /><SelectField value={status} onChange={setStatus} options={['All alerts', 'New', 'Acknowledged', 'Dismissed']} ariaLabel="Filter by alert status" /></div></div>
      <div className="alert-list">{filtered.map((alert) => <article className={`alert-row ${alert.status === 'New' ? 'alert-row-new' : ''}`} key={alert.id}><div className={`alert-row-icon severity-${alert.severity.toLowerCase()}`}><ShieldAlert size={18} /></div><div className="alert-row-main"><div className="alert-row-title"><h3>{alert.title}</h3><StatusBadge status={alert.severity} /><StatusBadge status={alert.status} /></div><p>{alert.detail}</p><div className="alert-row-meta"><span>{alert.media}</span><span>·</span><span>{alert.location}</span><span>·</span><span>{alert.time}</span><span className="alert-id">{alert.id}</span></div></div><div className="alert-actions">{alert.status === 'New' && <button className="button button-small button-ack" onClick={() => updateAlert(alert.id, 'Acknowledged')}><Check size={14} /> Acknowledge</button>}{alert.status !== 'Dismissed' && <button className="icon-button dismiss-button" title="Dismiss alert" aria-label={`Dismiss ${alert.id}`} onClick={() => updateAlert(alert.id, 'Dismissed')}><Trash2 size={15} /></button>}{alert.status === 'Dismissed' && <span className="dismissed-label">Dismissed</span>}</div></article>)}
      {filtered.length === 0 && <div className="empty-state"><Filter size={26} /><strong>No matching alerts</strong><span>Try another search or filter.</span></div>}</div>
      <div className="table-footer"><span>Showing {filtered.length} of {alerts.length} alerts</span><span><span className="health-dot" /> Alerts updated just now</span></div>
    </section>
  </div>
}

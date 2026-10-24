import { useMemo, useState } from 'react'
import { ArrowDownToLine, CalendarDays, FileBarChart2, Image, ShieldCheck, TrendingUp } from 'lucide-react'
import { useAppContext } from '../App'
import { PageTitle, SelectField, StatCard } from '../components/Primitives'

export function ReportsPage() {
  const { events, alertActions } = useAppContext()
  const [period, setPeriod] = useState('Last 7 days')
  const reportEvents = useMemo(() => {
    const durationMs = period === 'Last 24 hours' ? 24 * 60 * 60 * 1000 : period === 'Last 30 days' ? 30 * 24 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000
    const cutoff = Date.now() - durationMs
    return events.filter((event) => new Date(event.occurred_at).getTime() >= cutoff)
  }, [events, period])
  const statusFor = (eventId: string) => alertActions.find((action) => action.event_id === eventId)?.status ?? 'New'
  const severityFor = (eventType: string) => eventType.includes('intrusion') ? 'Critical' : eventType.includes('loiter') || eventType.includes('night') ? 'High' : 'Medium'
  const exportReport = () => {
    const rows = [[
      'Event ID', 'Event type', 'Severity', 'Status', 'Camera/source', 'Object',
      'Confidence', 'Vehicle number', 'OCR confidence', 'Zone', 'Occurred at', 'Details',
    ], ...reportEvents.map((event) => [
      event.event_id,
      event.event_type,
      severityFor(event.event_type),
      statusFor(event.event_id),
      String(event.details.filename ?? event.camera_id),
      event.object?.class_name ?? 'activity',
      event.object?.confidence == null ? '' : String(event.object.confidence),
      String(event.details.plate_text ?? 'Vehicle number not captured'),
      event.details.ocr_confidence == null ? '' : String(event.details.ocr_confidence),
      event.zone_id ?? '',
      event.occurred_at,
      Object.entries(event.details).map(([key, value]) => `${key}=${value ?? ''}`).join('; '),
    ])]
    const csv = rows.map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `ibvap-alert-report-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }
  return <div className="page">
    <PageTitle eyebrow="INSIGHTS & HISTORY" title="Reports" description="Review uploaded media and manually flagged items." action={<button className="button button-secondary" onClick={exportReport}><ArrowDownToLine size={15} /> Export report</button>} />
    <div className="report-toolbar"><div className="report-period"><CalendarDays size={16} /><span>Reporting period</span><SelectField value={period} onChange={setPeriod} options={['Last 24 hours', 'Last 7 days', 'Last 30 days']} ariaLabel="Reporting period" /></div><span className="report-date">{reportEvents.length} alert events included</span></div>
    <section className="stats-grid">
      <StatCard label="Alert events" value={reportEvents.length.toString().padStart(2, '0')} icon={<Image size={18} />} tone="cyan" note="Included in this report" />
      <StatCard label="Acknowledged" value={reportEvents.filter((event) => statusFor(event.event_id) === 'Acknowledged').length.toString().padStart(2, '0')} icon={<FileBarChart2 size={18} />} tone="green" note="Reviewed by an officer" />
      <StatCard label="Still new" value={reportEvents.filter((event) => statusFor(event.event_id) === 'New').length.toString().padStart(2, '0')} icon={<TrendingUp size={18} />} tone="amber" note="Needs operator review" />
      <StatCard label="Intrusions" value={reportEvents.filter((event) => event.event_type.includes('intrusion')).length.toString().padStart(2, '0')} icon={<ShieldCheck size={18} />} tone="red" note="Restricted-zone events" />
    </section>
    <section className="dashboard-grid reports-main-grid">
      <article className="panel report-chart-panel"><div className="panel-heading"><div><h2>Alert report</h2><p>Detailed events and officer review status</p></div></div><div className="empty-state"><FileBarChart2 size={26} /><strong>{reportEvents.length ? `${reportEvents.length} events available` : 'No alert events in this period'}</strong><span>Use Export report to download the detailed CSV.</span></div></article>
      <article className="panel severity-panel"><div className="panel-heading"><div><h2>Report contents</h2><p>Included in the download</p></div></div><div className="empty-state"><ShieldCheck size={26} /><strong>Operational details</strong><span>Event ID, severity, status, source, object, confidence, zone, time, and detector details.</span></div></article>
    </section>
    <section className="panel report-table-panel"><div className="table-toolbar"><div><h2>Alert details</h2><p>Events persisted by the IBVAP service for the selected period</p></div></div><div className="table-scroll"><table><thead><tr><th>EVENT</th><th>SEVERITY</th><th>STATUS</th><th>SOURCE</th><th>OBJECT</th><th>PLATE</th><th>ZONE</th><th>TIME</th></tr></thead><tbody>{reportEvents.slice(0, 50).map((event) => <tr key={event.event_id}><td>{event.event_type.replace(/_/g, ' ')}</td><td>{severityFor(event.event_type)}</td><td>{statusFor(event.event_id)}</td><td>{String(event.details.filename ?? event.camera_id)}</td><td>{event.object?.class_name ?? 'activity'}{event.object?.confidence != null ? ` (${Math.round(event.object.confidence * 100)}%)` : ''}</td><td>{String(event.details.plate_text ?? '—')}</td><td>{event.zone_id ?? '—'}</td><td className="last-seen">{new Date(event.occurred_at).toLocaleString()}</td></tr>)}</tbody></table>{!reportEvents.length && <div className="table-empty">No events to report in this period.</div>}</div></section>
  </div>
}

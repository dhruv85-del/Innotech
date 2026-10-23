import type { ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight, ChevronDown, Search } from 'lucide-react'
import type { AlertItem } from '../data'

export function PageTitle({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="page-title">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {action && <div className="title-action">{action}</div>}
    </div>
  )
}

export function StatusBadge({ status }: { status: AlertItem['severity'] | AlertItem['status'] }) {
  const className = status.toLowerCase().replace(/\s/g, '-')
  return <span className={`badge badge-${className}`}><span className="badge-dot" />{status}</span>
}

export function StatCard({ label, value, change, icon, tone = 'cyan', note }: { label: string; value: string; change?: string; icon: ReactNode; tone?: string; note?: string }) {
  const isDown = change?.startsWith('-')
  return (
    <article className="stat-card">
      <div className="stat-top">
        <span className="stat-label">{label}</span>
        <span className={`stat-icon tone-${tone}`}>{icon}</span>
      </div>
      <div className="stat-value-row"><strong>{value}</strong>{change && <span className={`stat-change ${isDown ? 'change-down' : 'change-up'}`}>{isDown ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}{change}</span>}</div>
      <p className="stat-note">{note ?? 'vs. previous 24 hours'}</p>
    </article>
  )
}

export function SearchField({ value, onChange, placeholder = 'Search...' }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="search-field"><Search size={16} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} aria-label={placeholder} /></label>
}

export function SelectField({ value, onChange, options, ariaLabel }: { value: string; onChange: (value: string) => void; options: string[]; ariaLabel: string }) {
  return <label className="select-field"><select aria-label={ariaLabel} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option}>{option}</option>)}</select><ChevronDown size={15} /></label>
}

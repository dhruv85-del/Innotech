import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Activity, AlertTriangle, Bell, ChevronDown, Command, FileBarChart2, Images, LayoutDashboard, Menu, Settings, Shield, Upload, X } from 'lucide-react'
import { useAppContext } from '../App'

const navigation = [
  { label: 'Overview', path: '/', icon: LayoutDashboard },
  { label: 'Cameras', path: '/cameras', icon: Activity },
  { label: 'Upload media', path: '/uploads', icon: Upload },
  { label: 'Alerts', path: '/alerts', icon: AlertTriangle },
  { label: 'Upload history', path: '/uploads/history', icon: Images },
  { label: 'Reports', path: '/reports', icon: FileBarChart2 },
]

const pageNames: Record<string, string> = {
  '/': 'Overview',
  '/cameras': 'Cameras',
  '/cameras/live': 'Cameras',
  '/uploads': 'Upload media',
  '/uploads/history': 'Upload history',
  '/alerts': 'Alerts',
  '/reports': 'Reports',
  '/settings': 'Settings',
}

export function Layout() {
  const { apiError } = useAppContext()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const pageName = pageNames[location.pathname] ?? 'Overview'
  const sidebarClass = mobileOpen ? 'sidebar sidebar-open' : 'sidebar'

  return (
    <div className="app-shell">
      {mobileOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <aside className={sidebarClass}>
        <div className="brand">
          <div className="brand-mark"><Shield size={19} strokeWidth={2.2} /></div>
          <div><span className="brand-name">IBVAP</span><span className="brand-sub">BORDER OPERATIONS</span></div>
          <button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <div className="workspace-switch"><div className="workspace-icon"><Command size={16} /></div><div><span className="workspace-label">Media workspace</span><span className="workspace-sub">Northern command</span></div><ChevronDown size={15} className="muted-icon" /></div>
        <div className="nav-section-label">WORKSPACE</div>
        <nav className="nav-list" aria-label="Main navigation">
          {navigation.map(({ label, path, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}><Icon size={18} strokeWidth={1.8} /><span>{label}</span></NavLink>)}
        </nav>
        <div className="nav-section-label system-label">SYSTEM</div>
        <NavLink to="/settings" onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}><Settings size={18} strokeWidth={1.8} /><span>Settings</span></NavLink>
        <div className="sidebar-spacer" />
        <div className="system-health"><div className="health-heading"><span className="health-dot" /> IBVAP service</div><span>{apiError ? 'Connection needs attention' : 'Connected to local service'}</span></div>
        <div className="profile-row"><div className="avatar">JD</div><div className="profile-info"><span>Jordan Davis</span><span>Duty officer</span></div><ChevronDown size={15} className="muted-icon" /></div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={20} /></button><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{pageName}</strong></div></div>
          <div className="topbar-right"><div className="command-status"><span className="health-dot" /> Local workspace <ChevronDown size={13} /></div><span className="topbar-divider" /><button className="icon-button notification-button" aria-label="Notifications"><Bell size={18} /><i /></button><div className="topbar-time"><span>LOCAL TIME</span><strong>14:32:08</strong></div></div>
        </header>
        <main className="main-content">{apiError && <div className="service-banner" role="status"><span className="health-dot" /> {apiError}</div>}<Outlet /></main>
        <footer className="app-footer"><span><Activity size={13} /> IBVAP <span className="footer-separator">·</span> Analytics workspace</span><span>Local service <span className="footer-separator">·</span> Session media is not retained by the UI</span></footer>
      </div>
    </div>
  )
}

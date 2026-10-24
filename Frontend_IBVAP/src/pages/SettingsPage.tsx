import { useState } from 'react'
import { Bell, Check, Globe2, Monitor, Moon, Upload, Volume2 } from 'lucide-react'
import { PageTitle } from '../components/Primitives'
import { useAppContext } from '../App'
import { isSoundEnabled, setSoundEnabled, speakAlert } from '../voiceAlerts'

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return <button className={`toggle ${checked ? 'toggle-on' : ''}`} role="switch" aria-checked={checked} aria-label={label} onClick={onChange}><i /></button>
}

export function SettingsPage() {
  const { token, setToken, readiness } = useAppContext()
  const [settings, setSettings] = useState({
    critical: true,
    high: true,
    system: false,
    sound: isSoundEnabled(),
    compact: false,
    confirmation: true,
  })
  const [saved, setSaved] = useState(false)
  const toggle = (key: keyof typeof settings) => {
    if (key === 'sound') {
      setSoundEnabled(!settings.sound)
    }
    setSettings((current) => ({ ...current, [key]: !current[key] }))
    setSaved(false)
  }
  return <div className="page">
    <PageTitle eyebrow="PREFERENCES" title="Settings" description="Configure your workspace and notification preferences." />
    <div className="settings-layout">
      <nav className="settings-nav"><a className="settings-nav-active" href="#notifications"><Bell size={16} /> Notifications</a><a href="#display"><Monitor size={16} /> Display</a><a href="#uploads"><Upload size={16} /> Uploads</a><a href="#regional"><Globe2 size={16} /> Regional</a></nav>
      <div className="settings-content">
        <section id="notifications" className="panel settings-panel"><div className="settings-section-heading"><div className="settings-heading-icon"><Bell size={17} /></div><div><h2>Notifications &amp; Voice Alarms</h2><p>Configure audible alarm sirens and spoken security voice alerts.</p></div></div><div className="setting-row"><div><strong>Critical alerts</strong><span>Immediate notification for critical items flagged for review</span></div><Toggle checked={settings.critical} onChange={() => toggle('critical')} label="Critical alerts" /></div><div className="setting-row"><div><strong>High priority alerts</strong><span>Notify when a high severity item is flagged</span></div><Toggle checked={settings.high} onChange={() => toggle('high')} label="High priority alerts" /></div><div className="setting-row"><div><strong>New upload notifications</strong><span>Show a notification when files are added</span></div><Toggle checked={settings.system} onChange={() => toggle('system')} label="New upload notifications" /></div><div className="setting-row"><div className="setting-label-icon"><Volume2 size={16} /><div><strong>Voice Alerts &amp; Alarm Siren</strong><span>Play audible siren and voice warning on perimeter intrusions &amp; loitering</span></div></div><div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><button type="button" className="button button-small" onClick={() => speakAlert("Security Warning! Perimeter intrusion detected in restricted sector!")}><Volume2 size={13} /> Test Voice Alarm</button><Toggle checked={settings.sound} onChange={() => toggle('sound')} label="Sound notifications" /></div></div></section>
        <section id="display" className="panel settings-panel"><div className="settings-section-heading"><div className="settings-heading-icon"><Monitor size={17} /></div><div><h2>Display preferences</h2><p>Personalize your operations workspace.</p></div></div><div className="setting-row"><div className="setting-label-icon"><Moon size={16} /><div><strong>Compact data tables</strong><span>Show more rows with reduced spacing</span></div></div><Toggle checked={settings.compact} onChange={() => toggle('compact')} label="Compact data tables" /></div><div className="setting-row"><div><strong>Confirm before dismissing</strong><span>Ask for confirmation when dismissing a flagged item</span></div><Toggle checked={settings.confirmation} onChange={() => toggle('confirmation')} label="Confirm before dismissing" /></div></section>
        <section id="uploads" className="panel settings-panel"><div className="settings-section-heading"><div className="settings-heading-icon"><Upload size={17} /></div><div><h2>Service connection</h2><p>Authenticate requests to the local IBVAP analytics service.</p></div></div><label className="field-label" htmlFor="service-token">SERVICE API TOKEN</label><input id="service-token" type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Enter IBVAP_API_TOKEN" autoComplete="off" /><p className="field-hint">{readiness ? `Service ${readiness.status}.` : 'Token is held in this browser session only.'}</p><div className="upload-preference-row"><div><strong>Supported media</strong><span>Images can be analyzed by the configured models</span></div><span className="upload-format-tags"><i>JPG</i><i>PNG</i><i>WEBP</i></span></div></section>
        <section id="regional" className="panel settings-panel region-panel"><div className="settings-section-heading"><div className="settings-heading-icon"><Globe2 size={17} /></div><div><h2>Regional preferences</h2><p>Set the time and language used in this workspace.</p></div></div><div className="regional-fields"><label>TIME ZONE<select defaultValue="UTC−05:00 · Eastern Time"><option>UTC−05:00 · Eastern Time</option><option>UTC+00:00 · Coordinated Universal Time</option><option>UTC+05:30 · India Standard Time</option></select></label><label>DATE FORMAT<select defaultValue="MMM DD, YYYY"><option>MMM DD, YYYY</option><option>DD/MM/YYYY</option><option>MM/DD/YYYY</option></select></label></div></section>
        <div className="settings-actions"><span>{saved && <><Check size={15} /> Preferences saved</>}</span><button className="button button-primary" onClick={() => setSaved(true)}>Save preferences</button></div>
      </div>
    </div>
  </div>
}

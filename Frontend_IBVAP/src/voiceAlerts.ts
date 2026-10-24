import type { AnalyticsEvent } from './api'

export function isSoundEnabled(): boolean {
  if (typeof window === 'undefined') return true
  return localStorage.getItem('ibvap-sound-enabled') !== 'false'
}

export function setSoundEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return
  localStorage.setItem('ibvap-sound-enabled', enabled ? 'true' : 'false')
}

/**
 * Synthesizes an audible security alarm sound using browser Web Audio API
 */
export function playAlarmSound(type: 'critical' | 'warning' | 'info' = 'critical'): void {
  if (!isSoundEnabled() || typeof window === 'undefined') return

  try {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    if (!AudioContextClass) return

    const ctx = new AudioContextClass()
    const now = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()

    osc.connect(gain)
    gain.connect(ctx.destination)

    if (type === 'critical') {
      // Rapid dual-frequency urgent security siren: 880Hz -> 660Hz -> 880Hz -> 660Hz
      osc.type = 'sawtooth'
      osc.frequency.setValueAtTime(880, now)
      osc.frequency.setValueAtTime(659.25, now + 0.12)
      osc.frequency.setValueAtTime(880, now + 0.24)
      osc.frequency.setValueAtTime(659.25, now + 0.36)

      gain.gain.setValueAtTime(0.18, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.5)

      osc.start(now)
      osc.stop(now + 0.5)
    } else if (type === 'warning') {
      // Alert ascending chime: 587Hz -> 880Hz
      osc.type = 'triangle'
      osc.frequency.setValueAtTime(587.33, now)
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.2)

      gain.gain.setValueAtTime(0.2, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45)

      osc.start(now)
      osc.stop(now + 0.45)
    } else {
      // Subtle confirmation beep
      osc.type = 'sine'
      osc.frequency.setValueAtTime(620, now)
      gain.gain.setValueAtTime(0.12, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25)

      osc.start(now)
      osc.stop(now + 0.25)
    }
  } catch (err) {
    console.warn('AudioContext playback error:', err)
  }
}

/**
 * Voice synthesis alert: plays an alarm chime and speaks the security warning aloud
 */
export function speakAlert(message: string, withAlarm: boolean = true): void {
  if (!isSoundEnabled() || typeof window === 'undefined') return

  if (withAlarm) {
    playAlarmSound('critical')
  }

  if (!('speechSynthesis' in window)) return

  try {
    window.speechSynthesis.cancel()

    const utterance = new SpeechSynthesisUtterance(message)
    utterance.rate = 1.05
    utterance.pitch = 1.0
    utterance.volume = 1.0

    const voices = window.speechSynthesis.getVoices()
    const englishVoice = voices.find(
      (v) => v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Microsoft') || v.name.includes('Samantha') || v.name.includes('English'))
    )
    if (englishVoice) {
      utterance.voice = englishVoice
    }

    setTimeout(() => {
      window.speechSynthesis.speak(utterance)
    }, withAlarm ? 320 : 0)
  } catch (err) {
    console.warn('SpeechSynthesis error:', err)
  }
}

/**
 * Generates an appropriate spoken warning message for a detected security event
 */
export function announceSecurityEvent(event: AnalyticsEvent): void {
  const cam = event.camera_id ? event.camera_id.replace(/^sim-/, '').replace(/[-_]/g, ' ') : 'camera'
  const obj = event.object?.class_name ?? 'activity'

  let message = ''
  if (event.event_type.includes('intrusion')) {
    message = `Security Alert! Perimeter intrusion detected. ${obj} in restricted area at ${cam}!`
  } else if (event.event_type.includes('loitering')) {
    message = `Warning! Loitering activity detected. ${obj} in zone at ${cam}!`
  } else if (event.event_type.includes('night_movement')) {
    message = `Security Alert! Unauthorized night movement detected at ${cam}!`
  } else if (event.event_type === 'plate_read' && event.details?.plate_text) {
    message = `Notice: License plate recognized. Plate ${event.details.plate_text} at ${cam}.`
  } else {
    message = `Security notice: ${event.event_type.replace(/_/g, ' ')} detected at ${cam}.`
  }

  speakAlert(message, true)
}

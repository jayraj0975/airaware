import { useState } from 'react'
import { toast } from './ui'

/** Why a location request failed, in words a person can act on. */
export function locationProblem(code: number | 'insecure' | 'unsupported'): string {
  switch (code) {
    case 'insecure': return 'Your browser only shares location on the secure (https) address of this site. Search or tap the map instead.'
    case 'unsupported': return 'This browser cannot share your location. Search for your area or tap the map instead.'
    case 1: return 'Location is blocked for this site. Allow it in your browser settings (the lock icon by the address), or search instead.'
    case 2: return 'Your device could not work out where you are right now. Try again outdoors, or search for your area.'
    case 0: return 'No answer to the location request. If your browser showed a prompt, allow it and try again; if not, location may be turned off for this site.'
    default: return 'Finding your location took too long. Try again, or search for your area.'
  }
}

/** "Use my location": asks the browser for a fresh, precise fix (GPS on phones), falls back to a quicker rough one,
 * and passes on how accurate the answer is. The position is used only to look up that spot; it is not stored
 * unless the person saves the place. */
export default function LocateButton({ onFound }: { onFound: (lat: number, lon: number, accuracy: number) => void }) {
  const [busy, setBusy] = useState(false)
  const locate = () => {
    if (!window.isSecureContext) return toast(locationProblem('insecure'), 'error')
    if (!('geolocation' in navigator)) return toast(locationProblem('unsupported'), 'error')
    setBusy(true)
    // The browser's own timeout only starts once permission is granted, so an ignored or dismissed prompt would
    // wait forever. This watchdog gives up after 25 s and says so; a late answer is then ignored.
    let settled = false
    const finish = () => { const first = !settled; settled = true; setBusy(false); clearTimeout(watchdog); return first }
    const watchdog = setTimeout(() => { if (finish()) toast(locationProblem(0), 'error') }, 25000)
    const ask = (precise: boolean) => navigator.geolocation.getCurrentPosition(
      (p) => {
        if (!finish()) return
        const { latitude: lat, longitude: lon, accuracy } = p.coords
        if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
          return toast('Your device returned an impossible position. Search for your area or tap the map instead.', 'error')
        }
        onFound(lat, lon, accuracy)
      },
      (e) => {
        if (settled) return
        if (precise && e.code !== 1) return ask(false)   // no GPS fix in time: settle for the device's rough position
        if (finish()) toast(locationProblem(e.code), 'error')
      },
      precise ? { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 } : { enableHighAccuracy: false, timeout: 10000, maximumAge: 10 * 60 * 1000 },
    )
    ask(true)
  }
  return (
    <button type="button" className="ghost small locate-btn" onClick={locate} disabled={busy} aria-busy={busy}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
      {busy ? 'Locating…' : 'Use my location'}
    </button>
  )
}

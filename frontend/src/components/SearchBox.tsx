import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

interface Hit { name: string; area: string; lat: number; lon: number }

/** Type an area's name, pick a result: debounced, keyboard-friendly, limited to the selected city. */
export default function SearchBox({ city, onPick }: { city: string; onPick: (lat: number, lon: number, label: string) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Hit[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [state, setState] = useState<'idle' | 'busy' | 'none' | 'error'>('idle')
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); setState('idle'); return }
    setState('busy')
    const t = setTimeout(() => {
      api.get<Hit[]>(`/api/search?q=${encodeURIComponent(q.trim())}&city=${encodeURIComponent(city)}`)
        .then((h) => { setHits(h); setActive(0); setOpen(true); setState(h.length ? 'idle' : 'none') })
        .catch(() => setState('error'))
    }, 450)  // wait for a pause in typing: the place service allows about one lookup a second
    return () => clearTimeout(t)
  }, [q, city])

  useEffect(() => {
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  const choose = (h: Hit) => { onPick(h.lat, h.lon, h.name); setQ(h.name); setOpen(false) }
  return (
    <div className="search-box" ref={box}>
      <input type="text" inputMode="search" placeholder={`Search an area in ${city}, e.g. ${city === 'Pune' ? 'Kothrud' : 'Andheri'}`} value={q} aria-label="Search for an area"
        onChange={(e) => setQ(e.target.value)} onFocus={() => hits.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          if (e.key === 'Enter' && hits[active]) { e.preventDefault(); choose(hits[active]) }
          if (e.key === 'Escape') setOpen(false)
        }} />
      {state === 'busy' && <span className="search-state">Searching…</span>}
      {open && (hits.length > 0 || state !== 'idle') && (
        <ul className="search-results" role="listbox">
          {hits.map((h, i) => (
            <li key={`${h.lat},${h.lon}`} role="option" aria-selected={i === active} className={i === active ? 'on' : ''}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); choose(h) }}>
              <b>{h.name}</b><small>{h.area}</small>
            </li>
          ))}
          {state === 'none' && <li className="muted">No match in {city}. Try another spelling, or click the map.</li>}
          {state === 'error' && <li className="muted">Search is busy. Try again in a moment, or click the map.</li>}
        </ul>
      )}
    </div>
  )
}

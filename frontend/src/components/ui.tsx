import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { Category, ForecastDay, Personal } from '../api'
import { AQI_BANDS, dayName, fmt } from '../util'

export function Card({ title, hint, children, className = '', action, id }: { title?: ReactNode; hint?: ReactNode; children: ReactNode; className?: string; action?: ReactNode; id?: string }) {
  return (
    <section className={`card ${className}`} id={id}>
      {(title || hint || action) && (
        <div className="card-head">
          <div>{title && <h2>{title}</h2>}{hint && <p className="hint">{hint}</p>}</div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

/** Category name with a small colour mark: the colour carries meaning without shouting. */
export const Pill = ({ cat }: { cat: Category | { name: string; colour: string } }) => (
  <span className="pill"><i style={{ background: cat.colour }} />{cat.name}</span>
)

/** The 0–500 AQI scale in CPCB's bands, with the likely range bracketed and the forecast marked. */
export function AqiMeter({ value, lo, hi }: { value: number; lo?: number; hi?: number }) {
  const pos = (v: number) => `${Math.max(0, Math.min(100, (v / 500) * 100))}%`
  let from = 0
  return (
    <div className="meter" role="img" aria-label={`AQI ${fmt(value)} on a scale of 0 to 500${lo != null && hi != null ? `, likely ${fmt(lo)} to ${fmt(hi)}` : ''}`}>
      <div className="meter-bar">
        {AQI_BANDS.map((b) => { const w = b.upto - from; const el = <span key={b.upto} style={{ flexGrow: w, background: b.colour }} />; from = b.upto; return el })}
      </div>
      {lo != null && hi != null && <div className="meter-range" style={{ left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` }} />}
      <div className="meter-mark" style={{ left: pos(value) }} />
      <div className="meter-scale"><span>0</span><span>100</span><span>200</span><span>300</span><span>400</span><span>500</span></div>
    </div>
  )
}

/** A forecast figure: the number, its category and where it sits on the AQI scale. */
export function Reading({ label, value, cat, lo, hi, size = 'large', children }: {
  label: ReactNode; value: number; cat: Category | { name: string; colour: string }; lo?: number; hi?: number; size?: 'large' | 'medium'; children?: ReactNode
}) {
  return (
    <div className={`reading ${size}`}>
      <div className="reading-label">{label}</div>
      <div className="reading-row"><span className="reading-num">{fmt(value)}</span><span className="reading-cat"><i style={{ background: cat.colour }} />{cat.name}</span></div>
      <AqiMeter value={value} lo={lo} hi={hi} />
      {children}
    </div>
  )
}

export const Advice = ({ p }: { p: Personal }) => (
  <p className={`advice ${p.level}`}><b>{p.level === 'ok' ? 'Good to go.' : p.level === 'caution' ? 'Take care.' : 'Limit time outside.'}</b> {p.text}</p>
)

/** The coming days as a compact list: day, colour mark, number. */
export function DayStrip({ days }: { days: ForecastDay[]; compact?: boolean }) {
  return (
    <ol className="days">
      {days.map((f) => (
        <li key={f.date} title={`${f.category.name} · likely ${fmt(f.lo)}–${fmt(f.hi)}`}>
          <span className="day">{dayName(f.date)}</span>
          <i style={{ background: f.category.colour }} />
          <b>{fmt(f.forecast)}</b>
        </li>
      ))}
    </ol>
  )
}

const PATHS: Record<string, ReactNode> = {
  bell: <><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
  close: <><path d="M18 6 6 18M6 6l12 12" /></>,
  star: <><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" /></>,
  share: <><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" /><path d="m16 6-4-4-4 4M12 2v13" /></>,
  flag: <><path d="M4 22V4a1 1 0 0 1 1-1h12l-2 4 2 4H5" /></>,
  download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5M12 15V3" /></>,
  check: <><path d="M20 6 9 17l-5-5" /></>,
  pin: <><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0z" /><circle cx="12" cy="10" r="3" /></>,
  calendar: <><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></>,
}

/** Simple line icons (no emoji): name one of the keys above. */
export const Icon = ({ name, size = 16 }: { name: keyof typeof PATHS; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{PATHS[name]}</svg>
)

export const Spinner = ({ label = 'Loading…' }: { label?: string }) => <div className="spinner"><i />{label}</div>
export const ErrorBox = ({ error }: { error: unknown }) => <div className="error">{error instanceof Error ? error.message : String(error)}</div>
export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>

export function Stat({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: ReactNode }) {
  return <div className="stat"><span>{label}</span><b>{value}</b>{sub && <small>{sub}</small>}</div>
}

/** Loads data for a component; re-runs when `deps` change. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: unknown; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    setLoading(true)
    load().then((d) => { if (alive) { setData(d); setError(null) } }).catch((e) => { if (alive) setError(e) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, error, loading, reload: () => setTick((t) => t + 1) }
}

/** Sets the browser tab title for a page. */
export function useTitle(title: string) {
  useEffect(() => { document.title = title ? `${title} · AirAware` : 'AirAware · Air quality forecasts for Pune & Mumbai' }, [title])
}

// ---------- toasts: short messages that confirm an action, shown by <Toaster /> in the shell ----------

type ToastKind = 'ok' | 'error'
export function toast(message: string, kind: ToastKind = 'ok') {
  window.dispatchEvent(new CustomEvent('aa-toast', { detail: { message, kind } }))
}

export function Toaster() {
  const [items, setItems] = useState<{ id: number; message: string; kind: ToastKind }[]>([])
  useEffect(() => {
    let next = 1
    const on = (e: Event) => {
      const { message, kind } = (e as CustomEvent).detail
      const id = next++
      setItems((xs) => [...xs, { id, message, kind }])
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4500)
    }
    window.addEventListener('aa-toast', on)
    return () => window.removeEventListener('aa-toast', on)
  }, [])
  return <div className="toasts" role="status" aria-live="polite">{items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.message}</div>)}</div>
}

// ---------- dialogs ----------

/** A modal dialog. It is rendered at the end of <body> (a portal), never inside the page's own markup: a dialog
 * with a form, opened from inside another form, would otherwise be a nested form, and the browser would submit
 * the outer one instead (this broke two-step setup and account deletion). */
export function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  // Keyboard users land inside the dialog (its first field, else the dialog itself, never a destructive button),
  // Tab stays inside while it is open, and focus returns to whatever opened it.
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const el = box.current!
    const focusable = () => [...el.querySelectorAll<HTMLElement>('input, select, textarea, button, a[href], [tabindex]:not([tabindex="-1"])')].filter((x) => !x.hasAttribute('disabled'))
    ;(el.querySelector<HTMLElement>('input, select, textarea') ?? el).focus()
    const trap = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const f = focusable()
      if (!f.length) return
      const [first, last] = [f[0], f[f.length - 1]]
      if (e.shiftKey && (document.activeElement === first || document.activeElement === el)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    el.addEventListener('keydown', trap)
    return () => { el.removeEventListener('keydown', trap); opener?.focus?.() }
  }, [])
  return createPortal(
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} ref={box} tabIndex={-1}>
        <div className="dialog-head"><h2>{title}</h2><button type="button" className="icon-btn" aria-label="Close" onClick={onClose}><Icon name="close" /></button></div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** A dialog asking for one line of text (replaces window.prompt). */
export function AskDialog({ title, label, initial = '', ok, type = 'text', note, danger = false, onSubmit, onClose }: {
  title: string; label: string; initial?: string; ok: string; type?: string; note?: ReactNode; danger?: boolean
  onSubmit: (value: string) => Promise<void> | void; onClose: () => void
}) {
  const [value, setValue] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return (
    <Dialog title={title} onClose={onClose}>
      <form className="form" onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setError('')
        try { await onSubmit(value); onClose() } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
      }}>
        {note && <p className="small muted">{note}</p>}
        <label>{label}<input autoFocus required type={type} value={value} maxLength={type === 'password' ? 256 : 80} onChange={(e) => setValue(e.target.value)}
          autoComplete={type === 'password' ? 'current-password' : 'off'} /></label>
        {error && <div className="error">{error}</div>}
        <div className="actions end"><button type="button" className="ghost small" onClick={onClose}>Cancel</button>
          <button className={`btn small ${danger ? 'danger-btn' : ''}`} disabled={busy || !value.trim()}>{busy ? 'Please wait…' : ok}</button></div>
      </form>
    </Dialog>
  )
}

/** A yes/no dialog (replaces window.confirm). */
export function ConfirmDialog({ title, children, ok, onConfirm, onClose }: { title: string; children: ReactNode; ok: string; onConfirm: () => Promise<void> | void; onClose: () => void }) {
  return (
    <Dialog title={title} onClose={onClose}>
      <div className="small">{children}</div>
      <div className="actions end"><button className="ghost small" onClick={onClose}>Cancel</button>
        <button className="btn small danger-btn" onClick={async () => { await onConfirm(); onClose() }}>{ok}</button></div>
    </Dialog>
  )
}

/** If a page crashes in the browser, show a friendly way out instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('AirAware page error', error, info.componentStack) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="page narrow">
        <div className="card oops">
          <h1>Something went wrong on this page</h1>
          <p>Sorry about that. It is usually a hiccup: reloading fixes it. Your account and data are safe.</p>
          <div className="actions"><button className="btn" onClick={() => location.reload()}>Reload</button><a className="ghost" href="/">Go to today's air</a></div>
        </div>
      </div>
    )
  }
}

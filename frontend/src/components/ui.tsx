import { useEffect, useState, type ReactNode } from 'react'
import type { Category, ForecastDay, Personal } from '../api'
import { dayName, fmt } from '../util'

export function Card({ title, hint, children, className = '', action }: { title?: ReactNode; hint?: ReactNode; children: ReactNode; className?: string; action?: ReactNode }) {
  return (
    <section className={`card ${className}`}>
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

export const Pill = ({ cat }: { cat: Category | { name: string; colour: string } }) => (
  <span className="pill" style={{ background: cat.colour }}>{cat.name}</span>
)

export function AqiHero({ label, value, cat, sub, children }: { label: ReactNode; value: number; cat: Category; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="aqi-hero" style={{ background: cat.colour }}>
      <div className="label">{label}</div>
      <div className="num">{fmt(value)}</div>
      <div className="cat">{cat.name}</div>
      {sub && <div className="sub">{sub}</div>}
      {children}
    </div>
  )
}

export const Advice = ({ p }: { p: Personal }) => (
  <div className={`advice ${p.level}`}><b>{p.level === 'ok' ? 'Good to go' : p.level === 'caution' ? 'Take care' : 'Limit time outside'}.</b> {p.text}</div>
)

export function DayStrip({ days, compact = false }: { days: ForecastDay[]; compact?: boolean }) {
  return (
    <div className={`days ${compact ? 'compact' : ''}`}>
      {days.map((f) => (
        <div key={f.date} style={{ background: f.category.colour }} title={`Likely ${fmt(f.lo)}–${fmt(f.hi)}`}>
          <span>{dayName(f.date)}</span><b>{fmt(f.forecast)}</b>{!compact && <small>{f.category.name}</small>}
        </div>
      ))}
    </div>
  )
}

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

export function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-head"><h2>{title}</h2><button className="link" aria-label="Close" onClick={onClose}>✕</button></div>
        {children}
      </div>
    </div>
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

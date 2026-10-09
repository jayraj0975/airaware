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

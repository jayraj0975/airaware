import { useState } from 'react'
import { api } from '../api'
import AreaMap from '../components/AreaMap'
import { Bars } from '../components/charts'
import { Card, Empty, ErrorBox, Spinner, Stat, useLoad, useTitle } from '../components/ui'
import { useSession } from '../session'
import { dateTime, fmt, shortDate } from '../util'

interface Overview {
  counts: Record<string, number>; signups: { day: string; n: number }[]
  freshness: { city: string; last_measured: string; days_behind: number; stations_reporting: number; stations_total: number; weather_until: string }[]
  trained_at: string; live: { at: string | null; stations: number }
  model: { mae: number; persistence_mae: number; dm_p: number; test_forecasts: number }; job_running: boolean
}
interface AdminUser { id: number; email: string; name: string; role: string; city: string; health: string; disabled: number; created_at: string; last_login: string | null; places: number; alerts: number; reports: number }
interface AdminReport { id: number; lat: number; lon: number; city: string; kind: string; note: string; status: string; created_at: string; author: string | null }
interface Job { id: number; kind: string; started_at: string; finished_at: string | null; ok: number | null; message: string }
interface Audit { id: number; at: string; email: string | null; action: string; detail: string; ip: string | null }
interface StationHealth { city: string; station: string; days: number; correlation: number | null; bias: number; verdict: string; date: string; aqi: number; days_30: number }

const TABS = ['Overview', 'Users', 'Reports', 'Data & jobs', 'Audit log'] as const

export default function Admin() {
  useTitle('Admin')
  const [tab, setTab] = useState<(typeof TABS)[number]>('Overview')
  return (
    <div className="page">
      <div className="page-head"><h1>Admin console</h1><p className="muted">Platform health, users, moderation and the data pipeline.</p></div>
      <div className="tabs">{TABS.map((t) => <button key={t} className={t === tab ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
      {tab === 'Overview' && <OverviewTab />}
      {tab === 'Users' && <UsersTab />}
      {tab === 'Reports' && <ReportsTab />}
      {tab === 'Data & jobs' && <DataTab />}
      {tab === 'Audit log' && <AuditTab />}
    </div>
  )
}

function OverviewTab() {
  const { data: o, error } = useLoad(() => api.get<Overview>('/api/admin/overview'), [])
  if (error) return <ErrorBox error={error} />
  if (!o) return <Spinner />
  const c = o.counts
  return (
    <>
      <div className="stats">
        <Stat label="Users" value={fmt(c.users)} sub={`${c.new_users} new, ${c.active_users} active this week`} />
        <Stat label="Saved places" value={fmt(c.places)} sub={`${c.alerts} active alerts`} />
        <Stat label="Warnings sent this week" value={fmt(c.warnings_week)} />
        <Stat label="Reports to moderate" value={fmt(c.reports_pending)} sub={`${c.reports} in all`} />
        <Stat label="Forecasts logged" value={fmt(c.forecasts_logged)} sub={`${c.forecasts_scored} scored against reality`} />
        <Stat label="Model error (test)" value={`${fmt(o.model.mae, 1)} AQI`} sub={`vs ${fmt(o.model.persistence_mae, 1)} naive · p ${o.model.dm_p < 0.001 ? '< 0.001' : '= ' + fmt(o.model.dm_p, 3)}`} />
      </div>
      <div className="grid two">
        <Card title="Data freshness">
          <div className="table-wrap"><table>
            <thead><tr><th>City</th><th>Last reading</th><th className="num">Days behind</th><th className="num">Stations this week</th><th>Weather until</th></tr></thead>
            <tbody>{o.freshness.map((f) => (
              <tr key={f.city}><td>{f.city}</td><td>{shortDate(f.last_measured)}</td><td className={`num ${f.days_behind > 6 ? 'warn' : ''}`}>{f.days_behind}</td>
                <td className="num">{f.stations_reporting}/{f.stations_total}</td><td>{shortDate(f.weather_until)}</td></tr>
            ))}</tbody>
          </table></div>
          <p className="small muted">Models trained {dateTime(o.trained_at)}. Live readings: {o.live.at ? `${o.live.stations} stations at ${dateTime(o.live.at)}` : 'off (set OPENAQ_API_KEY)'}.</p>
        </Card>
        <Card title="Sign-ups, last 30 days">
          {o.signups.length ? <Bars labels={o.signups.map((s) => shortDate(s.day))} values={o.signups.map((s) => s.n)} colours={o.signups.map(() => '#2563eb')} /> : <Empty>No sign-ups in the last 30 days.</Empty>}
        </Card>
      </div>
    </>
  )
}

function UsersTab() {
  const { user: me } = useSession()
  const [q, setQ] = useState('')
  const users = useLoad(() => api.get<AdminUser[]>(`/api/admin/users?q=${encodeURIComponent(q)}`), [q])
  const [err, setErr] = useState('')
  const [link, setLink] = useState<{ who: string; url: string } | null>(null)
  const resetLink = async (u: AdminUser) => {
    try {
      const r = await api.post<{ path: string }>(`/api/admin/users/${u.id}/reset-link`)
      setLink({ who: u.email, url: location.origin + r.path })
    } catch (e) { setErr((e as Error).message) }
  }
  const change = async (u: AdminUser, body: object) => {
    try { await api.patch(`/api/admin/users/${u.id}`, body); users.reload(); setErr('') } catch (e) { setErr((e as Error).message) }
  }
  return (
    <Card title="Users" action={<input className="search" placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} />}>
      {err && <div className="error">{err}</div>}
      {link && (
        <div className="reset-link">
          <b>One-time reset link for {link.who}</b>, valid 24 hours. Send it to them privately; it stops working once used.
          <div className="row-form"><input readOnly value={link.url} onFocus={(e) => e.target.select()} />
            <button className="btn small" onClick={() => navigator.clipboard?.writeText(link.url)}>Copy</button>
            <button className="ghost small" onClick={() => setLink(null)}>Done</button></div>
        </div>
      )}
      {!users.data ? <Spinner /> : (
        <div className="table-wrap"><table>
          <thead><tr><th>User</th><th>Role</th><th>City</th><th className="num">Places</th><th className="num">Alerts</th><th className="num">Reports</th><th>Joined</th><th>Last sign-in</th><th /></tr></thead>
          <tbody>{users.data.map((u) => (
            <tr key={u.id} className={u.disabled ? 'off' : ''}>
              <td><b>{u.name}</b><br /><small className="muted">{u.email}</small></td>
              <td><span className={`tag ${u.role}`}>{u.role}</span></td><td>{u.city}</td>
              <td className="num">{u.places}</td><td className="num">{u.alerts}</td><td className="num">{u.reports}</td>
              <td>{shortDate(u.created_at)}</td><td>{u.last_login ? dateTime(u.last_login) : '–'}</td>
              <td className="actions">{u.id !== me?.id && <>
                <button className="link" onClick={() => change(u, { role: u.role === 'admin' ? 'user' : 'admin' })}>{u.role === 'admin' ? 'Make user' : 'Make admin'}</button>
                <button className="link" onClick={() => resetLink(u)}>Reset link</button>
                <button className="link danger" onClick={() => change(u, { disabled: !u.disabled })}>{u.disabled ? 'Enable' : 'Disable'}</button>
              </>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  )
}

function ReportsTab() {
  const { status } = useSession()
  const [which, setWhich] = useState('pending')
  const reports = useLoad(() => api.get<AdminReport[]>(`/api/admin/reports?status=${which}`), [which])
  const moderate = async (id: number, s: string) => { await api.patch(`/api/admin/reports/${id}`, { status: s }); reports.reload() }
  const first = reports.data?.[0]
  return (
    <Card title="Citizen reports" action={<div className="tabs mini">{['pending', 'approved', 'rejected'].map((s) => <button key={s} className={s === which ? 'on' : ''} onClick={() => setWhich(s)}>{s}</button>)}</div>}>
      {!reports.data ? <Spinner /> : reports.data.length === 0 ? <Empty>No {which} reports.</Empty> : (
        <div className="map-row">
          <AreaMap center={[first!.lat, first!.lon]} zoom={11} height={420}
            pins={reports.data.map((r) => ({ lat: r.lat, lon: r.lon, label: `#${r.id}`, colour: '#ea580c' }))} />
          <ul className="moderation">{reports.data.map((r) => (
            <li key={r.id}>
              <b>#{r.id} · {status?.report_kinds[r.kind] ?? r.kind}</b> <small className="muted">{r.city} · {dateTime(r.created_at)} · {r.author ?? 'deleted user'}</small>
              {r.note && <p>“{r.note}”</p>}
              <div className="actions">
                {r.status !== 'approved' && <button className="btn small" onClick={() => moderate(r.id, 'approved')}>Approve</button>}
                {r.status !== 'rejected' && <button className="ghost small" onClick={() => moderate(r.id, 'rejected')}>Reject</button>}
              </div>
            </li>
          ))}</ul>
        </div>
      )}
    </Card>
  )
}

function DataTab() {
  const jobs = useLoad(() => api.get<Job[]>('/api/admin/jobs'), [])
  const stations = useLoad(() => api.get<StationHealth[]>('/api/admin/stations'), [])
  const [msg, setMsg] = useState('')
  const refresh = async () => {
    try { await api.post('/api/admin/refresh'); setMsg('Rebuild started: downloading new readings, weather and CAMS, then retraining. This takes a few minutes.'); setTimeout(jobs.reload, 1500) }
    catch (e) { setMsg((e as Error).message) }
  }
  return (
    <>
      <Card title="Pipeline jobs" hint="Startup, scheduled and manual rebuilds" action={<div className="actions"><button className="ghost small" onClick={jobs.reload}>Reload</button><button className="btn small" onClick={refresh}>Rebuild data now</button></div>}>
        {msg && <p className="small ok">{msg}</p>}
        {!jobs.data ? <Spinner /> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Job</th><th>Started</th><th>Took</th><th>Result</th><th>Message</th></tr></thead>
            <tbody>{jobs.data.map((j) => (
              <tr key={j.id}><td>{j.kind}</td><td>{dateTime(j.started_at)}</td>
                <td>{j.finished_at ? `${Math.round((+new Date(j.finished_at) - +new Date(j.started_at)) / 1000)} s` : 'running…'}</td>
                <td>{j.ok == null ? <span className="tag pending">running</span> : j.ok ? <span className="tag approved">ok</span> : <span className="tag rejected">failed</span>}</td>
                <td className="wrap">{j.message}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
      <Card title="Station health" hint="Last 90 days, each station against the median of its city">
        {!stations.data ? <Spinner /> : (
          <div className="table-wrap"><table>
            <thead><tr><th>City</th><th>Station</th><th>Last day</th><th className="num">Days, last 30</th><th className="num">Correlation</th><th className="num">Bias</th><th>Verdict</th></tr></thead>
            <tbody>{stations.data.map((s) => (
              <tr key={s.station}><td>{s.city}</td><td>{s.station}</td><td>{s.date}</td><td className={`num ${s.days_30 < 15 ? 'warn' : ''}`}>{s.days_30}</td>
                <td className="num">{fmt(s.correlation, 2)}</td><td className="num">{fmt(s.bias)}</td>
                <td className={s.verdict === 'Agrees with the city' ? 'muted' : 'warn'}>{s.verdict}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
    </>
  )
}

function AuditTab() {
  const { data, error } = useLoad(() => api.get<Audit[]>('/api/admin/audit'), [])
  if (error) return <ErrorBox error={error} />
  return (
    <Card title="Audit log" hint="Sign-ins, failed sign-ins, admin actions and reports">
      {!data ? <Spinner /> : (
        <div className="table-wrap"><table>
          <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th><th>IP</th></tr></thead>
          <tbody>{data.map((a) => (
            <tr key={a.id}><td>{dateTime(a.at)}</td><td>{a.email ?? '–'}</td><td><code>{a.action}</code></td><td className="wrap">{a.detail}</td><td><small>{a.ip ?? ''}</small></td></tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  )
}

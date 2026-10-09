import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Note, type Place } from '../api'
import AreaMap from '../components/AreaMap'
import { Advice, Card, DayStrip, Empty, ErrorBox, Pill, Spinner, useLoad } from '../components/ui'
import { useSession } from '../session'
import { dateTime, fmt, upcoming } from '../util'

interface MyReport { id: number; kind: string; note: string; status: string; created_at: string; city: string }

export default function Me() {
  const { user, city, status, refresh } = useSession()
  const places = useLoad(() => api.get<Place[]>('/api/me/places'), [])
  const notes = useLoad(() => api.get<Note[]>('/api/me/notifications'), [])
  const reports = useLoad(() => api.get<MyReport[]>('/api/me/reports'), [])
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    if (location.hash === '#notifications') document.getElementById('notifications')?.scrollIntoView({ behavior: 'smooth' })
  }, [notes.data])
  if (!user) return null
  const centre = status?.cities[user.city] ?? status?.cities[city]

  const markRead = async () => { await api.post('/api/me/notifications/read'); notes.reload(); refresh() }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Hi {user.name.split(' ')[0]}</h1>
        <p className="muted">Your places, your alerts and advice tuned to {user.health.length ? 'your health profile' : <Link to="#profile">your health profile (set it below)</Link>}.</p>
      </div>

      <Card title="Your places" hint="Forecast for each place, with advice for you" action={<button className="btn small" onClick={() => setAdding(!adding)}>{adding ? 'Done' : '+ Add a place'}</button>}>
        {adding && centre && <AddPlace centre={[centre.lat, centre.lon]} onAdded={() => { places.reload(); setAdding(false) }} />}
        {places.loading ? <Spinner /> : places.error ? <ErrorBox error={places.error} /> : places.data!.length === 0 ? (
          <Empty>No places yet. Add home, work or your child's school, or save a spot from the <Link to="/">map</Link>.</Empty>
        ) : (
          <div className="places">{places.data!.map((p) => <PlaceCard key={p.id} p={p} onChange={() => { places.reload(); notes.reload(); refresh() }} />)}</div>
        )}
      </Card>

      <div className="grid two">
        <Card title={<span id="notifications">Notifications</span>} action={notes.data?.some((n) => !n.read) && <button className="ghost small" onClick={markRead}>Mark all read</button>}>
          {!notes.data ? <Spinner /> : notes.data.length === 0 ? <Empty>No alerts yet. Set an alert on a place and we will warn you before a bad day.</Empty> : (
            <ul className="notes">{notes.data.map((n) => (
              <li key={n.id} className={n.read ? '' : 'unread'}><b>{n.title}</b><p>{n.body}</p><small>{dateTime(n.created_at)}</small></li>
            ))}</ul>
          )}
        </Card>
        <Profile />
      </div>

      <div className="grid two">
        <Card title="Your pollution reports" hint="Reports appear on the public map once a moderator approves them">
          {!reports.data ? <Spinner /> : reports.data.length === 0 ? <Empty>You have not reported anything yet. Click a spot on the <Link to="/">map</Link> and choose “Report pollution here”.</Empty> : (
            <div className="table-wrap"><table><thead><tr><th>When</th><th>What</th><th>Note</th><th>Status</th></tr></thead>
              <tbody>{reports.data.map((r) => <tr key={r.id}><td>{dateTime(r.created_at)}</td><td>{status?.report_kinds[r.kind] ?? r.kind}</td><td>{r.note}</td><td><span className={`tag ${r.status}`}>{r.status}</span></td></tr>)}</tbody>
            </table></div>
          )}
        </Card>
        <Security />
      </div>
    </div>
  )
}

function PlaceCard({ p, onChange }: { p: Place; onChange: () => void }) {
  const days = upcoming(p.forecast)
  const today = days[0]
  const [threshold, setThreshold] = useState(150)
  const remove = async () => { if (confirm(`Remove ${p.name}?`)) { await api.del(`/api/me/places/${p.id}`); onChange() } }
  const addAlert = async () => { await api.post('/api/me/alerts', { place_id: p.id, threshold }); onChange() }
  const toggle = async (id: number, active: number) => { await api.patch(`/api/me/alerts/${id}`, { active: !active }); onChange() }
  const dropAlert = async (id: number) => { await api.del(`/api/me/alerts/${id}`); onChange() }
  return (
    <div className="place">
      <div className="place-head"><h3>{p.name}</h3><button className="link danger" onClick={remove}>Remove</button></div>
      {today ? <>
        <div className="mid"><b style={{ color: today.category.colour }}>{fmt(today.forecast)}</b> <Pill cat={today.category} /> <span className="small muted">today · likely {fmt(today.lo)}–{fmt(today.hi)}</span></div>
        <DayStrip days={days} compact />
        <Advice p={today.personal} />
      </> : <Empty>No forecast for this spot.</Empty>}
      <div className="alerts">
        {p.alerts?.map((a) => (
          <div key={a.id} className={`alert-row ${a.active ? '' : 'off'}`}>
            🔔 Warn me at AQI <b>{a.threshold}</b> or higher {a.last_sent && <small className="muted">(last warned for {a.last_sent})</small>}
            <button className="link" onClick={() => toggle(a.id, a.active)}>{a.active ? 'Pause' : 'Resume'}</button>
            <button className="link danger" onClick={() => dropAlert(a.id)}>Delete</button>
          </div>
        ))}
        <div className="alert-row new">
          Alert me when it reaches
          <select value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}>
            <option value={100}>100 (Moderate)</option><option value={150}>150</option><option value={200}>200 (Poor)</option><option value={300}>300 (Very Poor)</option>
          </select>
          <button className="ghost small" onClick={addAlert}>Add alert</button>
        </div>
      </div>
    </div>
  )
}

function AddPlace({ centre, onAdded }: { centre: [number, number]; onAdded: () => void }) {
  const [spot, setSpot] = useState<{ lat: number; lon: number } | null>(null)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const save = async () => {
    try { await api.post('/api/me/places', { name, lat: spot!.lat, lon: spot!.lon }); onAdded() } catch (e) { setError((e as Error).message) }
  }
  return (
    <div className="add-place">
      <AreaMap center={centre} picked={spot} onPick={(lat, lon) => setSpot({ lat, lon })} height={320} />
      <div className="row-form">
        <input placeholder="Name, e.g. Home" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        <button className="btn small" disabled={!spot || !name.trim()} onClick={save}>{spot ? 'Save place' : 'Click the map first'}</button>
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  )
}

function Profile() {
  const { user, status, setUser } = useSession()
  const [health, setHealth] = useState<string[]>(user!.health)
  const [name, setName] = useState(user!.name)
  const [home, setHome] = useState(user!.city)
  const [email, setEmail] = useState(!!user!.email_alerts)
  const [saved, setSaved] = useState('')
  const save = async () => {
    const u = await api.patch<typeof user>('/api/me', { name, city: home, health, email_alerts: email })
    setUser(u)
    setSaved('Saved. Advice across the site now follows your profile.')
  }
  return (
    <Card title={<span id="profile">Profile and health</span>} hint="Used only to tune advice and alert wording. Never shared.">
      <div className="form">
        <label>Name<input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
        <label>Home city<select value={home} onChange={(e) => setHome(e.target.value)}><option>Pune</option><option>Mumbai</option></select></label>
        <fieldset><legend>Does any of this apply to you or your household?</legend>
          {Object.entries(status?.health_groups ?? {}).map(([k, v]) => (
            <label key={k} className="check"><input type="checkbox" checked={health.includes(k)} onChange={(e) => setHealth(e.target.checked ? [...health, k] : health.filter((h) => h !== k))} />{v}</label>
          ))}
        </fieldset>
        <label className="check"><input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} />Also email me alerts (when the server has email set up)</label>
        <button className="btn small" onClick={save}>Save profile</button>
        {saved && <p className="ok small">{saved}</p>}
      </div>
    </Card>
  )
}

function Security() {
  const { user, setUser } = useSession()
  const nav = useNavigate()
  const [pw, setPw] = useState({ current: '', new: '' })
  const [msg, setMsg] = useState('')
  const change = async (e: FormEvent) => {
    e.preventDefault()
    try { await api.post('/api/me/password', pw); setMsg('Password changed. Other devices have been signed out.'); setPw({ current: '', new: '' }) }
    catch (e) { setMsg((e as Error).message) }
  }
  const remove = async () => {
    const password = prompt('This deletes your account, places and alerts for good. Type your password to confirm:')
    if (!password) return
    try { await api.del('/api/me', { email: user!.email, password }); navigator.serviceWorker?.controller?.postMessage('signed-out'); setUser(null); nav('/') } catch (e) { setMsg((e as Error).message) }
  }
  return (
    <Card title="Account and security" hint={`Signed in as ${user!.email}`}>
      <form className="form" onSubmit={change}>
        <input type="email" autoComplete="username" value={user!.email} readOnly hidden />
        <label>Current password<input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></label>
        <label>New password<input type="password" autoComplete="new-password" minLength={8} value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} /></label>
        <button className="ghost small" disabled={!pw.current || pw.new.length < 8}>Change password</button>
        {msg && <p className="small">{msg}</p>}
        <hr />
        <button type="button" className="link danger" onClick={remove}>Delete my account</button>
      </form>
    </Card>
  )
}

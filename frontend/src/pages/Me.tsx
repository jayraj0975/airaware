import qrcode from 'qrcode-generator'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Note, type Place } from '../api'
import AreaMap from '../components/AreaMap'
import { Advice, AskDialog, Card, ConfirmDialog, DayStrip, Dialog, Empty, ErrorBox, Pill, Spinner, toast, useLoad, useTitle } from '../components/ui'
import { useSession } from '../session'
import { dateTime, fmt, upcoming } from '../util'

interface MyReport { id: number; kind: string; note: string; status: string; created_at: string; city: string }

export default function Me() {
  const { user, city, status, refresh } = useSession()
  const places = useLoad(() => api.get<Place[]>('/api/me/places'), [])
  const notes = useLoad(() => api.get<Note[]>('/api/me/notifications'), [])
  const reports = useLoad(() => api.get<MyReport[]>('/api/me/reports'), [])
  const [adding, setAdding] = useState(false)
  useTitle('Your places')

  useEffect(() => {  // links like /me#security land on that section once the page has its content
    const id = location.hash.slice(1)
    if (id) document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [notes.data, places.data])
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
        <Profile key={`${user.health.join()}-${user.health_consent}-${user.city}`} />
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
      <PrivacyCard />
    </div>
  )
}

function PlaceCard({ p, onChange }: { p: Place; onChange: () => void }) {
  const days = upcoming(p.forecast)
  const today = days[0]
  const [threshold, setThreshold] = useState(150)
  const [removing, setRemoving] = useState(false)
  const run = async (action: () => Promise<unknown>, done: string) => {
    try { await action(); toast(done); onChange() } catch (e) { toast((e as Error).message, 'error') }
  }
  const addAlert = () => run(() => api.post('/api/me/alerts', { place_id: p.id, threshold }), `We will warn you when ${p.name} reaches ${threshold}.`)
  const toggle = (id: number, active: number) => run(() => api.patch(`/api/me/alerts/${id}`, { active: !active }), active ? 'Alert paused.' : 'Alert back on.')
  const dropAlert = (id: number) => run(() => api.del(`/api/me/alerts/${id}`), 'Alert deleted.')
  return (
    <div className="place">
      <div className="place-head"><h3>{p.name}</h3><div className="actions">
        <Link className="small" to={`/?lat=${p.lat}&lon=${p.lon}`}>Details</Link>
        <button className="link danger" onClick={() => setRemoving(true)}>Remove</button></div></div>
      {removing && <ConfirmDialog title={`Remove ${p.name}?`} ok="Remove" onClose={() => setRemoving(false)}
        onConfirm={() => run(() => api.del(`/api/me/places/${p.id}`), `${p.name} removed.`)}>Its alerts are deleted too.</ConfirmDialog>}
      {today ? <>
        <div className="mid"><span className="swatch" style={{ background: today.category.colour }} /><b>{fmt(today.forecast)}</b> <Pill cat={today.category} /> <span className="small muted">today · likely {fmt(today.lo)}–{fmt(today.hi)}</span></div>
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
    try { await api.post('/api/me/places', { name, lat: spot!.lat, lon: spot!.lon }); toast(`Saved “${name}”.`); onAdded() } catch (e) { setError((e as Error).message) }
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
  const [consent, setConsent] = useState(user!.health_consent)
  const needsConsent = health.length > 0 && !user!.health_consent
  const save = async () => {
    try {
      const u = await api.patch<typeof user>('/api/me', { name, city: home, health, health_consent: consent || undefined, email_alerts: email })
      setUser(u)
      toast('Profile saved. Advice across the site now follows it.')
    } catch (e) { toast((e as Error).message, 'error') }
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
        {needsConsent && (
          <label className="check health-consent"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>I consent to AirAware using this health information <b>only</b> to tailor advice and alert levels for me. I can erase it any time below. (Optional: you can use everything without it.)</span></label>
        )}
        <label className="check"><input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} />Also email me alerts (when the server has email set up)</label>
        <button className="btn small" disabled={needsConsent && !consent} onClick={save}>Save profile</button>
      </div>
    </Card>
  )
}

function Security() {
  const { user, setUser } = useSession()
  const nav = useNavigate()
  const [pw, setPw] = useState({ current: '', new: '' })
  const [msg, setMsg] = useState('')
  const [deleting, setDeleting] = useState(false)
  const change = async (e: FormEvent) => {
    e.preventDefault()
    try { await api.post('/api/me/password', pw); setMsg(''); toast('Password changed. Other devices have been signed out.'); setPw({ current: '', new: '' }) }
    catch (e) { setMsg((e as Error).message) }
  }
  const remove = async (password: string) => {
    await api.del('/api/me', { email: user!.email, password })
    navigator.serviceWorker?.controller?.postMessage('signed-out')
    setUser(null)
    toast('Your account and everything in it has been deleted.')
    nav('/')
  }
  return (
    <Card title={<span id="security">Account and security</span>} hint={`Signed in as ${user!.email}`}>
      {/* Three separate blocks, never one form around them: Enter in the two-step code box must not submit the
          password change. */}
      <form className="form" onSubmit={change}>
        <input type="email" autoComplete="username" value={user!.email} readOnly hidden />
        <label>Current password<input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></label>
        <label>New password<input type="password" autoComplete="new-password" minLength={8} value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} /></label>
        <button className="ghost small" disabled={!pw.current || pw.new.length < 8}>Change password</button>
        {msg && <p className="small">{msg}</p>}
      </form>
      <hr />
      <TwoStep />
      <hr />
      <button type="button" className="link danger" onClick={() => setDeleting(true)}>Delete my account</button>
      {deleting && <AskDialog title="Delete your account?" label="Your password" type="password" ok="Delete for good" danger
        note="This permanently deletes your account, places, alerts and notifications. Reports you made stay on the map without your name."
        onClose={() => setDeleting(false)} onSubmit={remove} />}
    </Card>
  )
}

function PrivacyCard() {
  const { user, setUser } = useSession()
  const [withdrawing, setWithdrawing] = useState(false)
  const download = async () => {
    try {
      const data = await api.get<unknown>('/api/me/export')
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      Object.assign(document.createElement('a'), { href: url, download: `airaware-my-data-${new Date().toISOString().slice(0, 10)}.json` }).click()
      URL.revokeObjectURL(url)
      toast('Downloaded: everything we hold about you.')
    } catch (e) { toast((e as Error).message, 'error') }
  }
  return (
    <Card title={<span id="privacy">Your data and privacy</span>} hint="Your rights under India's DPDP Act, one click away">
      <div className="privacy-actions">
        <div><b>See everything we hold</b><p className="small muted">A file with your profile, places, alerts, notifications, reports, sign-in sessions and activity log.</p>
          <button className="ghost small" onClick={download}>⤓ Download my data</button></div>
        <div><b>Health information</b><p className="small muted">{user!.health_consent ? `You consented to using your health groups to tailor advice.` : 'You have not shared any health information.'}</p>
          {user!.health_consent && <button className="ghost small" onClick={() => setWithdrawing(true)}>Withdraw consent and erase it</button>}</div>
        <div><b>Questions or complaints</b><p className="small muted">Ask for a correction, raise a grievance or nominate someone to act for you.</p>
          <Link className="small" to="/rights">Contact us about your data →</Link></div>
        <div><b>Leave for good</b><p className="small muted">Deleting your account erases your data. Use “Delete my account” under Account and security.</p>
          <Link className="small" to="/privacy">Read the Privacy Notice →</Link></div>
      </div>
      {withdrawing && <ConfirmDialog title="Erase your health information?" ok="Erase it" onClose={() => setWithdrawing(false)}
        onConfirm={async () => { setUser(await api.del('/api/me/health')); toast('Erased. Advice is back to the general level.') }}>
        Your health groups are deleted straight away and advice goes back to what everyone sees. You can add them again later.
      </ConfirmDialog>}
    </Card>
  )
}

function TwoStep() {
  const { user, setUser } = useSession()
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [turningOff, setTurningOff] = useState(false)
  const [asking, setAsking] = useState(false)
  const start = async (password: string) => { setSetup(await api.post('/api/me/2fa/setup', { password })) }
  const enable = async () => {
    try { setUser(await api.post('/api/me/2fa/enable', { code })); setSetup(null); setCode(''); toast('Two-step sign-in is on. You will need a code each time you sign in.') }
    catch (e) { toast((e as Error).message, 'error') }
  }
  const qr = useMemo(() => {
    if (!setup) return ''
    const q = qrcode(0, 'M')
    q.addData(setup.uri)
    q.make()
    return q.createDataURL(5, 2)
  }, [setup])
  if (user!.two_step) return (
    <div className="two-step on">
      <b>✓ Two-step sign-in is on</b>
      <p className="small muted">Signing in needs your password and a code from your authenticator app.</p>
      <button type="button" className="link danger" onClick={() => setTurningOff(true)}>Turn it off</button>
      {turningOff && <TurnOff onClose={() => setTurningOff(false)} />}
    </div>
  )
  return (
    <div className="two-step">
      <b>Two-step sign-in</b>
      <p className="small muted">Adds a 6-digit code from an app like Google Authenticator or Authy, so a stolen password alone is not enough.{user!.role === 'admin' ? ' Required for the admin console.' : ''}</p>
      {asking && <AskDialog title="Confirm it's you" label="Your password" type="password" ok="Continue"
        note="Setting up two-step sign-in changes how you sign in, so we check your password first." onClose={() => setAsking(false)} onSubmit={start} />}
      {!setup ? <button type="button" className="ghost small" onClick={() => setAsking(true)}>Set up two-step sign-in</button> : (
        <div className="two-step-setup">
          <img src={qr} alt="QR code to scan with your authenticator app" width={180} height={180} />
          <div>
            <p className="small">1. Scan this with your authenticator app, or <a href={setup.uri}>open it on this phone</a>, or type this key:</p>
            <code className="key">{setup.secret.match(/.{1,4}/g)!.join(' ')}</code>
            <p className="small">2. Enter the 6-digit code it shows:</p>
            <form className="row-form" onSubmit={(e) => { e.preventDefault(); if (code.replace(/\D/g, '').length === 6) enable() }}>
              <input inputMode="numeric" autoComplete="one-time-code" maxLength={7} placeholder="123 456" aria-label="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
              <button className="btn small" disabled={code.replace(/\D/g, '').length !== 6}>Turn on</button></form>
          </div>
        </div>
      )}
    </div>
  )
}

function TurnOff({ onClose }: { onClose: () => void }) {
  const { setUser } = useSession()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  return (
    <Dialog title="Turn off two-step sign-in?" onClose={onClose}>
      <form className="form" onSubmit={async (e) => {
        e.preventDefault()
        try { setUser(await api.post('/api/me/2fa/disable', { password, code })); toast('Two-step sign-in is off.'); onClose() } catch (err) { setError((err as Error).message) }
      }}>
        <p className="small muted">Your account will be protected by your password alone.</p>
        <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <label>Current code<input inputMode="numeric" autoComplete="one-time-code" required maxLength={7} value={code} onChange={(e) => setCode(e.target.value)} /></label>
        {error && <div className="error">{error}</div>}
        <div className="actions end"><button type="button" className="ghost small" onClick={onClose}>Cancel</button><button className="btn small danger-btn">Turn off</button></div>
      </form>
    </Dialog>
  )
}

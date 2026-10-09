import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Area, type Overview, type Report, type Station } from '../api'
import AreaMap from '../components/AreaMap'
import { ForecastChart, HourBars, WeatherChart } from '../components/charts'
import { Advice, AqiHero, Card, DayStrip, Empty, ErrorBox, Pill, Spinner, useLoad } from '../components/ui'
import { useSession } from '../session'
import { compass, dayName, fmt, hourName, shortDate, upcoming, WEATHER } from '../util'

export default function Home() {
  const { city, status } = useSession()
  const ov = useLoad(() => api.get<Overview>(`/api/overview?city=${encodeURIComponent(city)}`), [city])
  const st = useLoad(() => api.get<{ source: string; stations: Station[] }>(`/api/stations?city=${encodeURIComponent(city)}`), [city])
  const rp = useLoad(() => api.get<Report[]>(`/api/reports?city=${encodeURIComponent(city)}`), [city])
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(null)
  const centre = status?.cities[city]

  return (
    <div className="page">
      {ov.error ? <ErrorBox error={ov.error} /> : !ov.data ? <div className="hero-grid"><div className="skeleton big" /><div className="skeleton" /><div className="skeleton" /></div> : <Hero o={ov.data} />}

      {ov.data && ov.data.hours.length > 0 && (
        <Card title={`${dayName(upcoming(ov.data.forecast)[0].date)}, hour by hour`}
          hint={`The day's forecast spread over the usual daily pattern for ${city} in this month. Outlined bar: now. Cleanest waking hours: ${ov.data.plan.best_hours.map(hourName).join(', ')}.`}>
          <HourBars hours={ov.data.hours} />
        </Card>
      )}

      <div className="map-row">
        <Card title="Pick any area" hint="Click anywhere, or use your location. Dots are CPCB stations; dashed orange dots are pollution reported by people.">
          {centre && <AreaMap center={[centre.lat, centre.lon]} stations={st.data?.stations} reports={rp.data ?? []} picked={picked} onPick={(lat, lon) => setPicked({ lat, lon })} />}
          <Legend />
        </Card>
        <AreaPanel picked={picked} onReported={rp.reload} />
      </div>

      {ov.data && (
        <div className="grid two">
          <Card title="The last six weeks and the week ahead" hint={`Forecast from the last reading on ${shortDate(ov.data.measured.date)}, with the 80% range`}>
            <ForecastChart history={ov.data.history} forecast={ov.data.forecast} />
            <DayStrip days={upcoming(ov.data.forecast)} />
          </Card>
          <Card title="Weather, next 48 hours" hint="Live from Open-Meteo">
            {ov.data.weather ? <WeatherChart w={ov.data.weather} /> : <Empty>Weather is unavailable right now.</Empty>}
            <p className="muted small">Mixing height is how deep the layer of air is that pollution spreads into. When it is low and the wind is still, particles pile up near the ground: that is why nights and winter mornings are the worst.</p>
          </Card>
        </div>
      )}

      <Card title={`Stations in ${city}`} hint={st.data?.source === 'live' ? 'Live 24-hour averages' : "Each station's latest day in the public archive"}>
        {st.loading ? <Spinner /> : st.data && <StationTable rows={st.data.stations} />}
      </Card>
    </div>
  )
}

function Hero({ o }: { o: Overview }) {
  const { user } = useSession()
  const days = upcoming(o.forecast)
  const today = days[0]
  const tomorrow = days[1]
  const w = o.weather?.current
  return (
    <div className="hero-grid">
      <AqiHero label={<>{o.city} · {dayName(today.date)} · AirAware forecast</>} value={today.forecast} cat={today.category}
        sub={<>Likely {fmt(today.lo)}–{fmt(today.hi)} · {today.days_ahead} day{today.days_ahead > 1 ? 's' : ''} after the last reading · chance of Poor or worse {Math.round(today.p_poor * 100)}%</>}>
        <Advice p={today.personal} />
        {!user && <div className="hint-on-colour"><Link to="/signup">Create a free account</Link> for advice tuned to your health and alerts for your places.</div>}
      </AqiHero>
      <div className="card stack">
        <span className="muted small">Tomorrow</span>
        {tomorrow ? <div className="mid"><b style={{ color: tomorrow.category.colour }}>{fmt(tomorrow.forecast)}</b> <Pill cat={tomorrow.category} /></div> : <div>–</div>}
        {tomorrow && <span className="small">Likely {fmt(tomorrow.lo)}–{fmt(tomorrow.hi)}</span>}
        <div className="row"><span>Cleanest day ahead</span><b>{dayName(o.plan.best_day)} ({fmt(o.plan.best_day_aqi)})</b></div>
        <div className="row"><span>Cleanest hours</span><b>{o.plan.best_hours.map(hourName).join(', ')}</b></div>
        <div className="row"><span>Last measured {shortDate(o.measured.date)}</span><b>{fmt(o.measured.aqi)} <Pill cat={o.measured.category} /></b></div>
        <div className="row"><span>Main pollutant then</span><b>{o.measured.dominant}</b></div>
      </div>
      <div className="card stack">
        <span className="muted small">Weather now{w ? ` · ${new Date(w.time).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}` : ''}</span>
        <div className="mid"><b>{w ? `${fmt(w.temperature_2m)}°C` : '–'}</b></div>
        <span className="small">{w ? `${WEATHER[w.weather_code] ?? ''} · feels like ${fmt(w.apparent_temperature)}°C` : 'Weather unavailable'}</span>
        <div className="row"><span>Humidity</span><b>{w ? `${fmt(w.relative_humidity_2m)}%` : '–'}</b></div>
        <div className="row"><span>Wind</span><b>{w ? `${fmt(w.wind_speed_10m)} km/h from ${compass(w.wind_direction_10m)}` : '–'}</b></div>
        <div className="row"><span>Breathing the last measured day</span><b>≈ {fmt(o.measured.cigarettes, 1)} cigarettes</b></div>
      </div>
    </div>
  )
}

function Legend() {
  const { status } = useSession()
  return <div className="legend">{status?.categories.map((c) => <span key={c.name}><i style={{ background: c.colour }} />{c.name}</span>)}<span><i className="dashed" />Reported source</span></div>
}

function AreaPanel({ picked, onReported }: { picked: { lat: number; lon: number } | null; onReported: () => void }) {
  const { user, refresh } = useSession()
  const area = useLoad(() => (picked ? api.get<Area>(`/api/area?lat=${picked.lat}&lon=${picked.lon}`) : Promise.resolve(null)), [picked?.lat, picked?.lon])
  const [msg, setMsg] = useState('')
  if (!picked) return (
    <Card title="Your area" className="area">
      <p className="muted">Click a spot on the map to see its estimated air quality, its forecast for the coming days, the weather there right now, nearby stations and anything people have reported.</p>
      <ul className="features"><li>📍 Any street in Pune or Mumbai</li><li>📅 Forecast up to a week ahead</li><li>🔔 <Link to="/signup">Save places and get alerts</Link></li></ul>
    </Card>
  )
  if (area.loading) return <Card title="Your area" className="area"><Spinner label="Looking up this spot…" /></Card>
  if (area.error || !area.data) return <Card title="Your area" className="area"><ErrorBox error={area.error ?? 'Nothing here'} /></Card>
  const a = area.data
  const save = async () => {
    const name = prompt('Name this place (e.g. Home, Office, School):', a.place.split(',')[0] || 'My place')
    if (!name) return
    try { await api.post('/api/me/places', { name, lat: a.lat, lon: a.lon }); setMsg(`Saved “${name}”. Set an alert for it on your dashboard.`); refresh() }
    catch (e) { setMsg((e as Error).message) }
  }
  return (
    <Card title="Your area" className="area">
      <h3>{a.place || `${a.lat.toFixed(3)}, ${a.lon.toFixed(3)}`}</h3>
      <div className="muted small">{a.city} · {a.lat.toFixed(4)}, {a.lon.toFixed(4)}</div>
      <AqiHero label={<>{dayName(a.today.date)} · forecast for this area</>} value={a.today.forecast} cat={a.today.category}
        sub={<>Likely {fmt(a.today.lo)}–{fmt(a.today.hi)} · {Math.abs(a.measured.offset) < 1 ? 'about the same as' : `${fmt(Math.abs(a.measured.offset))} ${a.measured.offset > 0 ? 'above' : 'below'}`} the city average</>} />
      <DayStrip days={upcoming(a.forecast)} compact />
      <Advice p={a.today.personal} />
      {a.hours.length > 0 && <HourBars hours={a.hours} small />}
      <p className="small">Cleanest hours this month: <b>{a.best_hours.map(hourName).join(', ')}</b></p>
      {a.weather && (
        <div className="wx">
          <div><b>{fmt(a.weather.current.temperature_2m)}°C</b>{WEATHER[a.weather.current.weather_code] ?? 'now'}</div>
          <div><b>{fmt(a.weather.current.relative_humidity_2m)}%</b>humidity</div>
          <div><b>{fmt(a.weather.current.wind_speed_10m)}</b>km/h {compass(a.weather.current.wind_direction_10m)}</div>
        </div>
      )}
      <p className="small muted">Last measured here (from {a.measured.used} station{a.measured.used > 1 ? 's' : ''} within 12 km): <b>{fmt(a.measured.aqi)}</b>, {a.measured.category.name}</p>
      <ul className="near">{a.measured.nearest.map((n) => <li key={n.station}>{n.station}: <b>{fmt(n.aqi)}</b> · {n.km} km</li>)}</ul>
      {a.reports.length > 0 && <p className="small warn">⚠ {a.reports.length} pollution report{a.reports.length > 1 ? 's' : ''} within 3 km this week: {[...new Set(a.reports.map((r) => r.label.toLowerCase()))].join(', ')}.</p>}
      {user ? (
        <div className="actions">
          <button className="btn small" onClick={save}>★ Save this place</button>
          <ReportButton lat={a.lat} lon={a.lon} onDone={(m) => { setMsg(m); onReported() }} />
        </div>
      ) : <p className="small"><Link to="/signup">Sign up</Link> to save this place, get alerts and report pollution.</p>}
      {msg && <p className="small ok">{msg}</p>}
    </Card>
  )
}

function ReportButton({ lat, lon, onDone }: { lat: number; lon: number; onDone: (msg: string) => void }) {
  const { status } = useSession()
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('burning')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  if (!open) return <button className="ghost small" onClick={() => setOpen(true)}>⚑ Report pollution here</button>
  const send = async () => {
    setBusy(true)
    try { await api.post('/api/reports', { lat, lon, kind, note }); onDone('Thanks! Your report will show on the map once a moderator approves it.'); setOpen(false); setNote('') }
    catch (e) { onDone((e as Error).message) }
    finally { setBusy(false) }
  }
  return (
    <div className="report-form">
      <select value={kind} onChange={(e) => setKind(e.target.value)}>
        {Object.entries(status?.report_kinds ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={280} placeholder="What did you see? (optional)" />
      <div className="actions"><button className="btn small" disabled={busy} onClick={send}>Send report</button><button className="ghost small" onClick={() => setOpen(false)}>Cancel</button></div>
    </div>
  )
}

export function StationTable({ rows }: { rows: Station[] }) {
  const sorted = [...rows].sort((a, b) => b.aqi - a.aqi)
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Station</th><th>Day</th><th className="num">AQI</th><th>Category</th><th className="num">PM2.5</th><th className="num">PM10</th><th>Reliability</th></tr></thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.station}>
              <td>{r.station}</td><td>{r.date}</td><td className="num"><b>{fmt(r.aqi)}</b></td><td><Pill cat={r.category} /></td>
              <td className="num">{fmt(r.pm25)}</td><td className="num">{fmt(r.pm10)}</td>
              <td className={r.verdict && r.verdict !== 'Agrees with the city' ? 'warn' : 'muted'} title={`Correlation with the city over 90 days: ${fmt(r.correlation, 2)}`}>{r.verdict ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

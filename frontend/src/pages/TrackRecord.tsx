import { api } from '../api'
import { Card, Empty, ErrorBox, Spinner, Stat, useLoad, useTitle } from '../components/ui'
import { useSession } from '../session'
import { colourOf, fmt, shortDate } from '../util'

interface Track {
  scored: number; pending: number
  horizons: { h: number; n: number; mae: number; persistence_mae: number; coverage: number }[]
  recent: { city: string; made_from: string; target: string; days_ahead: number; forecast: number; lo: number; hi: number; persistence: number; actual: number }[]
}

export default function TrackRecord() {
  const { city } = useSession()
  useTitle(`Track record · ${city}`)
  const { data, error } = useLoad(() => api.get<Track>(`/api/track-record?city=${encodeURIComponent(city)}`), [city])
  if (error) return <div className="page"><ErrorBox error={error} /></div>
  if (!data) return <div className="page"><Spinner /></div>
  const all = data.horizons.reduce((s, h) => ({ n: s.n + h.n, err: s.err + h.mae * h.n, base: s.base + h.persistence_mae * h.n }), { n: 0, err: 0, base: 0 })
  return (
    <div className="page">
      <div className="page-head">
        <h1>Track record · {city}</h1>
        <p className="muted">Every forecast this site publishes is logged before the day happens and scored against the real AQI once the stations report it. No back-filling, no cherry-picking. The model's offline test is on the <a href="/science">Science</a> page; this is how it does live.</p>
      </div>
      <div className="stats">
        <Stat label="Forecasts scored" value={fmt(data.scored)} sub={`${fmt(data.pending)} waiting for their day`} />
        <Stat label="Live average error" value={all.n ? `${fmt(all.err / all.n, 1)} AQI` : '–'} sub={all.n ? `vs ${fmt(all.base / all.n, 1)} for the last reading` : 'scores appear as days are measured'} />
      </div>
      {data.scored === 0 ? (
        <Card><Empty>No forecast has been scored yet. Forecasts are scored once the station archive reports their day, usually four to five days later. {fmt(data.pending)} forecasts are waiting.</Empty></Card>
      ) : (
        <div className="grid two">
          <Card title="By days ahead">
            <div className="table-wrap"><table>
              <thead><tr><th>Days ahead</th><th className="num">Forecasts</th><th className="num">AirAware error</th><th className="num">Last-reading error</th><th className="num">Inside 80% range</th></tr></thead>
              <tbody>{data.horizons.map((h) => (
                <tr key={h.h}><td>{h.h}</td><td className="num">{h.n}</td><td className="num"><b>{fmt(h.mae, 1)}</b></td><td className="num">{fmt(h.persistence_mae, 1)}</td><td className="num">{fmt(h.coverage * 100)}%</td></tr>
              ))}</tbody>
            </table></div>
          </Card>
          <Card title="Recent forecasts against reality">
            <div className="table-wrap"><table>
              <thead><tr><th>For</th><th className="num">Ahead</th><th className="num">Forecast</th><th className="num">Actual</th><th className="num">Error</th></tr></thead>
              <tbody>{data.recent.slice(0, 30).map((r) => (
                <tr key={`${r.made_from}${r.target}`}>
                  <td>{shortDate(r.target)}</td><td className="num">{r.days_ahead}</td>
                  <td className="num">{fmt(r.forecast)} <small className="muted">({fmt(r.lo)}–{fmt(r.hi)})</small></td>
                  <td className="num"><span className="dot" style={{ background: colourOf(r.actual) }} />{fmt(r.actual)}</td>
                  <td className={`num ${r.actual < r.lo || r.actual > r.hi ? 'warn' : ''}`}>{fmt(r.forecast - r.actual)}</td>
                </tr>
              ))}</tbody>
            </table></div>
          </Card>
        </div>
      )}
    </div>
  )
}

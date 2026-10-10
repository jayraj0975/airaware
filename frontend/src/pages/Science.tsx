import { api } from '../api'
import { HBar, LineChart } from '../components/charts'
import { Card, ErrorBox, Spinner, Stat, useLoad, useTitle } from '../components/ui'
import { fmt } from '../util'

interface Model {
  test_from: string; forecasts: number; airaware: string; persistence: string; history_only: string; optimistic: string; vintage: boolean
  table: { Method: string; MAE: number; RMSE: number; R2: number; category_accuracy: number; poor_recall: number }[]
  by_city: { Method: string; Pune: number; Mumbai: number }[]
  dm: { statistic: number; p: number; text: string }
  dm_history: { statistic: number; p: number; text: string }
  horizons: { h: number; Method: string; MAE: number; coverage: number | null; dm_p: number | null; Forecasts: number }[]
  importance: { feature: string; value: number }[]
}

const WX: Record<string, string> = { temp: 'temperature', humidity: 'humidity', rain: 'rain', wind: 'wind speed', wind_u: 'east-west wind', wind_v: 'north-south wind', pressure: 'air pressure' }
const NAMES: Record<string, string> = {
  aqi: "Today's AQI", aqi_7d: "Last 7 days' AQI", aqi_lag1: "Yesterday's AQI", aqi_lag2: 'AQI two days ago', pm10: "Today's PM10", pm25: "Today's PM2.5",
  doy_cos: 'Season', doy_sin: 'Season', weekday: 'Day of week', diwali: 'Diwali week', mumbai: 'City',
  ...Object.fromEntries(Object.entries(WX).flatMap(([k, v]) => [[`fc_today_${k}`, `Today's ${v} (forecast)`], [`fc_target_${k}`, `Target-day ${v} (forecast)`]])),
}
const pValue = (p: number | null | undefined) => (p == null ? '' : p < 0.001 ? 'p < 0.001' : `p = ${p.toFixed(3)}`)
const verdict = (p: number | null | undefined) => (p != null && p < 0.05 ? `significant, ${pValue(p)}` : `not significant, ${pValue(p)}`)

export default function Science() {
  useTitle('The science')
  const { data: m, error } = useLoad(() => api.get<Model>('/api/model'), [])
  if (error) return <div className="page"><ErrorBox error={error} /></div>
  if (!m) return <div className="page"><Spinner /></div>
  const short = (name: string) => ({ [m.airaware]: 'AirAware', [m.persistence]: 'Tomorrow = today', [m.history_only]: 'Station history only', [m.optimistic]: 'Upper bound (realized weather + CAMS)' } as Record<string, string>)[name] ?? name
  const ours = m.table.find((r) => r.Method === m.airaware)!
  const base = m.table.find((r) => r.Method === m.persistence)!
  const hz = (name: string) => m.horizons.filter((h) => h.Method === name).sort((a, b) => a.h - b.h)
  const mine = hz(m.airaware)
  const cov = mine.map((h) => h.coverage ?? 0)
  const at = (name: string, h: number) => hz(name).find((x) => x.h === h)
  const far = mine.length >= 5 ? 5 : mine.length
  const farOurs = at(m.airaware, far), farBase = at(m.persistence, far)
  const sigDays = mine.filter((h) => h.dm_p != null && h.dm_p < 0.05).map((h) => h.h)
  return (
    <div className="page">
      <div className="page-head">
        <h1>The science</h1>
        <p className="muted">How AirAware forecasts, and how well it really does. Every number here comes from a walk-forward test: each month since {new Date(m.test_from).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}, the models were retrained on earlier data only and then forecast that month, {m.forecasts} next-day forecasts in all, every method on exactly the same days.</p>
      </div>
      <div className="stats">
        <Stat label="Average error, next day" value={`${fmt(ours.MAE, 1)} AQI`} sub={`vs ${fmt(base.MAE, 1)} for "tomorrow = today"`} />
        <Stat label="Next day vs the naive forecast" value={`${fmt((1 - ours.MAE / base.MAE) * 100)}% lower`} sub={verdict(m.dm.p)} />
        {farOurs && farBase && <Stat label={`${far} days ahead`} value={`${fmt((1 - farOurs.MAE / farBase.MAE) * 100)}% lower`} sub={verdict(farOurs.dm_p)} />}
        <Stat label="80% ranges that held" value={`${fmt(Math.min(...cov) * 100)}–${fmt(Math.max(...cov) * 100)}%`} sub="across 1 to 7 days ahead" />
      </div>
      <Card title="How we keep the test honest">
        <p>A backtest is only fair if every input was really available on the evening the forecast was made. Weather records such as ERA5, and the CAMS particle analysis, are only known <i>afterwards</i>, and they are more accurate than the forecasts anyone had on the day. Feeding them to a backtest makes a model look better than it can be live.</p>
        <ul>
          <li><b>AirAware</b>, the model the site serves, uses the stations' history and {m.vintage ? <>weather <b>as it was actually forecast</b>, from Open-Meteo's archive of past forecast runs, each issued at least a day before the forecast is made (station history only at 7 days ahead, where no archived run is old enough)</> : <>station history only (the archive of issued forecasts was not available)</>}.</li>
          <li><b>Station history only</b> uses no weather and no CAMS at all: the most conservative benchmark. Next day it is {fmt((1 - (m.table.find((r) => r.Method === m.history_only)?.MAE ?? base.MAE) / base.MAE) * 100)}% better than "tomorrow = today" ({verdict(m.dm_history.p)}).</li>
          <li><b>Upper bound</b> adds the realized weather and the CAMS analysis for the target day. CAMS keeps no archive of its past forecasts, so this can only show a ceiling, never live accuracy.</li>
        </ul>
        <p className="small muted">The honest result: next day, AirAware is only slightly better than repeating today's reading{m.dm.p >= 0.05 ? ', and the difference is not statistically significant' : ''}. Its lead grows with the horizon{sigDays.length ? <> and is significant (Diebold-Mariano, p &lt; 0.05) at {sigDays.join(', ')} days ahead</> : ''}.</p>
      </Card>
      <div className="grid two">
        <Card title="Next day, against simpler methods" hint="Lower error is better">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Method</th><th className="num">Avg error</th><th className="num">R²</th><th className="num">Right category</th><th className="num">Poor days caught</th></tr></thead>
              <tbody>{[...m.table].sort((a, b) => a.MAE - b.MAE).map((r) => (
                <tr key={r.Method} className={r.Method === m.airaware ? 'best' : r.Method === m.optimistic ? 'muted' : ''}>
                  <td>{short(r.Method)}</td><td className="num">{fmt(r.MAE, 1)}</td><td className="num">{fmt(r.R2, 3)}</td>
                  <td className="num">{fmt(r.category_accuracy * 100)}%</td><td className="num">{fmt(r.poor_recall * 100)}%</td>
                </tr>))}
              </tbody>
            </table>
          </div>
          <p className="small muted">The upper bound uses information nobody has on the day; it is shown only to measure what perfect weather and particle forecasts would add.</p>
        </Card>
        <Card title="Further ahead" hint="Average error by days ahead">
          <LineChart labels={mine.map((h) => `${h.h} day${h.h > 1 ? 's' : ''}`)} yTitle="Average error (AQI points)"
            series={[{ label: 'AirAware', data: mine.map((h) => h.MAE), colour: '#0f6b5c' },
              { label: 'Station history only', data: hz(m.history_only).map((h) => h.MAE), colour: '#6f8f86' },
              { label: 'Tomorrow = today', data: hz(m.persistence).map((h) => h.MAE), colour: '#9aa0a6', dash: true },
              { label: 'Upper bound (not live)', data: hz(m.optimistic).map((h) => h.MAE), colour: '#c9ccd0', dash: true }]} />
          <p className="small">Repeating today's reading gets worse quickly as the days pass; AirAware falls back on the season and the weather forecast, so its lead grows with the horizon.</p>
        </Card>
        <Card title="What the model relies on" hint="Extra error when each input is shuffled so the model cannot use it">
          <HBar labels={m.importance.map((i) => NAMES[i.feature] ?? i.feature)} values={m.importance.map((i) => i.value)} xTitle="AQI points" />
        </Card>
        <Card title="How it works">
          <ol className="steps">
            <li><b>Collect.</b> 15-minute PM2.5 and PM10 from 37 CPCB monitors (14 in Pune and Pimpri-Chinchwad, 23 in Mumbai) via the OpenAQ archive; weather forecasts, and the archive of past forecast runs, from Open-Meteo.</li>
            <li><b>Clean.</b> Drop instrument error codes, stuck sensors and impossible readings (PM2.5 above PM10); a day needs 16 valid hours (CPCB's rule) and a city needs two stations.</li>
            <li><b>Model.</b> Ridge regression predicts the <i>change</i> from today's AQI, one model per horizon from 1 to 7 days. AQI moves slowly, so learning the change beats learning the level. It is trained on forecasts as they were issued, the same kind of input it gets live.</li>
            <li><b>Uncertainty.</b> The 80% range and the chance of a Poor day come from the model's own past out-of-sample errors (split conformal prediction).</li>
            <li><b>Any area.</b> A spot's estimate is an inverse-distance-weighted average of stations within 12 km; its forecast is the city forecast shifted by how the spot compares with the city.</li>
            <li><b>Stay honest.</b> Every forecast the site publishes is logged and scored when the real AQI arrives: see the <a href="/track-record">track record</a>.</li>
          </ol>
          <p className="small muted">Limits: the public archive runs a few days behind, so "tomorrow" is usually a 5-day forecast from the last reading; area estimates cannot see a source between stations; the AQI uses PM only; about a year of test data.</p>
        </Card>
      </div>
    </div>
  )
}

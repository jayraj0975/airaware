import { api } from '../api'
import { HBar, LineChart } from '../components/charts'
import { Card, ErrorBox, Spinner, Stat, useLoad } from '../components/ui'
import { fmt } from '../util'

interface Model {
  test_from: string; forecasts: number; airaware: string; persistence: string
  table: { Method: string; MAE: number; RMSE: number; R2: number; category_accuracy: number; poor_recall: number }[]
  by_city: { Method: string; Pune: number; Mumbai: number }[]
  dm: { statistic: number; p: number; text: string }
  horizons: { h: number; Method: string; MAE: number; coverage: number | null; Forecasts: number }[]
  importance: { feature: string; value: number }[]
}

const NAMES: Record<string, string> = {
  aqi: "Today's AQI", temp: "Today's temperature", temp_next: 'Target-day temperature', humidity: "Today's humidity", humidity_next: 'Target-day humidity',
  cams_pm25: 'CAMS PM2.5 today', cams_pm10: 'CAMS PM10 today', cams_pm25_next: 'CAMS PM2.5 forecast', cams_pm10_next: 'CAMS PM10 forecast',
  blh: "Today's mixing height", blh_next: 'Target-day mixing height', aqi_7d: "Last 7 days' AQI", wind_u_next: 'Target-day east-west wind',
  pm10: "Today's PM10", pm25: "Today's PM2.5", aqi_lag1: "Yesterday's AQI", rain_next: 'Target-day rain', wind_next: 'Target-day wind',
  wind_v_next: 'Target-day north-south wind', pressure_next: 'Target-day pressure', doy_cos: 'Season', doy_sin: 'Season', mumbai: 'City',
}
const short = (m: string) => m.replace('AirAware: linear regression on the change', 'AirAware').replace('Persistence (tomorrow = today)', 'Tomorrow = today')

export default function Science() {
  const { data: m, error } = useLoad(() => api.get<Model>('/api/model'), [])
  if (error) return <div className="page"><ErrorBox error={error} /></div>
  if (!m) return <div className="page"><Spinner /></div>
  const ours = m.table.find((r) => r.Method === m.airaware)!
  const base = m.table.find((r) => r.Method === m.persistence)!
  const hz = (name: string) => m.horizons.filter((h) => h.Method === name).sort((a, b) => a.h - b.h)
  const cov = hz(m.airaware).map((h) => h.coverage ?? 0)
  return (
    <div className="page">
      <div className="page-head">
        <h1>The science</h1>
        <p className="muted">How AirAware forecasts, and how we know it works. Every number here comes from a walk-forward test: each month since {new Date(m.test_from).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}, the models were retrained on earlier data only and then forecast that month, {m.forecasts} next-day forecasts in all.</p>
      </div>
      <div className="stats">
        <Stat label="Average error, next day" value={`${fmt(ours.MAE, 1)} AQI`} sub={`vs ${fmt(base.MAE, 1)} for "tomorrow = today"`} />
        <Stat label="Better than the naive forecast" value={`${fmt((1 - ours.MAE / base.MAE) * 100)}%`} sub={`Diebold-Mariano ${m.dm.text}`} />
        <Stat label="Right AQI category" value={`${fmt(ours.category_accuracy * 100)}%`} sub={`vs ${fmt(base.category_accuracy * 100)}%`} />
        <Stat label="80% ranges that held" value={`${fmt(Math.min(...cov) * 100)}–${fmt(Math.max(...cov) * 100)}%`} sub="honest, slightly cautious" />
      </div>
      <div className="grid two">
        <Card title="Next day, against simpler methods" hint="Lower error is better">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Method</th><th className="num">Avg error</th><th className="num">R²</th><th className="num">Right category</th><th className="num">Poor days caught</th></tr></thead>
              <tbody>{[...m.table].sort((a, b) => a.MAE - b.MAE).map((r) => (
                <tr key={r.Method} className={r.Method === m.airaware ? 'best' : ''}>
                  <td>{short(r.Method)}</td><td className="num">{fmt(r.MAE, 1)}</td><td className="num">{fmt(r.R2, 3)}</td>
                  <td className="num">{fmt(r.category_accuracy * 100)}%</td><td className="num">{fmt(r.poor_recall * 100)}%</td>
                </tr>))}
              </tbody>
            </table>
          </div>
          <p className="small muted">"Without CAMS" and "without tomorrow's forecasts" are the same model with inputs removed: they show what each input adds.</p>
        </Card>
        <Card title="Further ahead" hint="Average error by days ahead">
          <LineChart labels={hz(m.airaware).map((h) => `${h.h} day${h.h > 1 ? 's' : ''}`)} yTitle="Average error (AQI points)"
            series={[{ label: 'AirAware', data: hz(m.airaware).map((h) => h.MAE), colour: '#2563eb' },
              { label: 'Last reading repeated', data: hz(m.persistence).map((h) => h.MAE), colour: '#94a3b8', dash: true }]} />
          <p className="small">The gap widens with the horizon: the further ahead, the more the weather and CAMS forecasts matter.</p>
        </Card>
        <Card title="What the model relies on" hint="Extra error when each input is shuffled so the model cannot use it">
          <HBar labels={m.importance.map((i) => NAMES[i.feature] ?? i.feature)} values={m.importance.map((i) => i.value)} xTitle="AQI points" />
        </Card>
        <Card title="How it works">
          <ol className="steps">
            <li><b>Collect.</b> 15-minute PM2.5 and PM10 from 37 CPCB monitors (14 in Pune and Pimpri-Chinchwad, 23 in Mumbai) via the OpenAQ archive; ERA5 weather and forecasts from Open-Meteo; Copernicus CAMS particle analyses and forecasts.</li>
            <li><b>Clean.</b> Drop instrument error codes, stuck sensors and impossible readings (PM2.5 above PM10); a day needs 16 valid hours (CPCB's rule) and a city needs two stations.</li>
            <li><b>Model.</b> Ridge regression predicts the <i>change</i> from today's AQI, one model per horizon from 1 to 7 days. AQI moves slowly, so learning the change beats learning the level.</li>
            <li><b>Uncertainty.</b> The 80% range and the chance of a Poor day come from the model's own past errors (split conformal prediction).</li>
            <li><b>Any area.</b> A spot's estimate is an inverse-distance-weighted average of stations within 12 km; its forecast is the city forecast shifted by how the spot compares with the city.</li>
            <li><b>Stay honest.</b> Every forecast the site publishes is logged and scored when the real AQI arrives: see the <a href="/track-record">track record</a>.</li>
          </ol>
          <p className="small muted">Limits: the public archive runs a few days behind, so "tomorrow" is usually a 5-day forecast from the last reading; area estimates cannot see a source between stations; the AQI uses PM only.</p>
        </Card>
      </div>
    </div>
  )
}

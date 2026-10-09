import { api } from '../api'
import { Bars, LineChart, SeasonChart } from '../components/charts'
import { Card, ErrorBox, Spinner, useLoad, useTitle } from '../components/ui'
import { useSession } from '../session'
import { colourOf, fmt, heat, hourName, MONTHS, WEEKDAYS } from '../util'

interface Insights {
  hourly: { month: number; hour: number; aqi: number; pm25: number; pm10: number }[]
  diwali: { curve: { offset: number; change: number }[]; years: number[] }
  pm25_share: { month: number; share: number }[]; monthly: { month: number; aqi: number }[]
  weekday: { day: number; aqi: number }[]; cigarettes_year: number | null; days: number; since: string
}

export default function Explore() {
  const { city } = useSession()
  useTitle(`Insights · ${city}`)
  const { data, error } = useLoad(() => api.get<Insights>(`/api/insights?city=${encodeURIComponent(city)}`), [city])
  if (error) return <div className="page"><ErrorBox error={error} /></div>
  if (!data) return <div className="page"><Spinner /></div>
  const cell = new Map(data.hourly.map((h) => [`${h.month}-${h.hour}`, h]))
  const vals = data.hourly.map((h) => h.aqi)
  const winter = data.hourly.filter((h) => [11, 12, 1].includes(h.month))
  const byHour = (hs: typeof winter) => [...Array(24).keys()].map((hr) => { const x = hs.filter((h) => h.hour === hr); return x.reduce((s, h) => s + h.aqi, 0) / (x.length || 1) })
  const winterHours = byHour(winter)
  const worst = winterHours.indexOf(Math.max(...winterHours)), best = winterHours.indexOf(Math.min(...winterHours.slice(6, 22)))
  const peak = data.diwali.curve.reduce((m, c) => (c.change > m.change ? c : m), { offset: 0, change: -Infinity })

  return (
    <div className="page">
      <div className="page-head"><h1>Insights · {city}</h1><p className="muted">What {fmt(data.days)} days of station readings since {new Date(data.since).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })} say about {city}'s air.</p></div>
      <div className="grid two">
        <Card title="When in the day is the air cleanest?" hint="Every hour of every month since January 2025, from all the stations. Greener is cleaner.">
          <div className="heatmap">
            <div className="lbl" />
            {[...Array(24).keys()].map((h) => <div key={`h${h}`} className="lbl">{h % 3 === 0 ? h : ''}</div>)}
            {MONTHS.map((m, i) => [
              <div key={m} className="lbl">{m}</div>,
              ...[...Array(24).keys()].map((h) => {
                const c = cell.get(`${i + 1}-${h}`)
                return <div key={`${m}${h}`} title={c ? `${m} ${hourName(h)}: AQI ${fmt(c.aqi)}` : ''} style={{ background: c ? heat(c.aqi) : 'transparent' }} />
              }),
            ])}
          </div>
          <div className="scale"><span>cleaner · {fmt(Math.min(...vals))}</span><i /><span>{fmt(Math.max(...vals))} · dirtier</span></div>
          <p className="small">In winter, <b>{hourName(worst)}</b> is the worst hour and <b>{hourName(best)}</b> the cleanest waking hour. Cold, still night air traps particles near the ground until the sun warms it and mixes them upward.</p>
        </Card>
        <Card title="How much does Diwali add?" hint={data.diwali.years.length ? `Diwalis with data: ${data.diwali.years.join(', ')}` : 'No Diwali with data yet'}>
          <LineChart labels={data.diwali.curve.map((c) => c.offset)} xTitle="Days from Diwali" yTitle="AQI above the weeks before"
            series={[{ label: 'Change', data: data.diwali.curve.map((c) => c.change), colour: '#f59e0b', fill: true }]} />
          {peak.change > -Infinity && <p className="small">Peak <b>+{fmt(peak.change)} AQI</b>, {peak.offset === 0 ? 'on Diwali itself' : `${Math.abs(peak.offset)} day${Math.abs(peak.offset) > 1 ? 's' : ''} ${peak.offset < 0 ? 'before' : 'after'} Diwali`}. Each day's AQI minus the average of days 30 to 11 before. Part of the rise is the normal post-monsoon worsening, so this is an upper bound on the festival's own effect.</p>}
        </Card>
        <Card title="The year in air" hint="Bars: average AQI by month. Line: share of days fine PM2.5 (smoke) rather than coarse PM10 (dust) set the AQI.">
          <SeasonChart monthly={data.monthly} share={data.pm25_share} />
        </Card>
        <Card title="Does the weekend help?" hint="Average AQI by day of the week">
          <Bars labels={WEEKDAYS} values={WEEKDAYS.map((_, i) => data.weekday.find((w) => w.day === i)?.aqi ?? null)}
            colours={WEEKDAYS.map((_, i) => colourOf(data.weekday.find((w) => w.day === i)?.aqi ?? 0))} yTitle="AQI" />
          {data.weekday.length === 7 && (() => {
            const lo = data.weekday.reduce((a, b) => (b.aqi < a.aqi ? b : a)), hi = data.weekday.reduce((a, b) => (b.aqi > a.aqi ? b : a))
            return <p className="small muted">{WEEKDAYS[lo.day]} is the cleanest day on average and {WEEKDAYS[hi.day]} the dirtiest, only {fmt(hi.aqi - lo.aqi)} AQI points apart: the season matters far more than the day of the week.</p>
          })()}
          <div className="cig">
            <span className="muted small">The past year in {city}, in cigarettes</span>
            <b>≈ {fmt(data.cigarettes_year)}</b>
            <span>{fmt((data.cigarettes_year ?? 0) / 365, 1)} a day, from the average PM2.5 (Berkeley Earth's rule: 22 µg/m³ for a day ≈ one cigarette). A rough comparison of harm, not a medical measure.</span>
          </div>
        </Card>
      </div>
    </div>
  )
}

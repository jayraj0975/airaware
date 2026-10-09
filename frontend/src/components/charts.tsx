import {
  BarController, BarElement, CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip,
} from 'chart.js'
import { Bar, Chart, Line } from 'react-chartjs-2'
import type { ForecastDay, Weather } from '../api'
import { colourOf, MONTHS, shortDate } from '../util'

ChartJS.register(BarController, BarElement, CategoryScale, Filler, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip)
ChartJS.defaults.font.family = 'Inter, system-ui, sans-serif'
ChartJS.defaults.color = '#64748b'
ChartJS.defaults.borderColor = 'rgba(100,116,139,.15)'
ChartJS.defaults.maintainAspectRatio = false
if (matchMedia('(prefers-reduced-motion: reduce)').matches) ChartJS.defaults.animation = false

export function ForecastChart({ history, forecast }: { history: { date: string; aqi: number }[]; forecast: ForecastDay[] }) {
  const n = history.length
  const pad = <T,>(a: T[]) => [...Array(n).fill(null), ...a]
  return (
    <div className="chart">
      <Line
        data={{
          labels: [...history.map((h) => h.date), ...forecast.map((f) => f.date)].map(shortDate),
          datasets: [
            { label: 'Measured', data: history.map((h) => h.aqi), borderColor: '#3b82f6', backgroundColor: '#3b82f6', pointRadius: 0, tension: 0.3 },
            { label: '80% range', data: pad(forecast.map((f) => f.hi)), borderColor: 'transparent', backgroundColor: 'rgba(245,133,24,.2)', fill: '+1', pointRadius: 0 },
            { label: '', data: pad(forecast.map((f) => f.lo)), borderColor: 'transparent', pointRadius: 0 },
            { label: 'AirAware forecast', data: pad(forecast.map((f) => f.forecast)), borderColor: '#f58518', backgroundColor: '#f58518', borderDash: [6, 4], tension: 0.3 },
          ],
        }}
        options={{
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { labels: { filter: (i) => !!i.text } } },
          scales: { y: { beginAtZero: true, title: { display: true, text: 'AQI' } }, x: { ticks: { maxTicksLimit: 9 } } },
        }}
      />
    </div>
  )
}

export function WeatherChart({ w }: { w: Weather }) {
  const h = w.hourly
  return (
    <div className="chart">
      <Line
        data={{
          labels: h.time.map((t) => new Date(t).toLocaleString('en-IN', { weekday: 'short', hour: 'numeric' })),
          datasets: [
            { label: 'Temperature °C', data: h.temperature_2m, borderColor: '#ef4444', yAxisID: 'y', pointRadius: 0, tension: 0.3 },
            { label: 'Humidity %', data: h.relative_humidity_2m ?? [], borderColor: '#06b6d4', yAxisID: 'y', pointRadius: 0, tension: 0.3 },
            { label: 'Mixing height (m)', data: h.boundary_layer_height ?? [], borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,.12)', fill: true, yAxisID: 'y2', pointRadius: 0, tension: 0.3 },
          ],
        }}
        options={{
          interaction: { mode: 'index', intersect: false },
          scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { position: 'left' }, y2: { position: 'right', grid: { drawOnChartArea: false } } },
        }}
      />
    </div>
  )
}

export function LineChart({ labels, series, yTitle, xTitle, height }: {
  labels: (string | number)[]; series: { label: string; data: (number | null)[]; colour: string; fill?: boolean; dash?: boolean }[]
  yTitle?: string; xTitle?: string; height?: number
}) {
  return (
    <div className="chart" style={height ? { height } : undefined}>
      <Line
        data={{ labels, datasets: series.map((s) => ({ label: s.label, data: s.data, borderColor: s.colour, backgroundColor: s.fill ? s.colour + '2e' : s.colour,
          fill: s.fill, borderDash: s.dash ? [6, 4] : undefined, tension: 0.3 })) }}
        options={{ plugins: { legend: { display: series.length > 1 } }, interaction: { mode: 'index', intersect: false },
          scales: { y: { beginAtZero: true, title: { display: !!yTitle, text: yTitle } }, x: { title: { display: !!xTitle, text: xTitle } } } }}
      />
    </div>
  )
}

export function SeasonChart({ monthly, share }: { monthly: { month: number; aqi: number }[]; share: { month: number; share: number }[] }) {
  const aqi = MONTHS.map((_, i) => monthly.find((m) => m.month === i + 1)?.aqi ?? null)
  const pm = MONTHS.map((_, i) => { const s = share.find((m) => m.month === i + 1); return s ? s.share * 100 : null })
  return (
    <div className="chart">
      <Chart type="bar"
        data={{ labels: MONTHS, datasets: [
          { type: 'line' as const, label: '% of days PM2.5 led', data: pm, borderColor: '#6366f1', backgroundColor: '#6366f1', yAxisID: 'y2', tension: 0.3, order: 0 },
          { type: 'bar' as const, label: 'Average AQI', data: aqi, backgroundColor: aqi.map((v) => colourOf(v ?? 0)), yAxisID: 'y', order: 1 },
        ] }}
        options={{ scales: { y: { beginAtZero: true, title: { display: true, text: 'AQI' } }, y2: { position: 'right', min: 0, max: 100, grid: { drawOnChartArea: false } } } }}
      />
    </div>
  )
}

export function HBar({ labels, values, colour = '#2563eb', xTitle }: { labels: string[]; values: number[]; colour?: string; xTitle?: string }) {
  return (
    <div className="chart tall">
      <Bar data={{ labels, datasets: [{ data: values, backgroundColor: colour, borderRadius: 4 }] }}
        options={{ indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { title: { display: !!xTitle, text: xTitle } } } }} />
    </div>
  )
}

export function Bars({ labels, values, colours, yTitle }: { labels: string[]; values: (number | null)[]; colours: string[]; yTitle?: string }) {
  return (
    <div className="chart small">
      <Bar data={{ labels, datasets: [{ data: values, backgroundColor: colours, borderRadius: 6 }] }}
        options={{ plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 }, title: { display: !!yTitle, text: yTitle } } } }} />
    </div>
  )
}

export function HourBars({ hours, small = false }: { hours: { hour: number; aqi: number }[]; small?: boolean }) {
  const now = new Date().getHours()
  return (
    <div className="chart" style={{ height: small ? 140 : 200 }}>
      <Bar
        data={{ labels: hours.map((h) => (h.hour % 3 === 0 ? `${h.hour % 12 || 12}${h.hour < 12 ? 'a' : 'p'}` : '')),
          datasets: [{ data: hours.map((h) => h.aqi), backgroundColor: hours.map((h) => colourOf(h.aqi)),
            borderColor: hours.map((h) => (h.hour === now ? '#0f172a' : 'transparent')), borderWidth: 2, borderRadius: 3 }] }}
        options={{ plugins: { legend: { display: false }, tooltip: { callbacks: {
            title: (i) => { const h = hours[i[0].dataIndex].hour; return `${h % 12 || 12} ${h < 12 ? 'am' : 'pm'}${h === now ? ' (now)' : ''}` },
            label: (i) => `About AQI ${Math.round(i.parsed.y ?? 0)}` } } },
          scales: { x: { grid: { display: false }, ticks: { autoSkip: false, maxRotation: 0 } }, y: { beginAtZero: true, display: !small } } }}
      />
    </div>
  )
}

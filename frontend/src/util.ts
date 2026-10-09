// Small formatting helpers shared by every page.

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const fmt = (v: number | null | undefined, d = 0) => (v == null || Number.isNaN(v) ? '–' : Number(v).toFixed(d))

export function todayISO(): string {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10)
}

export function dayName(iso: string): string {
  const d = new Date(iso.slice(0, 10) + 'T00:00')
  const t = new Date(todayISO() + 'T00:00')
  const diff = Math.round((d.getTime() - t.getTime()) / 864e5)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff === -1) return 'Yesterday'
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

export const shortDate = (iso: string) => new Date(iso.slice(0, 10) + 'T00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
export const dateTime = (iso: string) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
export const hourName = (h: number) => `${h % 12 || 12} ${h < 12 ? 'am' : 'pm'}`
export const compass = (deg: number) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(deg / 45) % 8]

export const WEATHER: Record<number, string> = {
  0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Fog', 51: 'Drizzle', 53: 'Drizzle', 55: 'Drizzle',
  61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 80: 'Showers', 81: 'Showers', 82: 'Heavy showers', 95: 'Thunderstorm', 96: 'Thunderstorm', 99: 'Thunderstorm',
}

export const upcoming = <T extends { date: string }>(list: T[]): T[] => {
  const t = todayISO()
  const u = list.filter((f) => f.date >= t)
  return u.length ? u : list.slice(-1)
}

const CATS: [number, string][] = [[50, '#00b050'], [100, '#92d050'], [200, '#ffff00'], [300, '#ff9900'], [400, '#ff0000'], [Infinity, '#c00000']]
export const colourOf = (aqi: number) => CATS.find(([u]) => aqi <= u)![1]

/** Smooth green-to-red scale: AQI 40 is green, 120 yellow, 200 orange, 280 and above red. */
export function heat(aqi: number): string {
  const t = Math.max(0, Math.min(1, (aqi - 40) / 240))
  return `hsl(${130 - 130 * t} ${65 + 25 * t}% ${45 + 5 * Math.sin(Math.PI * t)}%)`
}

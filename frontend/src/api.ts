// Typed client for the AirAware API. Every write sends X-AirAware: 1, which the server requires (CSRF guard).

export interface Category { name: string; colour: string; advice: string }
export interface Personal { level: 'ok' | 'caution' | 'avoid'; category: string; text: string }
export interface ForecastDay {
  city: string; made_from: string; date: string; days_ahead: number
  forecast: number; lo: number; hi: number; p_poor: number; category: Category; personal: Personal
}
export interface Weather {
  current: { time: string; temperature_2m: number; relative_humidity_2m: number; apparent_temperature: number
    precipitation: number; weather_code: number; wind_speed_10m: number; wind_direction_10m: number }
  hourly: { time: string[]; temperature_2m: number[]; relative_humidity_2m?: number[]; boundary_layer_height?: number[]
    precipitation_probability?: number[]; wind_speed_10m?: number[] }
}
export interface Status {
  cities: Record<string, { lat: number; lon: number; last_measured: string; stations: number }>
  trained_at: string; live_readings: boolean; live_at: string | null; live_key: boolean
  categories: { upper: number | null; name: string; colour: string }[]
  health_groups: Record<string, string>; report_kinds: Record<string, string>
}
export interface Overview {
  city: string
  measured: { date: string; aqi: number; pm25: number; pm10: number; stations: number; category: Category
    dominant: string; cigarettes: number; source: string }
  forecast: ForecastDay[]; history: { date: string; aqi: number }[]
  plan: { best_day: string; best_day_aqi: number; best_hours: number[] }
  hours: { hour: number; aqi: number }[]
  weather: Weather | null
}
export interface Station {
  station: string; lat: number; lon: number; date: string; aqi: number; pm25: number | null; pm10: number | null
  verdict: string | null; correlation: number | null; category: Category
}
export interface Report { id: number; lat: number; lon: number; kind: string; label: string; note: string; created_at: string }
export interface Area {
  lat: number; lon: number; city: string; place: string; source: string
  measured: { aqi: number; used: number; offset: number; category: Category
    nearest: { station: string; km: number; aqi: number; date: string }[] }
  today: ForecastDay; forecast: ForecastDay[]; best_hours: number[]; hours: { hour: number; aqi: number }[]
  weather: Weather | null; reports: Report[]
}
export interface User {
  id: number; email: string; name: string; role: 'user' | 'admin'; city: string; health: string[]
  email_alerts: number; created_at: string; last_login: string | null
  health_consent: boolean; needs_consent: boolean; two_step: boolean
}
export interface Place {
  id: number; name: string; lat: number; lon: number; city: string; estimate?: number
  forecast: ForecastDay[]; alerts?: { id: number; threshold: number; active: number; last_sent: string | null }[]
}
export interface Note { id: number; title: string; body: string; created_at: string; read: number }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-AirAware'] = '1'
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin' })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    const d = (data as { detail?: unknown }).detail
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).join('; ') : r.statusText
    throw new ApiError(r.status, msg || `Request failed (${r.status})`)
  }
  return data as T
}

export const api = {
  get: <T,>(path: string) => request<T>('GET', path),
  post: <T,>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  patch: <T,>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T,>(path: string, body?: unknown) => request<T>('DELETE', path, body),
}

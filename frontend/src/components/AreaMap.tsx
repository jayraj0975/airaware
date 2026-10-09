import 'leaflet/dist/leaflet.css'
import { useEffect, useState } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import type { Report, Station } from '../api'
import { dateTime, fmt } from '../util'
import { toast } from './ui'

export interface Pin { lat: number; lon: number; label: string; colour?: string }

function Recenter({ lat, lon, zoom }: { lat: number; lon: number; zoom: number }) {
  const map = useMap()
  useEffect(() => { map.setView([lat, lon], zoom) }, [lat, lon, zoom, map])
  return null
}

function FlyTo({ to }: { to?: { lat: number; lon: number; n: number } | null }) {
  const map = useMap()
  useEffect(() => { if (to) map.flyTo([to.lat, to.lon], 14, { duration: 0.8 }) }, [to, map])
  return null
}

function Clicks({ onPick }: { onPick?: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick?.(e.latlng.lat, e.latlng.lng) })
  return null
}

function LocateButton({ onPick }: { onPick?: (lat: number, lon: number) => void }) {
  const map = useMap()
  const [locating, setLocating] = useState(false)
  if (!onPick || !('geolocation' in navigator)) return null
  const locate = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault()
    e.stopPropagation()
    if (!window.isSecureContext) {
      toast('Location access needs a secure HTTPS connection. Search an area or tap the map instead.', 'error')
      return
    }
    if (locating) return
    setLocating(true)
    navigator.geolocation.getCurrentPosition((p) => {
      const lat = p.coords.latitude
      const lon = p.coords.longitude
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
        toast('Your device returned an invalid location. Search an area or tap the map instead.', 'error')
        setLocating(false)
        return
      }
      map.setView([lat, lon], 13)
      onPick(lat, lon)
      setLocating(false)
    }, (err) => {
      const message = err.code === err.PERMISSION_DENIED
        ? 'Location permission is blocked. Allow it for this site in your browser settings, or search an area instead.'
        : err.code === err.TIMEOUT
          ? 'Your device took too long to find your location. Try again near a window, or search an area.'
          : 'Your device could not determine your location. Check device location settings, or search an area instead.'
      toast(message, 'error')
      setLocating(false)
    }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 60000 })
  }
  return (
    <button type="button" className="locate" title="Use my location" aria-live="polite" disabled={locating} onClick={locate}>
      {locating ? 'Finding location…' : '◎ My location'}
    </button>
  )
}

export default function AreaMap({ center, zoom = 11, stations = [], reports = [], pins = [], picked, onPick, height = 520, focus }: {
  center: [number, number]; zoom?: number; stations?: Station[]; reports?: Report[]; pins?: Pin[]
  picked?: { lat: number; lon: number } | null; onPick?: (lat: number, lon: number) => void; height?: number
  focus?: { lat: number; lon: number; n: number } | null  // fly here (n changes on every request)
}) {
  return (
    <div className="map-wrap" style={{ height }}>
      <MapContainer center={center} zoom={zoom} scrollWheelZoom style={{ height: '100%', width: '100%' }}>
        <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxZoom={19}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
        <Recenter lat={center[0]} lon={center[1]} zoom={zoom} />
        <FlyTo to={focus} />
        <Clicks onPick={onPick} />
        <LocateButton onPick={onPick} />
        {stations.map((s) => (
          <CircleMarker key={s.station} center={[s.lat, s.lon]} radius={11} pathOptions={{ color: '#0f172a', weight: 1, fillColor: s.category.colour, fillOpacity: 0.9 }}
            eventHandlers={{ click: (e) => { e.originalEvent.stopPropagation(); onPick?.(s.lat, s.lon) } }}>
            <Tooltip><b>{s.station}</b><br />AQI {fmt(s.aqi)} · {s.category.name}<br />{s.date}</Tooltip>
          </CircleMarker>
        ))}
        {reports.map((r) => (
          <CircleMarker key={`r${r.id}`} center={[r.lat, r.lon]} radius={7} pathOptions={{ color: '#7c2d12', weight: 2, dashArray: '3 3', fillColor: '#fb923c', fillOpacity: 0.85 }}>
            <Tooltip><b>Reported: {r.label}</b>{r.note && <><br />{r.note}</>}<br />{dateTime(r.created_at)}</Tooltip>
          </CircleMarker>
        ))}
        {pins.map((p) => (
          <CircleMarker key={`p${p.lat},${p.lon}`} center={[p.lat, p.lon]} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: p.colour ?? '#2563eb', fillOpacity: 1 }}>
            <Tooltip permanent direction="top" offset={[0, -8]}>{p.label}</Tooltip>
          </CircleMarker>
        ))}
        {picked && <CircleMarker center={[picked.lat, picked.lon]} radius={10} pathOptions={{ color: '#fff', weight: 4, fillColor: '#111827', fillOpacity: 1 }} />}
      </MapContainer>
    </div>
  )
}

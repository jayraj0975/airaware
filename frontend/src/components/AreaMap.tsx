import 'leaflet/dist/leaflet.css'
import { useEffect } from 'react'
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
  if (!onPick || !('geolocation' in navigator)) return null
  return (
    <button type="button" className="locate" title="Use my location" onClick={(e) => {
      e.stopPropagation()
      navigator.geolocation.getCurrentPosition((p) => {
        map.setView([p.coords.latitude, p.coords.longitude], 13)
        onPick(p.coords.latitude, p.coords.longitude)
      }, () => toast('Could not get your location. Allow location access, or search or click the map instead.', 'error'))
    }}>◎ My location</button>
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

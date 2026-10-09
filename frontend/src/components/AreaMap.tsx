import 'leaflet/dist/leaflet.css'
import { useEffect } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import type { Report, Station } from '../api'
import { dateTime, fmt } from '../util'

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
        {stations.map((s) => (
          <CircleMarker key={s.station} center={[s.lat, s.lon]} radius={9} pathOptions={{ color: '#ffffff', weight: 1.5, fillColor: s.category.colour, fillOpacity: 0.95 }}
            eventHandlers={{ click: (e) => { e.originalEvent.stopPropagation(); onPick?.(s.lat, s.lon) } }}>
            <Tooltip><b>{s.station}</b><br />AQI {fmt(s.aqi)} · {s.category.name}<br />{s.date}</Tooltip>
          </CircleMarker>
        ))}
        {reports.map((r) => (
          <CircleMarker key={`r${r.id}`} center={[r.lat, r.lon]} radius={7} pathOptions={{ color: '#a8630c', weight: 1.5, dashArray: '3 3', fillColor: '#f3d9b5', fillOpacity: 0.9 }}>
            <Tooltip><b>Reported: {r.label}</b>{r.note && <><br />{r.note}</>}<br />{dateTime(r.created_at)}</Tooltip>
          </CircleMarker>
        ))}
        {pins.map((p) => (
          <CircleMarker key={`p${p.lat},${p.lon}`} center={[p.lat, p.lon]} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: p.colour ?? '#0f6b5c', fillOpacity: 1 }}>
            <Tooltip permanent direction="top" offset={[0, -8]}>{p.label}</Tooltip>
          </CircleMarker>
        ))}
        {picked && <CircleMarker center={[picked.lat, picked.lon]} radius={10} pathOptions={{ color: '#fff', weight: 3, fillColor: '#1a1c1e', fillOpacity: 1 }} />}
      </MapContainer>
    </div>
  )
}

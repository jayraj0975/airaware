import { useEffect, useState } from 'react'
import { api, type Area, type Place } from '../api'
import AreaMap from '../components/AreaMap'
import SearchBox from '../components/SearchBox'
import { LineChart } from '../components/charts'
import { Card, Empty, Pill, useTitle } from '../components/ui'
import { useSession } from '../session'
import { dayName, fmt, upcoming } from '../util'

const COLOURS = ['#2563eb', '#db2777', '#059669', '#d97706']
type Spot = { id: number; lat: number; lon: number; label?: string; area?: Area; error?: string }
let nextId = 1

export default function Compare() {
  useTitle('Compare areas')
  const { city, status, user } = useSession()
  const [spots, setSpots] = useState<Spot[]>([])
  const centre = status?.cities[city]

  const add = async (lat: number, lon: number, label?: string) => {
    if (spots.length >= 4) return
    const id = nextId++  // results can come back in any order, so update by id, not position
    setSpots((s) => (s.length >= 4 ? s : [...s, { id, lat, lon, label }]))
    try {
      const area = await api.get<Area>(`/api/area?lat=${lat}&lon=${lon}`)
      setSpots((s) => s.map((x) => (x.id === id ? { ...x, area, label: label ?? area.place.split(',')[0] } : x)))
    } catch (e) {
      setSpots((s) => s.map((x) => (x.id === id ? { ...x, error: (e as Error).message } : x)))
    }
  }

  const [places, setPlaces] = useState<Place[]>([])
  useEffect(() => { if (user) api.get<Place[]>('/api/me/places').then(setPlaces).catch(() => setPlaces([])) }, [user])

  const ready = spots.filter((s) => s.area)
  const dates = ready.length ? upcoming(ready[0].area!.forecast).map((f) => f.date) : []
  return (
    <div className="page">
      <div className="page-head"><h1>Compare areas</h1><p className="muted">Click up to four spots, say home, office and your child's school, to see whose air is better this week.</p></div>
      <div className="map-row">
        <Card title="Pick spots" hint={`${spots.length}/4 chosen: search, or click the map`} action={spots.length > 0 && <button className="ghost small" onClick={() => setSpots([])}>Clear</button>}>
          <SearchBox city={city} onPick={(lat, lon, label) => add(lat, lon, label)} />
          {centre && <AreaMap center={[centre.lat, centre.lon]} onPick={(lat, lon) => add(lat, lon)} height={440}
            pins={spots.map((s, i) => ({ lat: s.lat, lon: s.lon, label: s.label ?? `Spot ${i + 1}`, colour: COLOURS[i] }))} />}
          {places.length > 0 && <div className="chips">Your places: {places.map((p) => <button key={p.id} className="chip" onClick={() => add(p.lat, p.lon, p.name)}>{p.name}</button>)}</div>}
        </Card>
        <Card title="Side by side" className="area">
          {spots.length === 0 ? <Empty>Click the map to add your first spot.</Empty> : (
            <div className="compare-list">
              {spots.map((s, i) => (
                <div key={s.id} className="compare-item" style={{ borderColor: COLOURS[i] }}>
                  <b>{s.label ?? 'Loading…'}</b>
                  {s.error && <span className="warn small">{s.error}</span>}
                  {s.area && <><span className="swatch" style={{ background: s.area.today.category.colour }} /><span className="big">{fmt(s.area.today.forecast)}</span><Pill cat={s.area.today.category} />
                    <span className="small muted">{dayName(s.area.today.date)} · week average {fmt(upcoming(s.area.forecast).reduce((a, f) => a + f.forecast, 0) / upcoming(s.area.forecast).length)}</span></>}
                </div>
              ))}
            </div>
          )}
          {ready.length > 1 && (() => {
            const avg = ready.map((s) => upcoming(s.area!.forecast).reduce((a, f) => a + f.forecast, 0) / upcoming(s.area!.forecast).length)
            const best = avg.indexOf(Math.min(...avg))
            return <p className="ok small">Cleanest this week: <b>{ready[best].label}</b>, about {fmt(Math.max(...avg) - avg[best])} AQI points better than the worst.</p>
          })()}
        </Card>
      </div>
      {ready.length > 0 && (
        <Card title="The week ahead">
          <LineChart labels={dates.map(dayName)} yTitle="Forecast AQI"
            series={ready.map((s) => ({ label: s.label ?? '', data: dates.map((d) => s.area!.forecast.find((f) => f.date === d)?.forecast ?? null), colour: COLOURS[spots.indexOf(s)] }))} />
        </Card>
      )}
    </div>
  )
}

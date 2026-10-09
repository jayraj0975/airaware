import { Suspense, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useSession } from '../session'
import { shortDate } from '../util'
import { Spinner } from './ui'

export default function Shell() {
  const { user, unread, status, city, setCity, setUser } = useSession()
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const signOut = async () => {
    await api.post('/api/auth/logout').catch(() => undefined)
    navigator.serviceWorker?.controller?.postMessage('signed-out')  // drop anything cached while signed in
    setUser(null)
    nav('/')
  }
  const links = [['/', 'Today'], ['/explore', 'Insights'], ['/compare', 'Compare'], ['/science', 'Science'], ['/track-record', 'Track record'], ['/about', 'About']]
  return (
    <>
      <header className="top">
        <Link to="/" className="brand" onClick={() => setOpen(false)}>
          <img src="/favicon.svg" alt="" width={34} height={34} />
          <div><b>AirAware</b><small>Know your air, a week ahead</small></div>
        </Link>
        <button className="menu-btn" aria-label="Menu" onClick={() => setOpen(!open)}>☰</button>
        <nav className={`links ${open ? 'open' : ''}`} onClick={() => setOpen(false)}>
          {links.map(([to, label]) => <NavLink key={to} to={to} end={to === '/'}>{label}</NavLink>)}
          {user?.role === 'admin' && <NavLink to="/admin" className="admin-link">Admin</NavLink>}
        </nav>
        <div className="right">
          <div className="cities" role="group" aria-label="City">
            {Object.keys(status?.cities ?? { Pune: 0, Mumbai: 0 }).map((c) => (
              <button key={c} className={c === city ? 'on' : ''} onClick={() => setCity(c)}>{c}</button>
            ))}
          </div>
          {user ? (
            <>
              <Link to="/me#notifications" className="bell" title="Notifications" aria-label={`${unread} unread notifications`}>
                🔔{unread > 0 && <span>{unread > 9 ? '9+' : unread}</span>}
              </Link>
              <Link to="/me" className="avatar" title={user.email}>{user.name.slice(0, 1).toUpperCase()}</Link>
              <button className="ghost small" onClick={signOut}>Sign out</button>
            </>
          ) : (
            <>
              <Link to="/login" className="ghost-link">Sign in</Link>
              <Link to="/signup" className="btn small">Get alerts</Link>
            </>
          )}
        </div>
      </header>
      {status && (
        <div className={`strip ${status.live_readings ? 'live' : ''}`}>
          <i />
          {status.live_readings
            ? <>Live CPCB station readings · weather live · models retrained {shortDate(status.trained_at)}</>
            : <>Station readings to {shortDate(status.cities[city]?.last_measured ?? '')} (public archive, a few days behind) · weather and CAMS forecasts live · forecasts start from the last reading</>}
        </div>
      )}
      <main><Suspense fallback={<Spinner />}><Outlet /></Suspense></main>
      <footer>
        <div><b>AirAware</b> · forecasts are estimates, not the official CPCB AQI. Data: CPCB via OpenAQ, Open-Meteo, Copernicus CAMS, © OpenStreetMap.</div>
        <div><Link to="/about">About</Link> · <Link to="/science">How it works</Link> · <a href="/api/docs">API</a></div>
      </footer>
    </>
  )
}

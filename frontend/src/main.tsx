import { lazy, StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import Shell from './components/Shell'
import { Spinner } from './components/ui'
import Home from './pages/Home'
import { SessionProvider, useSession } from './session'
import './styles.css'

// Home loads with the app; every other page is fetched the first time it is opened.
const About = lazy(() => import('./pages/About'))
const Admin = lazy(() => import('./pages/Admin'))
const Auth = lazy(() => import('./pages/Auth'))
const Compare = lazy(() => import('./pages/Compare'))
const Explore = lazy(() => import('./pages/Explore'))
const Me = lazy(() => import('./pages/Me'))
const Science = lazy(() => import('./pages/Science'))
const TrackRecord = lazy(() => import('./pages/TrackRecord'))

function Guard({ admin = false, children }: { admin?: boolean; children: ReactNode }) {
  const { user, ready } = useSession()
  if (!ready) return <Spinner />
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  if (admin && user.role !== 'admin') return <Navigate to="/" replace />
  return <>{children}</>
}

const router = createBrowserRouter([{
  element: <Shell />,
  children: [
    { path: '/', element: <Home /> },
    { path: '/explore', element: <Explore /> },
    { path: '/compare', element: <Compare /> },
    { path: '/science', element: <Science /> },
    { path: '/track-record', element: <TrackRecord /> },
    { path: '/about', element: <About /> },
    { path: '/login', element: <Auth mode="login" /> },
    { path: '/signup', element: <Auth mode="signup" /> },
    { path: '/me', element: <Guard><Me /></Guard> },
    { path: '/admin', element: <Guard admin><Admin /></Guard> },
    { path: '*', element: <div className="page narrow"><h1>Page not found</h1><p><a href="/">Back to today's air</a></p></div> },
  ],
}])

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => undefined))
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SessionProvider><RouterProvider router={router} /></SessionProvider>
  </StrictMode>,
)

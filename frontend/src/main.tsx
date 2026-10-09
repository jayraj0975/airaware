import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import Shell from './components/Shell'
import { Spinner } from './components/ui'
import About from './pages/About'
import Admin from './pages/Admin'
import Auth from './pages/Auth'
import Compare from './pages/Compare'
import Explore from './pages/Explore'
import Home from './pages/Home'
import Me from './pages/Me'
import Science from './pages/Science'
import TrackRecord from './pages/TrackRecord'
import { SessionProvider, useSession } from './session'
import './styles.css'

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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SessionProvider><RouterProvider router={router} /></SessionProvider>
  </StrictMode>,
)

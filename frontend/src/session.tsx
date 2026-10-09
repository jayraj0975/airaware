// App-wide state: the signed-in user, unread notification count, the selected city and the API status.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, type Status, type User } from './api'

interface Session {
  user: User | null; unread: number; ready: boolean; status: Status | null
  city: string; setCity: (c: string) => void
  refresh: () => Promise<void>; setUser: (u: User | null) => void
}

const Ctx = createContext<Session | null>(null)

function savedCity(): string {
  try { return localStorage.getItem('aa-city') || 'Pune' } catch { return 'Pune' }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [unread, setUnread] = useState(0)
  const [ready, setReady] = useState(false)
  const [status, setStatus] = useState<Status | null>(null)
  const [city, setCityState] = useState(savedCity)

  const setCity = useCallback((c: string) => {
    setCityState(c)
    try { localStorage.setItem('aa-city', c) } catch { /* private mode: just not remembered */ }
  }, [])

  const refresh = useCallback(async () => {
    const me = await api.get<{ user: User | null; unread?: number }>('/api/auth/me').catch(() => ({ user: null, unread: 0 }))
    setUser(me.user)
    setUnread(me.unread ?? 0)
    setReady(true)
  }, [])

  useEffect(() => {
    refresh()
    api.get<Status>('/api/status').then(setStatus).catch(() => setStatus(null))
    const t = setInterval(refresh, 60_000)  // keeps the notification bell current
    return () => clearInterval(t)
  }, [refresh])

  return <Ctx.Provider value={{ user, unread, ready, status, city, setCity, refresh, setUser }}>{children}</Ctx.Provider>
}

export function useSession(): Session {
  const s = useContext(Ctx)
  if (!s) throw new Error('useSession outside SessionProvider')
  return s
}

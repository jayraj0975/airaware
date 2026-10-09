import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'

/** /forgot asks for a reset link; /reset?token=… sets a new password with one. */
export default function Reset({ mode }: { mode: 'forgot' | 'reset' }) {
  const nav = useNavigate()
  const [value, setValue] = useState('')
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // The token travels after '#', which browsers never send to the server, so it stays out of access logs.
  const token = new URLSearchParams(location.hash.slice(1)).get('token') ?? ''

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (mode === 'forgot') {
        const r = await api.post<{ detail: string }>('/api/auth/forgot', { email: value })
        setMsg(r.detail)
      } else {
        await api.post('/api/auth/reset', { token, password: value })
        nav('/login?reset=1', { replace: true })
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page auth">
      <form className="card auth-card" onSubmit={submit}>
        <h1>{mode === 'forgot' ? 'Forgot your password?' : 'Choose a new password'}</h1>
        {mode === 'forgot' ? (
          <>
            <p className="muted">Enter your email and we will send a reset link, if this server has email set up. If not, an admin can give you a link.</p>
            <label>Email<input required type="email" autoComplete="email" value={value} onChange={(e) => setValue(e.target.value)} /></label>
          </>
        ) : !token ? (
          <div className="error">This page needs the link from your email or admin.</div>
        ) : (
          <label>New password<input required type="password" minLength={8} autoComplete="new-password" value={value} onChange={(e) => setValue(e.target.value)} />
            <small className="muted">At least 8 characters. Every device signed in to your account will be signed out.</small></label>
        )}
        {msg && <p className="ok small">{msg}</p>}
        {error && <div className="error">{error}</div>}
        {!(mode === 'reset' && !token) && <button className="btn wide" disabled={busy}>{busy ? 'Please wait…' : mode === 'forgot' ? 'Send reset link' : 'Set new password'}</button>}
        <p className="small center"><Link to="/login">Back to sign in</Link></p>
      </form>
    </div>
  )
}

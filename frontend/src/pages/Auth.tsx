import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type User } from '../api'
import { useSession } from '../session'

export default function Auth({ mode }: { mode: 'login' | 'signup' }) {
  const { setUser, refresh, city } = useSession()
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '', city })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const signup = mode === 'signup'
  const next = params.get('next')?.startsWith('/') && !params.get('next')?.startsWith('//') ? params.get('next')! : '/me'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const u = await api.post<User>(signup ? '/api/auth/signup' : '/api/auth/login', signup ? form : { email: form.email, password: form.password })
      setUser(u)
      await refresh()
      nav(next, { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  return (
    <div className="page auth">
      <form className="card auth-card" onSubmit={submit}>
        <h1>{signup ? 'Create your free account' : 'Welcome back'}</h1>
        <p className="muted">{signup ? 'Save your places, get advice tuned to your health, and an alert before a bad air day.' : 'Sign in to see your places and alerts.'}</p>
        {signup && <label>Name<input required maxLength={80} value={form.name} onChange={set('name')} autoComplete="name" /></label>}
        <label>Email<input required type="email" value={form.email} onChange={set('email')} autoComplete="email" /></label>
        <label>Password<input required type="password" minLength={signup ? 8 : 1} value={form.password} onChange={set('password')} autoComplete={signup ? 'new-password' : 'current-password'} />
          {signup ? <small className="muted">At least 8 characters.</small> : <small><Link to="/forgot">Forgot password?</Link></small>}</label>
        {signup && (
          <label>Your city<select value={form.city} onChange={set('city')}><option>Pune</option><option>Mumbai</option></select></label>
        )}
        {!signup && params.get('reset') && <p className="ok small">Password changed. Sign in with your new password.</p>}
        {error && <div className="error">{error}</div>}
        <button className="btn wide" disabled={busy}>{busy ? 'Please wait…' : signup ? 'Create account' : 'Sign in'}</button>
        <p className="small center">{signup ? <>Already have an account? <Link to="/login">Sign in</Link></> : <>New here? <Link to="/signup">Create a free account</Link></>}</p>
      </form>
    </div>
  )
}

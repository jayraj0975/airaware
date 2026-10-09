import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Card, toast, useTitle } from '../components/ui'
import { useSession } from '../session'

export const POLICY_DATE = '10 October 2026'

export function Privacy() {
  useTitle('Privacy Notice')
  return (
    <div className="page narrow prose legal">
      <h1>Privacy Notice</h1>
      <p className="muted">Last updated {POLICY_DATE}. Written to meet India's Digital Personal Data Protection Act, 2023 (DPDP Act) and its Rules.</p>

      <Card title="The short version">
        <ul>
          <li>You can use the forecasts, map, insights and everything public <b>without an account</b>. We collect nothing personal for that.</li>
          <li>If you make an account we keep your <b>email, name, password (scrambled so even we cannot read it), city, saved places and alerts</b>, to run your account and warn you about bad air.</li>
          <li><b>Health information is optional</b> and needs its own separate consent. We use it only to tailor advice. You can erase it any time.</li>
          <li>We <b>never sell</b> your data, show ads, or use tracking or analytics cookies.</li>
          <li>You can <b>see, download, correct or delete</b> your data yourself from <Link to="/me">your dashboard</Link>, or ask us on the <Link to="/rights">Your rights</Link> page.</li>
        </ul>
      </Card>

      <h2>1. Who we are</h2>
      <p>AirAware is an air-quality forecasting service for Pune and Mumbai, built and run by its developer as a student project. For your personal data, AirAware is the <i>Data Fiduciary</i> under the DPDP Act. To reach us about anything in this notice, use the <Link to="/rights">Your rights</Link> page; it reaches the person responsible for handling grievances.</p>

      <h2>2. What we collect, and why</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>What</th><th>Why we need it</th><th>How long we keep it</th></tr></thead>
        <tbody>
          <tr><td>Email, name, password (stored only as a scrypt hash)</td><td>Your account and signing in</td><td>Until you delete your account</td></tr>
          <tr><td>Home city, saved places (a name and map point)</td><td>Forecasts for the places you choose</td><td>Until you remove them or delete your account</td></tr>
          <tr><td>Alerts and in-app notifications</td><td>Warning you before a bad air day</td><td>Read notifications 180 days, all notifications 1 year</td></tr>
          <tr><td>Health groups you tick (asthma, heart disease, children, over 65, pregnancy, outdoor work)</td><td>Tailoring advice and alert levels, <b>only with your separate consent</b></td><td>Until you withdraw consent or delete your account; erased at once</td></tr>
          <tr><td>Pollution reports you send (place, type, note)</td><td>Showing pollution sources on the public map after moderation</td><td>Kept as public information; if you delete your account your name is removed from them</td></tr>
          <tr><td>Sign-in records, IP address, browser type</td><td>Security: stopping password guessing, spam and abuse</td><td>1 year</td></tr>
          <tr><td>Privacy requests and grievances you send us</td><td>Answering them and keeping a record we did</td><td>3 years after they are answered</td></tr>
        </tbody>
      </table></div>
      <p>We do not collect your location in the background. "Use my location" reads it once, in your browser, only when you tap it, to centre the map; it is not stored unless you save that spot as a place.</p>

      <h2>3. Your consent</h2>
      <p>We process your account data on the basis of the consent you give when you sign up, by ticking that you agree to this notice and the <Link to="/terms">Terms</Link>. Health information needs a <b>second, separate</b> consent that you give on your dashboard. Consent is free, and you can withdraw it at any time, as easily as you gave it: erase your health information with one tap, or delete your account. Withdrawing does not affect what was done before.</p>

      <h2>4. Who else sees anything</h2>
      <ul>
        <li><b>Nobody buys or receives your account data.</b> We do not sell, rent or share it for advertising.</li>
        <li>To show the map and weather, your browser and our server ask <b>OpenStreetMap</b> (map tiles, place names, search) and <b>Open-Meteo</b> (weather) about map coordinates. They see coordinates and your IP address for the map tiles, never your name or email.</li>
        <li>If email is switched on, alert and password-reset emails go through our email provider.</li>
        <li>We will disclose data to authorities only when Indian law requires it.</li>
      </ul>

      <h2>5. Your rights</h2>
      <p>Under the DPDP Act you have the right to:</p>
      <ul>
        <li><b>Access</b>: a summary of your personal data and how it is used. <Link to="/me#privacy">Download your data</Link> any time.</li>
        <li><b>Correction and completion</b>: edit your name, city, places and health groups on your dashboard, or ask us.</li>
        <li><b>Erasure</b>: delete your account, which deletes your data, from your dashboard, or ask us.</li>
        <li><b>Withdraw consent</b>, as above.</li>
        <li><b>Grievance redressal</b>: tell us about any problem on the <Link to="/rights">Your rights</Link> page. We reply within 30 days at the latest.</li>
        <li><b>Nominate</b> someone to exercise these rights if you die or become unable to: send their name and email through the <Link to="/rights">Your rights</Link> page.</li>
      </ul>
      <p>If you are not satisfied with our answer, you can complain to the <b>Data Protection Board of India</b>.</p>

      <h2>6. Children</h2>
      <p>Accounts are for people aged 18 or over; you confirm this when you sign up. We do not knowingly process children's personal data. If you believe a child has made an account, tell us and we will delete it. The public forecasts need no account and are fine for anyone.</p>

      <h2>7. How we protect it</h2>
      <p>Passwords are hashed with scrypt; sign-in sessions use secure, HttpOnly cookies and only a hash of each session key is stored; the site runs over HTTPS; sign-ins, sign-ups and lookups are rate-limited; each person can only reach their own data; admin actions are logged; the database is backed up daily; and the code is tested against common attacks on every change. Admins can turn on two-step sign-in.</p>
      <p>If a breach ever affects your data, we will tell you and the Data Protection Board of India without delay, as the Act requires, with what happened, what it means for you and what we are doing about it.</p>

      <h2>8. Cookies</h2>
      <p>We use <b>one</b> cookie, <code>aa_session</code>, only to keep you signed in. It is strictly necessary, so there is no cookie banner. Your browser also remembers your chosen city on your device. There are no analytics, advertising or third-party cookies.</p>

      <h2>9. Changes</h2>
      <p>If this notice changes in a way that matters, we will ask you to agree again the next time you sign in, and show the date above.</p>
    </div>
  )
}

export function Terms() {
  useTitle('Terms of use')
  return (
    <div className="page narrow prose legal">
      <h1>Terms of use</h1>
      <p className="muted">Last updated {POLICY_DATE}.</p>
      <Card title="In plain words">
        <p>AirAware gives honest, best-effort forecasts. They are estimates, not the official CPCB AQI and not medical advice. Use them to plan your day, and follow your doctor and official advisories. Be truthful when you report pollution.</p>
      </Card>

      <h2>1. The service</h2>
      <p>AirAware forecasts air quality for Pune and Mumbai from public data (CPCB monitoring stations via OpenAQ, Open-Meteo weather, Copernicus CAMS). It is a student project offered free of charge, as is, and may change, pause or stop.</p>

      <h2>2. Forecasts are estimates</h2>
      <ul>
        <li>Forecasts and area estimates can be wrong, sometimes by a lot. Every forecast shows a likely range; the real value falls outside it about one time in eight. Our <Link to="/track-record">track record</Link> shows how we do.</li>
        <li>They are <b>not</b> the official National Air Quality Index and are not endorsed by CPCB, MPCB or any government body.</li>
        <li>Health advice here is general information, <b>not medical advice</b>. If you have a health condition, follow your doctor's advice. In an emergency, call 112.</li>
      </ul>

      <h2>3. Your account</h2>
      <p>You must be 18 or older to make an account. Keep your password to yourself; you are responsible for what happens under your account. Tell us if you think someone else has used it.</p>

      <h2>4. Reports and fair use</h2>
      <ul>
        <li>Pollution reports must be true to the best of your knowledge. Do not report people or homes to harass them, and do not include anyone's personal details in a note.</li>
        <li>Moderators may decline or remove any report.</li>
        <li>Do not try to break, overload, scrape at scale or get around the security of the service, and do not use it for anything unlawful. Testing the security of your own copy of the open-source code is fine.</li>
      </ul>
      <p>We may suspend accounts that break these terms.</p>

      <h2>5. Data</h2>
      <p>How we handle personal data is set out in the <Link to="/privacy">Privacy Notice</Link>. Air-quality data belongs to its public sources and is used under their terms.</p>

      <h2>6. Liability</h2>
      <p>To the extent the law allows, AirAware is not liable for decisions made on the basis of its forecasts, or for losses from the service being unavailable. Nothing in these terms limits rights you have under Indian consumer law.</p>

      <h2>7. Law</h2>
      <p>These terms are governed by the laws of India. If a term changes in a way that matters, we will ask you to agree again when you next sign in.</p>
    </div>
  )
}

const KINDS: [string, string][] = [
  ['access', 'Get a summary of my data'], ['correction', 'Correct or complete my data'], ['erasure', 'Erase my data'],
  ['withdraw', 'Withdraw consent'], ['grievance', 'Raise a complaint (grievance)'], ['other', 'Something else, e.g. nominate someone'],
]

export function Rights() {
  useTitle('Your rights')
  const { user } = useSession()
  const [form, setForm] = useState({ email: user?.email ?? '', kind: 'grievance', message: '' })
  const [sent, setSent] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try { const r = await api.post<{ detail: string }>('/api/privacy/requests', form); setSent(r.detail); setForm({ ...form, message: '' }) }
    catch (err) { toast((err as Error).message, 'error') }
    finally { setBusy(false) }
  }
  return (
    <div className="page narrow prose">
      <h1>Your rights and contact</h1>
      <p className="lead">Questions, complaints or requests about your data: this goes straight to the person responsible for grievances.</p>
      {user && <Card title="Do it yourself, right now">
        <ul>
          <li><Link to="/me#privacy">Download everything we hold about you</Link></li>
          <li><Link to="/me#profile">Correct your name, city or health groups</Link></li>
          <li><Link to="/me#privacy">Erase your health information or delete your account</Link></li>
        </ul>
      </Card>}
      <Card title="Send us a request">
        {sent ? <p className="ok">{sent}</p> : (
          <form className="form" onSubmit={submit}>
            <label>Your email (we reply here)<input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
            <label>What do you need?<select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {KINDS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>Tell us more<textarea required minLength={5} maxLength={2000} rows={5} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })}
              placeholder="What happened, or what you would like us to do." /></label>
            <p className="small muted">We reply within 30 days at the latest. If you are not satisfied with our answer, you can complain to the Data Protection Board of India.</p>
            <button className="btn" disabled={busy}>{busy ? 'Sending…' : 'Send request'}</button>
          </form>
        )}
      </Card>
    </div>
  )
}

import { Link } from 'react-router-dom'
import { Card, useTitle } from '../components/ui'

export default function About() {
  useTitle('About')
  return (
    <div className="page narrow prose">
      <h1>Know your air, a week ahead</h1>
      <p className="lead">Air-quality dashboards tell you what the air is like at a few dozen monitoring stations. AirAware tells you what it <i>will be</i> over the next week, for any street, and what that means for you.</p>

      <div className="grid three">
        <Card title="The problem"><p>More than a third of measured days in Pune and Mumbai are Moderate or worse. The people hit hardest, children and people with asthma or heart disease, need to plan ahead for their own street and their own health, not read a station number after the fact.</p></Card>
        <Card title="What we built"><p>A forecast up to seven days ahead for any point in either city, with an honest range, the chance of a Poor day, advice tuned to your health, and alerts for the places you care about.</p></Card>
        <Card title="Why trust it"><p>It beats "tomorrow will be like today" by a statistically significant margin, its ranges are checked against reality, and every live forecast is published on the <Link to="/track-record">track record</Link> before the day happens.</p></Card>
      </div>

      <h2>Who it is for</h2>
      <ul>
        <li><b>Parents and people with asthma or heart disease</b>: warnings one category earlier than the general public, and the cleanest hours of the day.</li>
        <li><b>Runners and outdoor workers</b>: the cleanest day and hours this week to train or schedule work outside.</li>
        <li><b>Schools, gyms and housing societies</b>: one dashboard for several places, with alerts before a bad day.</li>
        <li><b>Citizens</b>: report garbage burning or construction dust; moderated reports go on the public map.</li>
      </ul>

      <h2>How it works</h2>
      <p>Readings from 37 CPCB monitoring stations are cleaned and combined with live weather and the Copernicus CAMS particle forecast. A model trained on station data since 2020 forecasts each day's change in AQI; a clicked spot gets an estimate weighted by its distance to nearby stations. The details, and every accuracy number, are on the <Link to="/science">Science</Link> page.</p>

      <h2>Roadmap</h2>
      <ul>
        <li>Live hourly CPCB readings (built in, switched on with an OpenAQ key), making "tomorrow" a true next-day forecast.</li>
        <li>More cities: Delhi, Bengaluru, Hyderabad; the pipeline is city-agnostic.</li>
        <li>Push notifications and a WhatsApp alert channel.</li>
        <li>Low-cost sensors from housing societies to fill the gaps between government stations.</li>
      </ul>

      <h2>Open by design</h2>
      <p>Every data source is free and public, the API is documented at <a href="/api/docs">/api/docs</a>, and the whole platform runs on one small server.</p>
      <p><Link to="/signup" className="btn">Create a free account</Link></p>
    </div>
  )
}

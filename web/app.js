// AirAware dashboard: talks to the JSON API under /api.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (v, d = 0) => (v == null ? "–" : Number(v).toFixed(d));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const WEATHER = { 0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
  61: "Light rain", 63: "Rain", 65: "Heavy rain", 80: "Showers", 81: "Showers", 82: "Heavy showers", 95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm" };

let STATUS, CATS, city = new URLSearchParams(location.search).get("city") || "Pune";
let map, stationLayer, clickMarker;
const charts = {};

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function colourOf(aqi) {
  for (const c of CATS) if (c.upper == null || aqi <= c.upper) return c.colour;
}

// Smooth green-to-red scale for the heatmap: AQI 40 is green, 120 yellow, 200 orange, 280 and above red.
function heat(aqi) {
  const t = Math.max(0, Math.min(1, (aqi - 40) / 240));
  return `hsl(${130 - 130 * t} ${65 + 25 * t}% ${45 + 5 * Math.sin(Math.PI * t)}%)`;
}

function dayName(iso) {
  const d = new Date(iso + "T00:00"), t = new Date(); t.setHours(0, 0, 0, 0);
  const diff = Math.round((d - t) / 864e5);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

const todayISO = () => new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
const upcoming = (list) => { const t = todayISO(), u = list.filter((f) => f.date >= t); return u.length ? u : list.slice(-1); };
const hourName = (h) => `${h % 12 || 12} ${h < 12 ? "am" : "pm"}`;

function chart(id, config) {
  charts[id]?.destroy();
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--line");
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  charts[id] = new Chart($(id), { ...config, options: { responsive: true, maintainAspectRatio: false, ...config.options } });
}

// ---------- header ----------

async function init() {
  STATUS = await api("/api/status");
  CATS = STATUS.categories;
  $("cities").innerHTML = Object.keys(STATUS.cities).map((c) => `<button data-city="${esc(c)}">${esc(c)}</button>`).join("");
  $("cities").onclick = (e) => { if (e.target.dataset.city) selectCity(e.target.dataset.city); };
  $("legend").innerHTML = CATS.map((c) => `<span><i style="background:${c.colour}"></i>${esc(c.name)}</span>`).join("");
  const live = STATUS.live_readings;
  $("status").innerHTML = `<span class="dot ${live ? "live" : ""}"></span>` + (live
    ? `Live CPCB readings, updated ${new Date(STATUS.live_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}`
    : `Station readings to ${new Date(STATUS.cities[city].last_measured).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} (public archive, ~4 days behind) · weather live`);
  initMap();
  selectCity(city);
  loadModel();
}

function selectCity(c) {
  city = c;
  history.replaceState(null, "", `?city=${encodeURIComponent(c)}`);
  document.querySelectorAll("#cities button").forEach((b) => b.classList.toggle("on", b.dataset.city === c));
  const { lat, lon } = STATUS.cities[c];
  map.setView([lat, lon], c === "Pune" ? 11 : 11);
  loadOverview(); loadStations(); loadInsights();
}

// ---------- city overview ----------

async function loadOverview() {
  const o = await api(`/api/overview?city=${encodeURIComponent(city)}`);
  const today = o.forecast.find((f) => dayName(f.date) === "Today") || o.forecast[0];
  const tomorrow = o.forecast.find((f) => dayName(f.date) === "Tomorrow") || o.forecast[1];
  const m = o.measured, w = o.weather?.current;
  $("hero").innerHTML = `
    <div class="card aqi-card" style="background:${today.category.colour}">
      <div class="label">${esc(city)} · ${dayName(today.date)}, ${new Date(today.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} · AirAware forecast</div>
      <div class="num">${fmt(today.forecast)}</div>
      <div class="cat">${esc(today.category.name)}</div>
      <div class="sub">Likely ${fmt(today.lo)}–${fmt(today.hi)} · ${today.days_ahead} day${today.days_ahead > 1 ? "s" : ""} after the last reading · chance of Poor or worse ${Math.round(today.p_poor * 100)}%</div>
      <div class="advice">${esc(today.category.advice)}</div>
    </div>
    <div class="card stat">
      <span class="muted small">Tomorrow</span>
      <span class="big" style="color:${tomorrow ? tomorrow.category.colour : "inherit"};text-shadow:0 0 1px #0004">${tomorrow ? fmt(tomorrow.forecast) : "–"}</span>
      <span>${tomorrow ? esc(tomorrow.category.name) + ` · likely ${fmt(tomorrow.lo)}–${fmt(tomorrow.hi)}` : ""}</span>
      <div class="row"><span>Cleanest day ahead</span><b>${dayName(o.plan.best_day)} (${fmt(o.plan.best_day_aqi)})</b></div>
      <div class="row"><span>Cleanest hours</span><b>${o.plan.best_hours.map(hourName).join(", ")}</b></div>
      <div class="row"><span>Last measured ${new Date(m.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span><b>${fmt(m.aqi)} <span class="pill" style="background:${m.category.colour}">${esc(m.category.name)}</span></b></div>
    </div>
    <div class="card stat">
      <span class="muted small">Weather now${w ? " · " + new Date(w.time).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }) : ""}</span>
      <span class="big">${w ? fmt(w.temperature_2m) + "°C" : "–"}</span>
      <span>${w ? esc(WEATHER[w.weather_code] || "") + ` · feels ${fmt(w.apparent_temperature)}°C` : "Weather unavailable"}</span>
      <div class="row"><span>Humidity</span><b>${w ? fmt(w.relative_humidity_2m) + "%" : "–"}</b></div>
      <div class="row"><span>Wind</span><b>${w ? fmt(w.wind_speed_10m) + " km/h from " + compass(w.wind_direction_10m) : "–"}</b></div>
      <div class="row"><span>Breathing the last measured day</span><b>≈ ${fmt(m.cigarettes, 1)} cigarettes</b></div>
    </div>`;

  $("fc-hint").textContent = `Forecast from the last reading on ${new Date(m.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}, shaded 80% range`;
  $("days").innerHTML = upcoming(o.forecast).map((f) => `<div style="background:${f.category.colour}"><span>${dayName(f.date)}</span><b>${fmt(f.forecast)}</b>${esc(f.category.name)}</div>`).join("");
  const labels = [...o.history.map((h) => h.date), ...o.forecast.map((f) => f.date)];
  const pad = (arr, before) => [...Array(before).fill(null), ...arr];
  const n = o.history.length;
  chart("fc-chart", {
    type: "line",
    data: { labels: labels.map((d) => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })), datasets: [
      { label: "Measured", data: o.history.map((h) => h.aqi), borderColor: "#3b82f6", backgroundColor: "#3b82f6", pointRadius: 0, tension: .3 },
      { label: "80% range", data: pad(o.forecast.map((f) => f.hi), n), borderColor: "transparent", backgroundColor: "rgba(245,133,24,.22)", fill: "+1", pointRadius: 0 },
      { label: "", data: pad(o.forecast.map((f) => f.lo), n), borderColor: "transparent", pointRadius: 0 },
      { label: "AirAware forecast", data: pad(o.forecast.map((f) => f.forecast), n), borderColor: "#f58518", backgroundColor: "#f58518", borderDash: [6, 4], tension: .3 },
    ] },
    options: { interaction: { mode: "index", intersect: false }, plugins: { legend: { labels: { filter: (i) => i.text } } },
      scales: { y: { title: { display: true, text: "AQI" }, beginAtZero: true }, x: { ticks: { maxTicksLimit: 10 } } } },
  });

  const h = o.weather?.hourly;
  if (h) chart("wx-chart", {
    type: "line",
    data: { labels: h.time.map((t) => new Date(t).toLocaleString("en-IN", { weekday: "short", hour: "numeric" })), datasets: [
      { label: "Temperature °C", data: h.temperature_2m, borderColor: "#ef4444", yAxisID: "y", pointRadius: 0, tension: .3 },
      { label: "Humidity %", data: h.relative_humidity_2m, borderColor: "#06b6d4", yAxisID: "y", pointRadius: 0, tension: .3 },
      { label: "Mixing height (m)", data: h.boundary_layer_height, borderColor: "#8b5cf6", backgroundColor: "rgba(139,92,246,.12)", fill: true, yAxisID: "y2", pointRadius: 0, tension: .3 },
    ] },
    options: { interaction: { mode: "index", intersect: false }, scales: { x: { ticks: { maxTicksLimit: 8 } },
      y: { position: "left" }, y2: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "m" } } } },
  });
}

function compass(deg) {
  return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(deg / 45) % 8];
}

// ---------- map and areas ----------

function initMap() {
  map = L.map("map", { zoomControl: true }).setView([18.52, 73.86], 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 19,
  }).addTo(map);
  stationLayer = L.layerGroup().addTo(map);
  map.on("click", (e) => loadArea(e.latlng.lat, e.latlng.lng));
}

async function loadStations() {
  const s = await api(`/api/stations?city=${encodeURIComponent(city)}`);
  stationLayer.clearLayers();
  for (const st of s.stations) {
    L.circleMarker([st.lat, st.lon], { radius: 11, color: "#111", weight: 1, fillColor: st.category.colour, fillOpacity: .9 })
      .bindTooltip(`<b>${esc(st.station)}</b><br>AQI ${fmt(st.aqi)} · ${esc(st.category.name)}<br>${esc(st.date)}`)
      .on("click", (e) => { L.DomEvent.stopPropagation(e); loadArea(st.lat, st.lon); })
      .addTo(stationLayer);
  }
  $("st-hint").textContent = s.source === "live" ? "Live 24-hour averages" : "Each station's latest day in the public archive";
  const rows = [...s.stations].sort((a, b) => b.aqi - a.aqi);
  $("stations").innerHTML = `<tr><th>Station</th><th>Day</th><th class="num">AQI</th><th>Category</th><th class="num">PM2.5</th><th class="num">PM10</th><th>Check</th></tr>` +
    rows.map((r) => `<tr><td>${esc(r.station)}</td><td>${esc(r.date)}</td><td class="num"><b>${fmt(r.aqi)}</b></td>
      <td><span class="pill" style="background:${r.category.colour}">${esc(r.category.name)}</span></td>
      <td class="num">${fmt(r.pm25)}</td><td class="num">${fmt(r.pm10)}</td>
      <td class="${r.verdict && r.verdict !== "Agrees with the city" ? "warn" : "muted"}" title="Correlation with the city over 90 days: ${fmt(r.correlation, 2)}">${esc(r.verdict || "")}</td></tr>`).join("");
}

async function loadArea(lat, lon) {
  clickMarker?.remove();
  clickMarker = L.marker([lat, lon]).addTo(map);
  $("area").innerHTML = `<h2>Your area</h2><p class="muted">Looking up this spot…</p>`;
  let a;
  try { a = await api(`/api/area?lat=${lat}&lon=${lon}`); }
  catch (e) { $("area").innerHTML = `<h2>Your area</h2><p class="warn">${esc(e.message)}</p>`; return; }
  if (a.city !== city) selectCity(a.city);
  const w = a.weather?.current, t = a.today, m = a.measured;
  $("area").innerHTML = `
    <h2>Your area</h2>
    <h3>${esc(a.place || `${a.lat.toFixed(3)}, ${a.lon.toFixed(3)}`)}</h3>
    <div class="place">${esc(a.city)} · ${a.lat.toFixed(4)}, ${a.lon.toFixed(4)}</div>
    <div class="card aqi-card" style="background:${t.category.colour};box-shadow:none">
      <div class="label">${dayName(t.date)} · forecast for this area</div>
      <div class="num">${fmt(t.forecast)}</div><div class="cat">${esc(t.category.name)}</div>
      <div class="sub">Likely ${fmt(t.lo)}–${fmt(t.hi)} · ${m.offset >= 0 ? fmt(m.offset) + " above" : fmt(-m.offset) + " below"} the city average</div>
    </div>
    <div class="mini">${upcoming(a.forecast).map((f) => `<div style="background:${f.category.colour}">${dayName(f.date)}<b>${fmt(f.forecast)}</b></div>`).join("")}</div>
    <p class="small">${esc(t.category.advice)} Cleanest hours this month: <b>${a.best_hours.map(hourName).join(", ")}</b>.</p>
    ${w ? `<div class="wx"><div><b>${fmt(w.temperature_2m)}°C</b>${esc(WEATHER[w.weather_code] || "now")}</div><div><b>${fmt(w.relative_humidity_2m)}%</b>humidity</div><div><b>${fmt(w.wind_speed_10m)}</b>km/h ${compass(w.wind_direction_10m)}</div></div>` : ""}
    <p class="small muted">Last measured here (estimate from ${m.used} station${m.used > 1 ? "s" : ""} within 12 km): <b>${fmt(m.aqi)}</b>, ${esc(m.category.name)}.</p>
    <ul>${m.nearest.map((n) => `<li>${esc(n.station)}: ${fmt(n.aqi)} · ${n.km} km away</li>`).join("")}</ul>`;
}

// ---------- insights ----------

async function loadInsights() {
  const s = await api(`/api/insights?city=${encodeURIComponent(city)}`);
  const cell = {};
  for (const h of s.hourly) cell[`${h.month}-${h.hour}`] = h;
  let html = `<div class="lbl"></div>` + [...Array(24).keys()].map((h) => `<div class="lbl">${h % 3 === 0 ? h : ""}</div>`).join("");
  for (let mo = 1; mo <= 12; mo++) {
    html += `<div class="lbl">${MONTHS[mo - 1]}</div>`;
    for (let h = 0; h < 24; h++) {
      const c = cell[`${mo}-${h}`];
      html += c ? `<div title="${MONTHS[mo - 1]} ${hourName(h)}: AQI ${fmt(c.aqi)}" style="background:${heat(c.aqi)}"></div>` : `<div></div>`;
    }
  }
  $("heatmap").innerHTML = html;
  const vals = s.hourly.map((h) => h.aqi);
  $("heat-scale").innerHTML = `<span>cleaner · ${fmt(Math.min(...vals))}</span><i></i><span>${fmt(Math.max(...vals))} · dirtier</span>`;

  $("dw-hint").textContent = s.diwali.years.length ? `Diwali${s.diwali.years.length > 1 ? "s" : ""} with data: ${s.diwali.years.join(", ")}` : "No Diwali with data";
  chart("dw-chart", {
    type: "line",
    data: { labels: s.diwali.curve.map((c) => c.offset), datasets: [{ label: "AQI above the weeks before", data: s.diwali.curve.map((c) => c.change),
      borderColor: "#f59e0b", backgroundColor: "rgba(245,158,11,.18)", fill: true, tension: .3 }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: "Days from Diwali" } } } },
  });

  const share = Object.fromEntries(s.pm25_share.map((p) => [p.month, p.share * 100]));
  chart("season-chart", {
    data: { labels: MONTHS, datasets: [
      { type: "bar", label: "Average AQI", data: MONTHS.map((_, i) => s.monthly.find((m) => m.month === i + 1)?.aqi ?? null),
        backgroundColor: MONTHS.map((_, i) => colourOf(s.monthly.find((m) => m.month === i + 1)?.aqi ?? 0)), yAxisID: "y", order: 1 },
      { type: "line", label: "% of days PM2.5 led", data: MONTHS.map((_, i) => share[i + 1] ?? null), borderColor: "#6366f1", backgroundColor: "#6366f1", yAxisID: "y2", tension: .3, order: 0 },
    ] },
    options: { scales: { y: { beginAtZero: true, title: { display: true, text: "AQI" } }, y2: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false } } } },
  });

  $("cig").innerHTML = `<h2>The past year in cigarettes</h2><div class="big">≈ ${fmt(s.cigarettes_year)}</div>
    <div>${fmt(s.cigarettes_year / 365, 1)} a day, from ${esc(city)}'s average PM2.5</div>
    <p class="muted small">Berkeley Earth's rule of thumb: a day at 22 µg/m³ of PM2.5 harms about as much as smoking one cigarette. A rough comparison, not a medical measure.</p>`;
}

// ---------- model ----------

async function loadModel() {
  const m = await api("/api/model");
  const short = (n) => n.replace("AirAware: linear regression on the change", "AirAware").replace("Persistence (tomorrow = today)", "Tomorrow = today");
  const rows = [...m.table].sort((a, b) => a.MAE - b.MAE);
  $("metrics").innerHTML = `<tr><th>Method</th><th class="num">Avg error</th><th class="num">Right category</th><th class="num">Poor days caught</th></tr>` +
    rows.map((r) => `<tr class="${r.Method === m.airaware ? "best" : ""}"><td>${esc(short(r.Method))}</td><td class="num">${fmt(r.MAE, 1)}</td>
      <td class="num">${fmt(r.category_accuracy * 100)}%</td><td class="num">${fmt(r.poor_recall * 100)}%</td></tr>`).join("");
  $("dm").innerHTML = `${m.forecasts} next-day forecasts since ${new Date(m.test_from).toLocaleDateString("en-IN", { month: "long", year: "numeric" })}, each from a model trained only on earlier months.
    Diebold-Mariano test against "tomorrow = today": statistic ${fmt(m.dm.statistic, 2)}, ${esc(m.dm.text)}, so the improvement is ${m.dm.p < 0.05 ? "statistically significant" : "not significant"}.`;
  const hz = (name) => m.horizons.filter((h) => h.Method === name).sort((a, b) => a.h - b.h);
  chart("hz-chart", {
    type: "line",
    data: { labels: hz(m.airaware).map((h) => `${h.h} day${h.h > 1 ? "s" : ""}`), datasets: [
      { label: "AirAware", data: hz(m.airaware).map((h) => h.MAE), borderColor: "#2563eb", backgroundColor: "#2563eb", tension: .3 },
      { label: "Last reading repeated", data: hz(m.persistence).map((h) => h.MAE), borderColor: "#94a3b8", backgroundColor: "#94a3b8", tension: .3 },
    ] },
    options: { scales: { y: { beginAtZero: true, title: { display: true, text: "Average error (AQI points)" } } } },
  });
  const cov = hz(m.airaware).map((h) => h.coverage);
  $("hz-note").textContent = `AirAware's 80% ranges held the real AQI ${Math.round(Math.min(...cov) * 100)}–${Math.round(Math.max(...cov) * 100)}% of the time.`;
  const NAMES = { aqi: "Today's AQI", temp: "Today's temperature", temp_next: "Target-day temperature", humidity: "Today's humidity", humidity_next: "Target-day humidity",
    cams_pm25: "CAMS PM2.5 today", cams_pm10: "CAMS PM10 today", cams_pm25_next: "CAMS PM2.5 forecast", cams_pm10_next: "CAMS PM10 forecast",
    blh: "Today's mixing height", blh_next: "Target-day mixing height", aqi_7d: "Last 7 days' AQI", wind_u_next: "Target-day east-west wind",
    pm10: "Today's PM10", pm25: "Today's PM2.5", aqi_lag1: "Yesterday's AQI", rain_next: "Target-day rain", wind_next: "Target-day wind" };
  chart("imp-chart", {
    type: "bar",
    data: { labels: m.importance.map((i) => NAMES[i.feature] || i.feature), datasets: [{ data: m.importance.map((i) => i.value), backgroundColor: "#2563eb" }] },
    options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: "AQI points of extra error" } } } },
  });
}

init().catch((e) => { $("status").textContent = "Could not load: " + e.message; });

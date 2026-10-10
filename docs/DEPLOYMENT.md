# Deploying AirAware

AirAware is one Docker image: a FastAPI server that also serves the built React app, runs background jobs
(data refresh every 6 hours, daily backups, alerts, retention) and keeps its state in SQLite on a volume.
`compose.yaml` is the single deployment definition, used the same way on a laptop and on a server.

## What the app needs from a host

| Need | Why |
|---|---|
| A process that runs all the time | background refresh, alerts, backups and retention run inside the server |
| A persistent disk | SQLite database, refreshed data and backups live in the `airaware-data` volume |
| Outbound HTTPS | OpenAQ archive, Open-Meteo, OpenStreetMap |
| ~1 GB RAM, 2 GB disk | training the models on startup and after each refresh |

That rules out frontend or serverless hosts (Vercel, Netlify, Cloudflare Pages/Workers): nothing there keeps a
Python process and a disk alive. Platforms with persistent volumes (Render, Railway, Fly.io) could run it, but
need a paid always-on instance plus a volume, and would be a second, different way of running the same container.

## Recommendation: one small Linux server running `compose.yaml`, behind a named Cloudflare Tunnel

- **Server:** any VPS with Docker, for example Oracle Cloud Always Free (Ampere, free), or a ₹300–600/month VPS.
  It should also build on ARM (every base image and Python package publishes ARM builds), but that is untested.
- **HTTPS and address:** a *named* Cloudflare Tunnel on your own domain. No ports open on the server, free TLS,
  a permanent address, and the same tunnel container the laptop setup already uses.
- **Why not keep the laptop?** The current public address is a *quick* tunnel from the laptop: it disappears when
  the laptop sleeps, and its address changes whenever the tunnel restarts. Fine for demos, not for real use.

### Setting it up (about 20 minutes, needs your accounts)

1. Get a server with Docker and Docker Compose, and a domain on Cloudflare (a cheap `.in` or a free subdomain you own).
2. In Cloudflare: Zero Trust → Networks → Tunnels → Create tunnel (Cloudflared). Copy its token. Add a public
   hostname (e.g. `air.yourdomain.in`) with service `http://172.30.0.10:8000`.
3. On the server:
   ```sh
   git clone https://github.com/jayraj0975/airaware && cd airaware
   cp .env.example .env    # set TUNNEL_TOKEN and AIRAWARE_PUBLIC_URL=https://air.yourdomain.in
   docker compose --profile named up -d --build
   docker compose exec airaware python -m airaware.server.manage make-admin you@example.com   # after signing up
   ```
4. Open `https://air.yourdomain.in`, sign in, and set up two-step sign-in to open the admin console.

## Railway (the hosted option in use)

Railway runs the same Dockerfile, always on, at a fixed address, and redeploys on every push to `main`.

- Project `airaware`, service `airaware`, address `https://airaware-production-8299.up.railway.app` (port 8000).
- A volume mounted at `/app/data` holds the database, refreshed data and backups. On first start the container
  copies the starting data into the empty volume, makes it writable, then runs the server as an unprivileged user.
- Variables: `AIRAWARE_PUBLIC_URL` (the address above), `AIRAWARE_SECURE_COOKIES=1`, `PORT=8000`. Rate limits work per
  visitor only when `AIRAWARE_TRUSTED_PROXIES` names Railway's edge network and `AIRAWARE_CLIENT_IP_HEADER` names the
  header it sets; until then every visitor shares one set of limits (safe, but strict).
- Needs about 1 GB of memory while retraining, so plan for Railway's Hobby plan rather than the trial credit.

## Local development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn airaware.server.app:app --reload --port 8000     # API + built frontend
cd frontend && npm ci && npm run dev                               # http://localhost:5173, proxies /api
```

Checks before a change goes in (CI runs the same):

```sh
.venv/bin/python -m pytest                                   # backend
cd frontend && npm run lint && npm run build                 # type-check and build
npx playwright install chromium && npx playwright test       # browser tests, desktop and phone
python security/attack.py                                    # against a throwaway instance on :8002
```

## Running with Docker

```sh
docker compose up -d                   # http://localhost:8000 only
docker compose --profile quick up -d   # plus a temporary public HTTPS address (laptop demos)
docker compose logs tunnel-quick | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com'
docker compose ps                      # the airaware service shows (healthy) once trained, about 30 s
docker compose down                    # stop; data stays in the airaware-data volume
docker compose up -d --build           # upgrade after git pull
```

## Settings (`.env`, see `.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `AIRAWARE_PUBLIC_URL` | empty | the public address, for link previews and emailed links |
| `TUNNEL_TOKEN` | empty | named Cloudflare tunnel; needed only with `--profile named` |
| `AIRAWARE_SECURE_COOKIES` | 1 | sign-in cookie over HTTPS only |
| `OPENAQ_API_KEY` | empty | live hourly CPCB readings instead of the archive |
| `AIRAWARE_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM` | empty | email for alerts and password resets |
| `AIRAWARE_TRUSTED_PROXIES` | set in compose | the tunnel's fixed address; do not change |
| `AIRAWARE_REBUILD_HOURS` | 6 | how often data is refreshed and models retrained |

Secrets live only in `.env` on the machine (ignored by git and by Docker builds). Nothing secret is in the image.

## Data, backups and restore

- Everything is in the `airaware-data` volume: `airaware.db` (accounts, places, alerts, reports, logs), the daily
  tables and the download cache.
- A copy of the database is made every day to `backups/` inside the volume (newest 7 kept). Admins can download a
  fresh one from the API (`POST /api/admin/backup`).
- Copy the backups off the server now and then:
  `docker compose cp airaware:/app/data/backups ./airaware-backups`
- Restore: `docker compose down`, copy a backup over `/app/data/airaware.db` in the volume, `docker compose up -d`.

## Health and troubleshooting

- `GET /api/health` answers `{"ok": true}`; Docker uses it for the container health status.
- The admin console (Data & jobs) shows every refresh, backup and retention run with its result.
- An admin who loses their authenticator: `docker compose exec airaware python -m airaware.server.manage reset-2fa you@example.com`.
- Disk: the image is about 1 GB; old images pile up after rebuilds. `docker image prune` removes unused ones.

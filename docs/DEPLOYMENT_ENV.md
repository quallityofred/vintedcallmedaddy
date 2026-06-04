# Deployment Environment Variables

This repository deploys as two separate Railway services from the same GitHub repo.

Rotate any secret that was previously exposed outside the repository before deploying:

- database password / `DATABASE_URL`
- `SECRET_KEY`
- Telegram bot tokens
- proxy credentials
- any other exposed credential

Do not put backend secrets into the frontend service. Do not use `NEXT_PUBLIC_` for secrets.

## Backend Railway Service

Service:

- Suggested name: `vintedbot-backend`
- Platform: Railway
- Root directory: `backend`
- Build command: `poetry install --only main --no-root`
- Start command: `sh -c 'poetry run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}'`
- Healthcheck path: `/health`

Railway provides `PORT` automatically. Do not set `PORT=8080` manually in Railway unless there is a special reason. The backend start command is shell-wrapped so Railway's `PORT` value is expanded before Uvicorn starts.

In production, backend `/` redirects to `FRONTEND_URL` when configured. If `FRONTEND_URL` is not configured, `/` returns a minimal JSON service status without secrets. `/health` and `/api/health` are public, unauthenticated health probes.

### Required Variables

| Variable name | Example placeholder value | Secret? | Where to get it | Notes |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql://USER:PASSWORD@HOST:PORT/DB` | yes | Railway PostgreSQL service variables | Use a newly rotated value. The backend normalizes `postgresql://` to `postgresql+asyncpg://`. Never commit it. |
| `SECRET_KEY` | `generate-a-new-long-random-secret` | yes | Generate locally with `python -c "import secrets; print(secrets.token_urlsafe(32))"` | Required in production. Rotate if previously exposed. |
| `ENVIRONMENT` | `production` | no | Set manually in Railway | Enables production validation. |
| `FRONTEND_URL` | `https://YOUR_FRONTEND_SERVICE.up.railway.app` | no | Railway frontend public URL | Added to backend CORS origins. Set after the frontend service has a public URL. |
| `ALLOWED_ORIGINS` | `https://YOUR_FRONTEND_SERVICE.up.railway.app,http://localhost:3000` | no | Frontend URL plus local dev origin if needed | Comma-separated. Keep specific in production. |
| `SESSION_COOKIE_SECURE` | `true` | no | Set manually in Railway | Railway also implies secure cookies, but setting this explicitly is clearer. |
| `NIXPACKS_PYTHON_VERSION` | `3.11` | no | Set manually in Railway if needed | Keeps the Railway Python runtime aligned with project support. |
| `PORT` | Railway-provided | no | Railway injects this automatically | Do not hardcode or manually set it in normal Railway deploys. The shell-wrapped start command reads `${PORT:-8080}`. |

### Optional Defaults

These are bootstrap/default values only. They are not required for normal user setup.

| Variable name | Example placeholder value | Secret? | Where to get it | Notes |
| --- | --- | --- | --- | --- |
| `CHECK_INTERVAL_SECONDS` | `120` | no | Project default | Admins can override scraper defaults in the web settings UI. |
| `PROXIES` | empty | yes if credentials are included | Proxy provider | Admins can override in the web settings UI. Never commit proxy credentials. |
| `SESSIONS_PER_DOMAIN` | `3` | no | Project default | Admin UI override exists. |
| `RATE_LIMIT_PER_MINUTE` | `8` | no | Project default | Admin UI override exists. |
| `CF_WORKER_URL` | empty | no | Optional Cloudflare Worker URL | Admin UI override exists. Not required for deployment. |
| `CF_WORKER_BLOCK_THRESHOLD` | `2` | no | Project default | Admin UI override exists. |
| `CF_WORKER_RECOVERY_MINUTES` | `10` | no | Project default | Admin UI override exists. |
| `PEAK_START_HOUR` | `8` | no | Project default | Admin UI override exists. |
| `PEAK_END_HOUR` | `23` | no | Project default | Admin UI override exists. |
| `OFFPEAK_INTERVAL_MULTIPLIER` | `2.5` | no | Project default | Admin UI override exists. |
| `NIGHT_INTERVAL_MULTIPLIER` | `5.0` | no | Project default | Admin UI override exists. |

Telegram bot token and Telegram chat ID are intentionally not required backend deployment variables. Each user configures them in the authenticated web settings UI. Saved token and chat ID fields are masked/write-only in the UI.

Telegram long polling must run in only one backend process/replica for a given bot token. Keep Railway backend replicas at `1` while using polling. Multiple replicas, a stale old deployment, or another environment using the same bot token can make Start/Stop/status inconsistent because one process cannot cancel another process's polling task. If horizontal scaling is needed later, switch to a webhook architecture or add a distributed runtime lock. If a stale process cannot be stopped, rotate the token in BotFather.

Safe Telegram connection cleanup can be run manually without storing credentials:

```powershell
Set-Location backend
$env:TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
poetry run python scripts/cleanup_telegram_bot_connections.py
Remove-Item Env:\TELEGRAM_BOT_TOKEN
```

The cleanup script deletes any webhook with pending updates dropped and attempts a safe pending-update cleanup. It prints only safe status text and must not be used with real tokens in committed files or docs.

Cloudflare Worker URL and scraper defaults are intentionally not required backend deployment variables. Admins configure them in the web settings UI without redeploying.

## Frontend Railway Service

Service:

- Suggested name: `vintedbot-frontend`
- Platform: Railway
- Root directory: `frontend`
- Build command: `npm run build`
- Start command: `npm run start -- --hostname 0.0.0.0 --port $PORT`

### Required Variables

| Variable name | Example placeholder value | Secret? | Where to get it | Notes |
| --- | --- | --- | --- | --- |
| `BACKEND_URL` | `https://YOUR_BACKEND_SERVICE.up.railway.app` | no | Railway backend public URL | Used server-side by Next.js rewrites/proxy. Client code should prefer relative `/api/...` requests. |

### Optional Variables

| Variable name | Example placeholder value | Secret? | Where to get it | Notes |
| --- | --- | --- | --- | --- |
| `NEXT_PUBLIC_APP_NAME` | `Vinted Monitor` | no | Project default | Public UI label. |
| `NEXT_PUBLIC_SPLINE_SCENE_URL` | empty | no | Spline export URL if used | Public URL only. Leave empty until a scene is ready. |
| `NEXT_PUBLIC_LEGACY_LOGIN_URL` | empty | no | Backend public login URL if a temporary fallback link is needed | Optional public URL only. Leave empty to hide the fallback in production. |

## After Creating Railway Services

1. Create a backend service from `https://github.com/tellaboutme/vintedbot.git`.
2. Set the backend root directory to `backend`.
3. Add backend variables from the required backend table.
4. Deploy the backend service.
5. Copy the backend public URL.
6. Create a frontend service from the same GitHub repo.
7. Set the frontend root directory to `frontend`.
8. Add frontend variable: `BACKEND_URL=https://YOUR_BACKEND_SERVICE.up.railway.app`.
9. Deploy the frontend service.
10. Copy the frontend public URL.
11. Update backend variables:
    - `FRONTEND_URL=https://YOUR_FRONTEND_SERVICE.up.railway.app`
    - `ALLOWED_ORIGINS=https://YOUR_FRONTEND_SERVICE.up.railway.app,http://localhost:3000`
12. Redeploy the backend service.
13. Open the frontend URL.
14. Sign in to the backend UI or migrated frontend flow when available.
15. Configure per-user Telegram bot token/chat ID in the web settings page.
16. Configure Cloudflare Worker and scraper defaults from an admin account in the settings page if needed.

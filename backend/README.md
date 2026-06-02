# Vinted Monitor Backend

FastAPI backend for the Vinted Monitor Bot. This service owns authentication, sessions, CSRF, database access, scheduler jobs, Vinted scraping, Telegram bot polling, notifications, and the legacy Jinja dashboard.

## Local Development

```bash
poetry install
cp .env.example .env
poetry run pytest -q
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

`DATABASE_URL=sqlite+aiosqlite:///./data/vinted.db` keeps local development on SQLite. Production should use PostgreSQL through Railway.

## Railway

Use this directory as the Railway backend service root.

- Build command: `poetry install --only main --no-root`
- Start command: `poetry run uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Required production variables are documented in `../docs/DEPLOYMENT_ENV.md`.

## Settings Ownership

- Telegram bot token and chat ID are stored per user and configured from the web settings UI.
- Cloudflare Worker fallback settings and scraper defaults are global admin settings stored in `AppSettings`.
- Environment variables remain bootstrap/default values, not normal user setup requirements for Telegram or Cloudflare Worker.

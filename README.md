# Vinted Monitor Bot

Monorepo for a Vinted monitoring service with Telegram notifications, a FastAPI backend, the legacy Jinja dashboard, and a Next.js frontend migration.

## Structure

```text
backend/   FastAPI backend, scheduler, scraper, Telegram bots, database, legacy Jinja UI, backend tests
frontend/  Next.js App Router frontend, TypeScript, Tailwind CSS, shadcn/ui, Motion, Spline placeholder, Playwright tests
docs/      Deployment and environment documentation
```

## Backend

```bash
cd backend
poetry install
poetry run pytest -q
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Copy `backend/.env.example` to `backend/.env` for local backend development. Do not commit real secrets.

## Frontend

```bash
cd frontend
npm install
npm run lint
npm run build
npm run dev
```

Copy `frontend/.env.example` to `frontend/.env.local` for local frontend development.

## Deployment

Railway should use two separate services from this repository:

- Backend service root directory: `backend`
- Frontend service root directory: `frontend`

See [docs/DEPLOYMENT_ENV.md](docs/DEPLOYMENT_ENV.md) for exact build/start commands, required variables, and the URL wiring order.

## Security

Never commit `.env` files, database dumps, Telegram bot tokens, database passwords, proxy credentials, or session data. If a secret was exposed outside the repository, rotate it before deployment.

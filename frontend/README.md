# Vinted Monitor Frontend

Next.js frontend foundation for the Vinted Monitor dashboard migration.

## Commands

```bash
npm install
npm run dev
npm run lint
npm run build
npm run test:e2e
```

## Environment

Copy `.env.example` to `.env.local` for local frontend development.

```bash
BACKEND_URL=http://localhost:8080
NEXT_PUBLIC_APP_NAME=Vinted Monitor
NEXT_PUBLIC_SPLINE_SCENE_URL=
```

`BACKEND_URL` is used by `next.config.ts` rewrites so browser requests can call `/api/*` from the Next app and proxy to the FastAPI backend.

## Railway

Use this directory as the Railway frontend service root.

- Build command: `npm ci && npm run build`
- Start command: `npm run start -- --hostname 0.0.0.0 --port $PORT`
- Required variable: `BACKEND_URL=https://YOUR_BACKEND_SERVICE.up.railway.app`

Do not put backend secrets in frontend environment variables. Only `NEXT_PUBLIC_*` values are exposed to browser code.

## Scope

Phase 1 is frontend-only:

- Existing FastAPI/Jinja routes remain untouched.
- Auth, session cookies, CSRF, scheduler, scraper, and Telegram runtime behavior remain backend-owned.
- The current pages are placeholders until versioned FastAPI JSON APIs are added in later phases.

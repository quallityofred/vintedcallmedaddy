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

## Scope

Phase 1 is frontend-only:

- Existing FastAPI/Jinja routes remain untouched.
- Auth, session cookies, CSRF, scheduler, scraper, and Telegram runtime behavior remain backend-owned.
- The current pages are placeholders until versioned FastAPI JSON APIs are added in later phases.

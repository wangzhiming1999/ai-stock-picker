# Deployment Architecture

## Frontend

- Framework: React 18 + Vite 6 + TypeScript.
- Owner: repository owner.
- Deployment: Vercel project `frontend` (`prj_h8Jn0uqaseg3da15M9X2rwTPoRpK`).
- Local link: `frontend/.vercel/project.json`.
- Production API route: `frontend/vercel.json` rewrites `/api/*` to
  `https://backend-smoky-kappa-70.vercel.app/api/*`.

## Backend

- Framework: Python 3.11 + FastAPI, packaged as Vercel Functions.
- Owner: repository owner.
- Deployment: Vercel project `backend` (`prj_xk3deYtD1BrFsIMhcOWPupWu8U5y`).
- Local link: `backend/.vercel/project.json`.
- Root directory in Vercel: `backend`.
- Production URL: `https://backend-smoky-kappa-70.vercel.app`.
- Scheduled jobs are declared in `backend/vercel.json`.

## Storage and authentication

- Supabase provides Postgres persistence and authentication.
- The production Supabase project already exists, but its project ref, name,
  organization and binding confirmation are not recorded in this repository.
- Deployment must not run `supabase link`, write Supabase environment variables,
  or push remote migrations until the user explicitly confirms that identity.
- Schema changes remain replayable SQL files under `backend/supabase-schema-v*.sql`.
  They are applied through the existing admin migration flow or manually in the
  confirmed Supabase project.
- Service-role credentials are backend-only and must never be exposed to the frontend.

## Delivery boundary

- Code deployment uses the two existing Vercel project links above.
- Frontend and backend are deployed separately from their respective directories.
- The root `.vercel/project.json` is a legacy/general project link and is not the
  deployment target for either application.
- Database binding, secret rotation and remote migration execution require explicit
  project identity confirmation and are outside an ordinary code deployment.

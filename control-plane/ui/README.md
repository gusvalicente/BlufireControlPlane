# BluFire Ops admin UI

Next.js 15 (App Router, React 19, TypeScript) admin console for the BluFire control plane. Material 3 styling
(blue primary, white and cool-gray surfaces), light and dark themes, phone-first with a navigation rail on wide screens.

Every screen talks to `platform-api` per `docs/api-contract.md`. All API calls run on the server (server components and
server actions) with the signed-in user's token. The browser never sees an access token.

## Run locally (mock mode)

```bash
npm ci
npm run dev            # http://localhost:3000
```

Mock mode is on whenever `PLATFORM_API_URL` is unset or `UI_MOCK=1`. It serves fixture data from `lib/fixtures/`
(placeholder clients only), skips sign-in with a fake "Gus" Admin session, and keeps edits in memory until restart.
Saving a setting runs the same approval classification the API uses, so you can see "Saved" vs "Sent for approval".

## Environment variables

| Variable | Purpose |
| --- | --- |
| `PLATFORM_API_URL` | Internal URL of platform-api. Unset = mock mode. |
| `PLATFORM_API_SCOPE` | Delegated API scope, for example `api://blufire-platform-api/access_as_user` |
| `AUTH_SECRET` | Auth.js cookie encryption secret (Key Vault `ui-auth-secret`) |
| `AUTH_URL` | Public URL of the UI, for example `https://ops.example.com` |
| `AUTH_MICROSOFT_ENTRA_ID_ID` | Client ID of the admin UI app registration |
| `AUTH_MICROSOFT_ENTRA_ID_SECRET` | Client secret (Key Vault `ui-entra-client-secret`) |
| `AUTH_MICROSOFT_ENTRA_ID_ISSUER` | `https://login.microsoftonline.com/<tenant>/v2.0` |
| `UI_MOCK` | `1` forces mock mode |
| `NEXT_PUBLIC_TIMEZONE` | Display time zone, default `America/New_York` |

The app registration needs the redirect URI `<AUTH_URL>/api/auth/callback/microsoft-entra-id` and the API permission
for `PLATFORM_API_SCOPE`.

## How auth works

- Auth.js v5 with the Microsoft Entra ID provider. `middleware.ts` sends any unauthenticated request to `/signin`.
- The JWT callback stores the API access token, refresh token and ID token in the encrypted session cookie only.
  The session object exposed at `/api/auth/session` never contains them. `lib/token.ts` reads them server side.
- Access tokens refresh automatically through the Entra token endpoint.
- Step-up MFA: approving a change and rotating a secret send the ID token as `X-Step-Up-Token`. If the API answers
  `403 step_up_required`, the UI signs in again with `prompt=login&max_age=0`, returns to the same page with
  `?retry=approve` (or `?retry=rotate:<id>`), and runs the action once more.

## Scripts

| Command | What it does |
| --- | --- |
| `npm run lint` | ESLint (Next.js core web vitals and TypeScript rules) |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run build` | Production build (`output: standalone`) |
| `node scripts/screens.mjs http://localhost:3000` | Screenshots `/`, an app, a change and Security at 390x844, light and dark, into `screenshots/`. Start the app first. |

## Container

`Dockerfile` builds the standalone server and runs it as a non-root user on port 3000. Liveness probe: `GET /healthz`
(no auth, no API call).

## Layout

```
app/
  (app)/            signed-in screens: Fleet, Apps, Changes, Security, More and its pages
  signin/           sign-in page
  actions.ts        server actions (propose change, approve, reject, ops, drift, rotate, graduate, step-up)
  api/auth/         Auth.js route handlers
  healthz/          liveness probe
components/         shell, navigation, sheets, snackbar, diff view, cards
lib/
  api.ts            typed platform-api client (server only)
  types.ts          contract types
  mock.ts           in-memory mock API over lib/fixtures
  approval.ts       approval rule matching and JSON merge patch helpers
  token.ts, entra.ts  token access and refresh
auth.ts, middleware.ts
```

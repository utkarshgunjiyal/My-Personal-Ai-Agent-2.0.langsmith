# Test Credentials — AI Decision Engine

> These are auto-seeded by `backend/auth/routes.py::seed_admin()` on startup.

## Admin (email/password)
- **Email:** `admin@decision-engine.dev`
- **Password:** `admin123`
- **Role:** `admin`
- **Auth provider:** `password`

The admin user has access to the global stats view on `/dashboard` (all users' data).

## Test user
For testing user-level isolation, register a fresh account via the UI (`/register`)
or via API:

```bash
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"alice123","name":"Alice"}'
```

## Google OAuth (Emergent-managed)
- Click **"Continue with Google"** on `/login` or `/register`.
- You'll be redirected to `https://auth.emergentagent.com` and back to `/app#session_id=...`.
- `AuthCallback.js` exchanges the `session_id` for a long-lived session via
  `POST /api/auth/google/session`.

## Endpoints
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET  /api/auth/me`
- `POST /api/auth/refresh`
- `POST /api/auth/forgot-password`
- `POST /api/auth/reset-password`
- `POST /api/auth/google/session`

## Notes
- Brute force lockout: 5 failed attempts → 15-minute lockout per `{ip}:{email}`.
- Cookies: `access_token`, `refresh_token` (JWT path) and `session_token`
  (Google path). All httpOnly, `SameSite=None`, `Secure=True`.

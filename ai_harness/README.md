# AI Harness

A chat application where users **sign in with OAuth** and chat with Claude on
**their own AI subscription**: each user connects their personal Anthropic API
key once, and all usage bills to their own Anthropic account.

> Why not "Sign in with Claude"? Anthropic prohibits (and server-side blocks)
> consumer-subscription OAuth tokens outside Claude Code / Claude.ai, and
> offers no OAuth client registration for third-party apps. The sanctioned
> model is exactly this: OAuth for *identity*, per-user API keys for *usage*.

## How it works

1. **Login** — Google OAuth (OIDC via Authlib). Identity only; no Google data
   beyond email/name/avatar is used.
2. **Connect subscription** — the user pastes their Anthropic API key once
   (console.anthropic.com → API keys). It is validated against the Models API,
   encrypted with Fernet, and stored server-side in SQLite against their
   account. It never returns to the browser.
3. **Chat** — requests are authorized by the session cookie; the server
   decrypts the user's key per request and streams Claude's response back over
   SSE (live text, collapsible summarized thinking, token usage).

## Features

- Model picker populated with the models the user's key can actually access
  (default Claude Opus 5)
- Effort control (low / medium / high / xhigh / max) on supporting models
- Adaptive thinking with summarized display
- Server-side refusal fallbacks on Opus 5 / Fable 5 (`fallbacks: "default"`),
  with automatic retry without the beta if the account lacks it
- Per-browser system prompt; local conversation history with "New chat"
- Key management: replace or disconnect the key in Settings; revoked keys are
  detected and force re-entry

## Setup

```sh
pip install -r requirements.txt
```

Create OAuth credentials at Google Cloud Console → APIs & Services →
Credentials → "OAuth client ID" (Web application), with authorized redirect
URI `https://<your-host>/auth/callback` (or `http://localhost:8001/auth/callback`
for local use). Then:

```sh
export GOOGLE_CLIENT_ID=…
export GOOGLE_CLIENT_SECRET=…
export HARNESS_SECRET_KEY=…   # optional; auto-generated + persisted if unset
python ai_harness/app.py       # http://localhost:8001 (PORT to override)
```

For local testing without Google credentials:

```sh
ALLOW_DEV_LOGIN=1 python ai_harness/app.py   # enables the "Dev login" button
```

Data lives in `ai_harness/instance/` (SQLite DB + generated secret) — this
directory is gitignored; back it up or mount it in deployment.

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Chat UI |
| `/auth/login` → `/auth/callback` | GET | Google OAuth flow |
| `/auth/dev` | POST | Dev login (only with `ALLOW_DEV_LOGIN=1`) |
| `/auth/logout` | POST | Clear session |
| `/api/me` | GET | Session info: user, key status, available models |
| `/api/key` | POST / DELETE | Validate + store, or remove, the user's API key |
| `/api/chat` | POST | Streaming chat (SSE): `{model, effort, system, messages}` |

# AI Harness

A bring-your-own-key chat application: users connect their own Anthropic API
subscription and talk to Claude through this app.

## How it works

- On first load the app asks for the user's Anthropic API key
  (console.anthropic.com → API keys). The key is kept **only in the browser's
  localStorage** — the server is a stateless streaming proxy and never stores
  keys or conversations.
- The key is validated against the Models API, and the model picker is
  populated with the models that key can actually access.
- Chat requests stream back over Server-Sent Events with live text, a
  collapsible "thinking" panel (summarized reasoning), and per-message token
  usage.

## Features

- **Model picker** — defaults to Claude Opus 5; lists whatever the user's
  subscription has access to.
- **Effort control** — low / medium / high / xhigh / max via
  `output_config.effort` (sent only for models that support it).
- **Adaptive thinking** — enabled with summarized display on supporting models.
- **Refusal fallbacks** — on Opus 5 / Fable 5, requests opt into server-side
  refusal fallbacks (`fallbacks: "default"`), so a safety-classifier decline is
  automatically retried on the recommended fallback model. If the beta isn't
  available to the account, the request is retried without it.
- **Custom system prompt** — set per-browser in Settings.
- **Local history** — the conversation persists in localStorage; "New chat"
  clears it.

## Run

```sh
pip install -r ../requirements.txt   # from ai_harness/, or -r requirements.txt from repo root
python ai_harness/app.py             # serves on http://localhost:8001 (PORT env to override)
```

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Chat UI |
| `/api/validate` | POST | Validate an API key; returns the models it can access |
| `/api/chat` | POST | Streaming chat (SSE): `{api_key, model, effort, system, messages}` |

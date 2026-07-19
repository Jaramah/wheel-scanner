# Ensemble — Multi-Agent Operating Platform

A platform where you register **multiple coding agents** (by their subscription
key or API key), assemble them onto a project, and let them **collaborate and
double-check each other's work**.

It lives alongside the wheel scanner in this repo but is fully self-contained
in `agent_platform/`.

## What it does

1. **Connect agents.** Add as many agents as you like, each backed by a
   different provider and its own credential. Credentials are encrypted at rest
   (Fernet) and never returned to the browser — only a masked hint is shown.

2. **Create projects & tasks.** A task is a spec/prompt the agents will work on.

3. **Assemble a team and run a collaboration.** Two modes:

   | Mode | What happens |
   |------|--------------|
   | **Build + cross-review** | One agent drafts a solution; every other agent independently reviews it and returns a verdict (APPROVE / REQUEST_CHANGES). The builder revises until all reviewers approve or the round limit is hit. |
   | **Independent + synthesize** | Every agent drafts its own solution, then cross-reviews another agent's draft (round-robin), and a synthesizer merges the best of everything into one final answer. |

   The full transcript — every draft, every review, every verdict — is shown
   live in the UI.

## Supported providers

| Provider | Programmatic API | Credential |
|----------|------------------|------------|
| Anthropic (Claude API) | ✅ real HTTPS calls | API key |
| OpenAI | ✅ real HTTPS calls | API key |
| Google Gemini | ✅ real HTTPS calls | API key |
| OpenAI-compatible / Local (Ollama, LM Studio, vLLM) | ✅ real HTTPS calls | optional key + base URL |
| Claude Max/Pro subscription | ⚠️ demo (no public API) | subscription token |
| ChatGPT Plus subscription | ⚠️ demo (no public API) | subscription token |
| Mock agent | offline | none |

> **Why the subscription providers are "demo":** consumer subscription plans
> (Claude Max/Pro, ChatGPT Plus) do not expose a public server-side API you can
> drive with a token. The platform stores the credential and runs those agents
> through a deterministic local **mock** so the collaboration workflow is fully
> demonstrable, but it does not attempt to scrape or impersonate a logged-in
> subscription session. Providers with a real API are called for real.

Agents left without a credential (or on a local endpoint that's unreachable)
also fall back to the mock automatically, so the whole flow always runs.

## Run locally

```bash
cd agent_platform
pip install -r requirements.txt
python app.py
# open http://localhost:5001
```

Try it with **zero credentials**: add two or three "Mock agent" agents, create
a project + task, select the agents, and hit **Run collaboration** to watch the
build → review → revise loop.

## Configuration

| Env var | Purpose | Default |
|---------|---------|---------|
| `PORT` | HTTP port | `5001` |
| `AGENT_PLATFORM_SECRET` | Master secret used to derive the encryption key. Set this in production instead of relying on the generated `.secret.key` file. | generated `.secret.key` |
| `AGENT_PLATFORM_DB` | SQLite path | `agent_platform/platform.db` |
| `AGENT_PLATFORM_HTTP_TIMEOUT` | Provider HTTP timeout (s) | `90` |

## Architecture

```
app.py           Flask app: JSON API + serves the SPA, launches run threads
orchestrator.py  Multi-agent collaboration (cross-review + ensemble)
providers.py     Provider adapters (Anthropic/OpenAI/Gemini/OpenAI-compatible/mock)
crypto.py        Fernet encryption for stored credentials
db.py            SQLite persistence (agents, projects, tasks, runs, steps)
static/          Single-page UI (vanilla JS)
```

## Security notes

- Credentials are encrypted at rest and only ever decrypted server-side at call
  time. The API returns a masked hint (`sk-a…z9`), never the raw key.
- `.secret.key` and `platform.db` are gitignored — do not commit them.
- This MVP has no user accounts/auth; run it behind your own auth for
  multi-user or internet-facing deployments.

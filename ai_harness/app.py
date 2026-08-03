"""AI Harness — OAuth login, with two ways to pay for usage.

Users sign in with Google OAuth (identity only), then either:

  1. BYO key   — connect their own Anthropic API key once (validated,
                 encrypted, stored server-side; billed to their own account), or
  2. Subscribe — pick a plan that runs on the app-owned API key
                 (HARNESS_APP_API_KEY) with a metered monthly allowance.
                 Billing is currently STUBBED: choosing a plan activates it
                 immediately. Replace activate/cancel in /api/subscribe with a
                 Stripe Checkout + webhook flow before charging real money.

Usage is metered per user per calendar month for everyone; quotas are
enforced only for plan users. An active plan takes precedence over a stored
personal key.

Configuration (env vars):
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET  Google OAuth credentials
        (create at console.cloud.google.com → APIs & Services → Credentials,
         authorized redirect URI: <base-url>/auth/callback)
    HARNESS_APP_API_KEY  App-owned Anthropic key funding subscription plans
                         (subscriptions are hidden if unset)
    HARNESS_SECRET_KEY   Session/encryption secret (auto-generated if unset)
    ALLOW_DEV_LOGIN=1    Enable a no-OAuth dev login for local testing
    PORT                 Listen port (default 8001)

Run:  python ai_harness/app.py
"""

import json
import os
from datetime import datetime, timezone
from functools import wraps

import anthropic
from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session

from storage import Storage, load_secret

app = Flask(__name__, static_folder="static")
app.secret_key = load_secret()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

storage = Storage(app.secret_key)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
ALLOW_DEV_LOGIN = os.environ.get("ALLOW_DEV_LOGIN") == "1"
APP_API_KEY = os.environ.get("HARNESS_APP_API_KEY", "").strip()

oauth = None
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)
    oauth.register(
        "google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 64000

MODEL_NAMES = {
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-sonnet-5": "Claude Sonnet 5",
    "claude-opus-5": "Claude Opus 5",
}

# Subscription plans, funded by HARNESS_APP_API_KEY. The allowance is in
# "weighted tokens": input + OUTPUT_WEIGHT * output, mirroring the ~1:5
# input:output price ratio so the quota tracks real cost.
OUTPUT_WEIGHT = 5
PLANS = {
    "starter": {
        "name": "Starter",
        "price": "$10/mo",
        "allowance": 5_000_000,
        "models": ["claude-sonnet-5", "claude-haiku-4-5"],
        "blurb": "Everyday chat on Sonnet and Haiku.",
    },
    "pro": {
        "name": "Pro",
        "price": "$25/mo",
        "allowance": 25_000_000,
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
        "blurb": "5x the allowance, plus Opus.",
    },
}

# Models that support adaptive thinking + output_config.effort. Anything else
# (e.g. Haiku 4.5) gets a plain request — sending these params there is a 400.
ADAPTIVE_THINKING_MODELS = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)

# Models whose safety classifiers can decline a request; opt into server-side
# refusal fallbacks so a decline is retried on a fallback model automatically.
FALLBACK_MODELS = ("claude-fable-5", "claude-mythos-5", "claude-opus-5")

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def supports_adaptive(model: str) -> bool:
    return model.startswith(ADAPTIVE_THINKING_MODELS)


def supports_fallbacks(model: str) -> bool:
    return model.startswith(FALLBACK_MODELS)


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def weighted_usage(usage_row: dict) -> int:
    return usage_row["input_tokens"] + OUTPUT_WEIGHT * usage_row["output_tokens"]


def plan_catalog() -> list:
    return [
        {
            "id": pid,
            "name": p["name"],
            "price": p["price"],
            "allowance": p["allowance"],
            "models": [MODEL_NAMES.get(m, m) for m in p["models"]],
            "blurb": p["blurb"],
        }
        for pid, p in PLANS.items()
    ]


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def api_error_payload(exc: Exception, on_plan: bool) -> dict:
    if isinstance(exc, anthropic.AuthenticationError):
        if on_plan:
            return {"type": "error", "error": "The app's subscription backend is misconfigured. Contact the operator."}
        return {"type": "error", "error": "Your stored API key is no longer valid — reconnect it in Settings."}
    if isinstance(exc, anthropic.PermissionDeniedError):
        return {"type": "error", "error": "This account doesn't have permission for that model."}
    if isinstance(exc, anthropic.NotFoundError):
        return {"type": "error", "error": "Model not found for this account."}
    if isinstance(exc, anthropic.RateLimitError):
        retry_after = exc.response.headers.get("retry-after", "a moment")
        return {"type": "error", "error": f"Rate limited by the API. Retry after {retry_after}s."}
    if isinstance(exc, anthropic.APIStatusError):
        return {"type": "error", "error": f"API error ({exc.status_code}): {exc.message}"}
    if isinstance(exc, anthropic.APIConnectionError):
        return {"type": "error", "error": "Could not reach the Anthropic API. Check your connection."}
    return {"type": "error", "error": f"Unexpected error: {exc}"}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("sub"):
            return jsonify({"error": "Not logged in."}), 401
        return f(*args, **kwargs)

    return wrapper


def list_models(client: anthropic.Anthropic) -> list:
    models = [{"id": m.id, "name": m.display_name} for m in client.models.list()]
    models.sort(key=lambda m: (not m["id"].startswith(DEFAULT_MODEL), m["id"]))
    return models


def usage_summary(sub: str, plan_id: str | None) -> dict | None:
    """Usage block for /api/me and quota checks. None when nothing to report."""
    row = storage.get_usage(sub, current_period())
    used = weighted_usage(row)
    summary = {
        "period": current_period(),
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "messages": row["messages"],
        "used": used,
    }
    if plan_id and plan_id in PLANS:
        allowance = PLANS[plan_id]["allowance"]
        summary["allowance"] = allowance
        summary["pct"] = min(100, round(used * 100 / allowance, 1))
    return summary


# ---------------------------------------------------------------- auth routes

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/auth/login")
def auth_login():
    if not oauth:
        return jsonify({"error": "Google OAuth is not configured on this server."}), 503
    redirect_uri = request.url_root.rstrip("/") + "/auth/callback"
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/callback")
def auth_callback():
    if not oauth:
        return redirect("/")
    token = oauth.google.authorize_access_token()
    info = token.get("userinfo") or {}
    sub = info.get("sub")
    if not sub:
        return jsonify({"error": "OAuth login failed."}), 401
    storage.upsert_user(sub, info.get("email", ""), info.get("name", ""), info.get("picture", ""))
    session["sub"] = sub
    session.permanent = True
    return redirect("/")


@app.post("/auth/dev")
def auth_dev():
    """Local-testing login that bypasses OAuth. Enabled only via ALLOW_DEV_LOGIN=1."""
    if not ALLOW_DEV_LOGIN:
        return jsonify({"error": "Dev login is disabled."}), 403
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "dev@localhost").strip()
    sub = f"dev:{email}"
    storage.upsert_user(sub, email, email.split("@")[0], "")
    session["sub"] = sub
    return jsonify({"ok": True})


@app.post("/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


# ----------------------------------------------------------------- api routes

@app.get("/api/me")
def me():
    sub = session.get("sub")
    if not sub:
        return jsonify({
            "logged_in": False,
            "oauth_configured": bool(oauth),
            "dev_login": ALLOW_DEV_LOGIN,
        })
    user = storage.get_user(sub) or {}
    api_key = storage.get_api_key(sub)
    plan_id = user.get("plan") if user.get("plan") in PLANS else None

    payload = {
        "logged_in": True,
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "has_key": bool(api_key),
        "plan": plan_id,
        "plan_name": PLANS[plan_id]["name"] if plan_id else None,
        "subscriptions_available": bool(APP_API_KEY),
        "plans": plan_catalog(),
        "usage": usage_summary(sub, plan_id),
        "models": [],
    }

    if plan_id:
        # Plan users chat on the app key: fixed, plan-scoped model list.
        payload["models"] = [
            {"id": m, "name": MODEL_NAMES.get(m, m)} for m in PLANS[plan_id]["models"]
        ]
    elif api_key:
        try:
            payload["models"] = list_models(anthropic.Anthropic(api_key=api_key))
        except anthropic.AuthenticationError:
            # Key was revoked since it was stored — force re-entry.
            storage.set_api_key(sub, None)
            payload["has_key"] = False
        except (anthropic.APIStatusError, anthropic.APIConnectionError):
            payload["models"] = [{"id": DEFAULT_MODEL, "name": "Claude Opus 5"}]
    return jsonify(payload)


@app.post("/api/subscribe")
@login_required
def subscribe():
    """Activate or cancel a plan.

    BILLING STUB: activation is immediate and free. For production, replace
    the activate path with a Stripe Checkout session and move set_plan() into
    the checkout.session.completed / customer.subscription.deleted webhooks.
    """
    if not APP_API_KEY:
        return jsonify({"ok": False, "error": "Subscriptions are not enabled on this server."}), 503
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan")
    if plan_id is None:
        storage.set_plan(session["sub"], None)
        return jsonify({"ok": True, "plan": None})
    if plan_id not in PLANS:
        return jsonify({"ok": False, "error": "Unknown plan."}), 400
    storage.set_plan(session["sub"], plan_id)
    return jsonify({
        "ok": True,
        "plan": plan_id,
        "note": "Billing stub — plan activated without payment.",
    })


@app.post("/api/key")
@login_required
def set_key():
    """Validate and store the user's API key server-side (encrypted)."""
    data = request.get_json(silent=True) or {}
    key = (data.get("api_key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "No API key provided."}), 400
    try:
        models = list_models(anthropic.Anthropic(api_key=key))
    except anthropic.AuthenticationError:
        return jsonify({"ok": False, "error": "Invalid API key."}), 401
    except anthropic.APIStatusError as e:
        return jsonify({"ok": False, "error": f"API error ({e.status_code}): {e.message}"}), 502
    except anthropic.APIConnectionError:
        return jsonify({"ok": False, "error": "Could not reach the Anthropic API."}), 502
    storage.set_api_key(session["sub"], key)
    return jsonify({"ok": True, "models": models})


@app.delete("/api/key")
@login_required
def delete_key():
    storage.set_api_key(session["sub"], None)
    return jsonify({"ok": True})


def build_request_kwargs(model: str, messages: list, system: str, effort: str) -> dict:
    kwargs = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if supports_adaptive(model):
        kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        if effort in EFFORT_LEVELS:
            kwargs["output_config"] = {"effort": effort}
    return kwargs


@app.post("/api/chat")
@login_required
def chat():
    sub = session["sub"]
    user = storage.get_user(sub) or {}
    plan_id = user.get("plan") if user.get("plan") in PLANS else None

    data = request.get_json(silent=True) or {}
    model = (data.get("model") or DEFAULT_MODEL).strip()
    system = (data.get("system") or "").strip()
    effort = (data.get("effort") or "").strip()
    messages = data.get("messages") or []
    if not messages:
        return jsonify({"error": "No messages provided."}), 400

    if plan_id:
        # Subscription mode: app-owned key, plan model list, monthly quota.
        if not APP_API_KEY:
            return jsonify({"error": "Subscriptions are not enabled on this server."}), 503
        plan = PLANS[plan_id]
        if model not in plan["models"]:
            return jsonify({"error": f"The {plan['name']} plan doesn't include that model."}), 403
        used = weighted_usage(storage.get_usage(sub, current_period()))
        if used >= plan["allowance"]:
            return jsonify({
                "error": f"You've used your {plan['name']} allowance for this month. "
                         "It resets at the start of next month — or upgrade in Settings.",
                "quota_exceeded": True,
            }), 402
        key = APP_API_KEY
    else:
        key = storage.get_api_key(sub)
        if not key:
            return jsonify({"error": "No API key or plan connected. Set one up in Settings."}), 400

    def generate():
        client = anthropic.Anthropic(api_key=key)
        kwargs = build_request_kwargs(model, messages, system, effort)

        def open_stream(with_fallbacks: bool):
            if with_fallbacks:
                return client.beta.messages.stream(
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    **kwargs,
                )
            return client.messages.stream(**kwargs)

        attempts = [True, False] if supports_fallbacks(model) else [False]
        try:
            stream_cm = None
            for i, use_fallbacks in enumerate(attempts):
                try:
                    stream_cm = open_stream(use_fallbacks)
                    stream_cm.__enter__()
                    break
                except anthropic.BadRequestError:
                    # The fallbacks beta may not be available to every account;
                    # retry the same request without it before giving up.
                    if i + 1 < len(attempts):
                        continue
                    raise

            try:
                for event in stream_cm:
                    if event.type == "content_block_start":
                        if event.content_block.type == "thinking":
                            yield sse({"type": "thinking_start"})
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield sse({"type": "text", "text": event.delta.text})
                        elif event.delta.type == "thinking_delta" and event.delta.thinking:
                            yield sse({"type": "thinking", "text": event.delta.thinking})
                final = stream_cm.get_final_message()
            finally:
                stream_cm.__exit__(None, None, None)

            # Meter everyone (plan quotas + BYO-key usage display).
            storage.add_usage(
                sub, current_period(),
                final.usage.input_tokens, final.usage.output_tokens,
            )

            if final.stop_reason == "refusal":
                detail = ""
                if final.stop_details and getattr(final.stop_details, "explanation", None):
                    detail = f" ({final.stop_details.explanation})"
                yield sse({
                    "type": "refusal",
                    "error": "The model declined this request for safety reasons." + detail,
                })
                return

            done = {
                "type": "done",
                "model": final.model,
                "stop_reason": final.stop_reason,
                "usage": {
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                },
            }
            if plan_id:
                done["quota"] = usage_summary(sub, plan_id)
            yield sse(done)
        except Exception as exc:  # surfaced to the client as an SSE error event
            yield sse(api_error_payload(exc, on_plan=bool(plan_id)))

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port, threaded=True)

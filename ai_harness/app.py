"""AI Harness — OAuth login + per-user API keys.

Users sign in with Google OAuth (identity only). Each user then connects their
own Anthropic API subscription once: the key is validated, encrypted, and
stored server-side against their account — it never returns to the browser.
Chat requests are authorized by the session cookie and billed to that user's
own Anthropic account.

Configuration (env vars):
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET  Google OAuth credentials
        (create at console.cloud.google.com → APIs & Services → Credentials,
         authorized redirect URI: <base-url>/auth/callback)
    HARNESS_SECRET_KEY   Session/encryption secret (auto-generated if unset)
    ALLOW_DEV_LOGIN=1    Enable a no-OAuth dev login for local testing
    PORT                 Listen port (default 8001)

Run:  python ai_harness/app.py
"""

import json
import os
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


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def api_error_payload(exc: Exception) -> dict:
    if isinstance(exc, anthropic.AuthenticationError):
        return {"type": "error", "error": "Your stored API key is no longer valid — reconnect it in Settings."}
    if isinstance(exc, anthropic.PermissionDeniedError):
        return {"type": "error", "error": "Your API key doesn't have permission for that model."}
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
    payload = {
        "logged_in": True,
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "has_key": bool(api_key),
        "models": [],
    }
    if api_key:
        try:
            payload["models"] = list_models(anthropic.Anthropic(api_key=api_key))
        except anthropic.AuthenticationError:
            # Key was revoked since it was stored — force re-entry.
            storage.set_api_key(sub, None)
            payload["has_key"] = False
        except (anthropic.APIStatusError, anthropic.APIConnectionError):
            payload["models"] = [{"id": DEFAULT_MODEL, "name": "Claude Opus 5"}]
    return jsonify(payload)


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
    key = storage.get_api_key(session["sub"])
    if not key:
        return jsonify({"error": "No API key connected. Add one in Settings."}), 400

    data = request.get_json(silent=True) or {}
    model = (data.get("model") or DEFAULT_MODEL).strip()
    system = (data.get("system") or "").strip()
    effort = (data.get("effort") or "").strip()
    messages = data.get("messages") or []
    if not messages:
        return jsonify({"error": "No messages provided."}), 400

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

            if final.stop_reason == "refusal":
                detail = ""
                if final.stop_details and getattr(final.stop_details, "explanation", None):
                    detail = f" ({final.stop_details.explanation})"
                yield sse({
                    "type": "refusal",
                    "error": "The model declined this request for safety reasons." + detail,
                })
                return

            yield sse({
                "type": "done",
                "model": final.model,
                "stop_reason": final.stop_reason,
                "usage": {
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                },
            })
        except Exception as exc:  # surfaced to the client as an SSE error event
            yield sse(api_error_payload(exc))

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port, threaded=True)

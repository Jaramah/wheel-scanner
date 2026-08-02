"""AI Harness — bring-your-own-key chat application.

Users authenticate with their own Anthropic API key (from their Claude API
subscription). The key is held client-side in the browser and passed with each
request; this server is a stateless streaming proxy and never stores keys or
conversation history.

Run:  python ai_harness/app.py   (serves on PORT, default 8001)
"""

import json
import os

import anthropic
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

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
        return {"type": "error", "error": "Invalid API key. Check it and try again."}
    if isinstance(exc, anthropic.PermissionDeniedError):
        return {"type": "error", "error": "This API key doesn't have permission for that model."}
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


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/validate")
def validate():
    """Check the user's API key and return the models it can access."""
    data = request.get_json(silent=True) or {}
    key = (data.get("api_key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "No API key provided."}), 400

    client = anthropic.Anthropic(api_key=key)
    try:
        models = [{"id": m.id, "name": m.display_name} for m in client.models.list()]
    except anthropic.AuthenticationError:
        return jsonify({"ok": False, "error": "Invalid API key."}), 401
    except anthropic.APIStatusError as e:
        return jsonify({"ok": False, "error": f"API error ({e.status_code}): {e.message}"}), 502
    except anthropic.APIConnectionError:
        return jsonify({"ok": False, "error": "Could not reach the Anthropic API."}), 502

    # Put the default model first if the account has it.
    models.sort(key=lambda m: (not m["id"].startswith(DEFAULT_MODEL), m["id"]))
    return jsonify({"ok": True, "models": models})


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
def chat():
    data = request.get_json(silent=True) or {}
    key = (data.get("api_key") or "").strip()
    model = (data.get("model") or DEFAULT_MODEL).strip()
    system = (data.get("system") or "").strip()
    effort = (data.get("effort") or "").strip()
    messages = data.get("messages") or []

    if not key:
        return jsonify({"error": "No API key provided."}), 400
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

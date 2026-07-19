"""Provider adapters.

Each agent record carries a provider id, a model, an (encrypted) credential
and an optional base_url. `chat()` normalizes a list of messages
[{"role": "system"|"user"|"assistant", "content": str}, ...] into a single
text reply for whatever provider the agent uses.

Providers that expose a real programmatic API are called over HTTPS.
Subscription-only agents (or agents left without a credential) transparently
fall back to a deterministic local "mock" so the whole collaboration workflow
is runnable end-to-end without spend.
"""

import json
import os

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

from crypto import decrypt

# Public catalog surfaced to the UI. `api` marks whether the provider can be
# called programmatically today; subscription-only ones fall back to mock.
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic (Claude API)",
        "api": True,
        "default_model": "claude-sonnet-5",
        "cred_kind": "api_key",
        "help": "Anthropic API key (sk-ant-…).",
    },
    "openai": {
        "label": "OpenAI (API)",
        "api": True,
        "default_model": "gpt-4o",
        "cred_kind": "api_key",
        "help": "OpenAI API key (sk-…).",
    },
    "gemini": {
        "label": "Google Gemini (API)",
        "api": True,
        "default_model": "gemini-1.5-pro",
        "cred_kind": "api_key",
        "help": "Google AI Studio API key.",
    },
    "openai_compatible": {
        "label": "OpenAI-compatible / Local (Ollama, LM Studio, vLLM…)",
        "api": True,
        "default_model": "llama3.1",
        "cred_kind": "api_key",
        "help": "Any /v1/chat/completions endpoint. Set Base URL; key optional.",
    },
    "claude_max": {
        "label": "Claude Max/Pro subscription (no public API — demo)",
        "api": False,
        "default_model": "claude (subscription)",
        "cred_kind": "subscription",
        "help": "Subscription plans have no public server API; runs as a mock agent.",
    },
    "chatgpt_plus": {
        "label": "ChatGPT Plus subscription (no public API — demo)",
        "api": False,
        "default_model": "gpt (subscription)",
        "cred_kind": "subscription",
        "help": "Subscription plans have no public server API; runs as a mock agent.",
    },
    "mock": {
        "label": "Mock agent (offline demo)",
        "api": False,
        "default_model": "mock-1",
        "cred_kind": "none",
        "help": "Deterministic local agent. No credential or network needed.",
    },
}

TIMEOUT = float(os.environ.get("AGENT_PLATFORM_HTTP_TIMEOUT", "90"))


class ProviderError(Exception):
    pass


def _split_messages(messages):
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    convo = [m for m in messages if m["role"] != "system"]
    return "\n\n".join(system_parts).strip(), convo


def _cred(agent) -> str:
    return decrypt(agent.get("credential") or "")


# ---- real providers --------------------------------------------------------

def _call_anthropic(agent, messages):
    key = _cred(agent)
    if not key or requests is None:
        return _call_mock(agent, messages, reason="no anthropic key")
    system, convo = _split_messages(messages)
    body = {
        "model": agent.get("model") or PROVIDERS["anthropic"]["default_model"],
        "max_tokens": 2048,
        "messages": [{"role": m["role"], "content": m["content"]} for m in convo],
    }
    if system:
        body["system"] = system
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        data=json.dumps(body),
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise ProviderError(f"Anthropic {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()


def _call_openai_style(agent, messages, base_url, default_model):
    key = _cred(agent)
    if requests is None:
        return _call_mock(agent, messages, reason="requests unavailable")
    if not key and "api.openai.com" in base_url:
        return _call_mock(agent, messages, reason="no openai key")
    headers = {"content-type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "model": agent.get("model") or default_model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "temperature": 0.4,
    }
    resp = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers=headers,
        data=json.dumps(body),
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise ProviderError(f"{base_url} {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_gemini(agent, messages):
    key = _cred(agent)
    if not key or requests is None:
        return _call_mock(agent, messages, reason="no gemini key")
    system, convo = _split_messages(messages)
    model = agent.get("model") or PROVIDERS["gemini"]["default_model"]
    contents = []
    for m in convo:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    body = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    resp = requests.post(
        url,
        headers={"content-type": "application/json"},
        data=json.dumps(body),
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise ProviderError(f"Gemini {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    cands = data.get("candidates", [])
    if not cands:
        raise ProviderError("Gemini returned no candidates")
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()


# ---- mock ------------------------------------------------------------------

def _call_mock(agent, messages, reason=None):
    """Deterministic offline agent.

    It plays the role implied by the prompt (build vs review) so the
    orchestration is demonstrable without any real model.
    """
    name = agent.get("name", "Agent")
    last_user = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user = m["content"]
            break
    lowered = last_user.lower()

    if "synthesize and merge" in lowered or "synthesize" in lowered:
        return (
            f"[{name} · mock] Synthesis: merged the strongest elements of each "
            "candidate — the clearest structure, the most complete input validation, "
            "and the best-documented interface — into one consolidated solution:\n\n"
            "```\n"
            "def solve(data):\n"
            "    \"\"\"Consolidated solution agreed by the agent team.\"\"\"\n"
            "    if not data:\n"
            "        raise ValueError('input required')\n"
            "    # validated + documented core logic\n"
            "    return result\n"
            "```"
        )

    if "review" in lowered or "critique" in lowered or "double-check" in lowered:
        # Reviewer behaviour: approve on later rounds, request changes early.
        if "revision" in lowered or "round 2" in lowered or "round 3" in lowered:
            return (
                "VERDICT: APPROVE\n"
                f"[{name} · mock] The revised solution addresses the earlier "
                "concerns. Inputs are validated, edge cases are handled, and the "
                "structure is clear. No blocking issues remain."
            )
        return (
            "VERDICT: REQUEST_CHANGES\n"
            f"[{name} · mock] Review notes:\n"
            "1. Add validation for empty / malformed input.\n"
            "2. Clarify the error-handling path.\n"
            "3. Add a short docstring and one usage example.\n"
            "Otherwise the approach is sound."
        )

    # Builder behaviour.
    note = f" (fallback: {reason})" if reason else ""
    return (
        f"[{name} · mock{note}] Draft solution:\n\n"
        "```\n"
        "def solve(data):\n"
        "    \"\"\"Handle the task described in the prompt.\"\"\"\n"
        "    if not data:\n"
        "        raise ValueError('input required')\n"
        "    # ... core logic ...\n"
        "    return result\n"
        "```\n\n"
        "This is a first draft ready for peer review."
    )


# ---- dispatch --------------------------------------------------------------

def chat(agent, messages):
    provider = agent.get("provider", "mock")
    try:
        if provider == "anthropic":
            return _call_anthropic(agent, messages)
        if provider == "openai":
            return _call_openai_style(
                agent, messages, "https://api.openai.com/v1", PROVIDERS["openai"]["default_model"]
            )
        if provider == "openai_compatible":
            base = agent.get("base_url") or "http://localhost:11434/v1"
            return _call_openai_style(
                agent, messages, base, PROVIDERS["openai_compatible"]["default_model"]
            )
        if provider == "gemini":
            return _call_gemini(agent, messages)
        # subscription-only + mock providers
        return _call_mock(agent, messages)
    except ProviderError:
        raise
    except Exception as exc:  # network, JSON, etc.
        raise ProviderError(f"{provider} call failed: {exc}") from exc

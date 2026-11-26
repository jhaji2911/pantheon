"""A relay to any OpenAI-compatible chat endpoint (Ollama by default).

Same call shape as the Colony relay: `Relay().chat(model, messages, ...)` returns
`{ok, content, model, ms, usage, error}` and never raises.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import settings

STANDALONE = True
_resolved = {"model": None}
_NOT_CHAT = ("embed", "ocr", "whisper", "rerank", "clip")


def _request(path, body=None, timeout=10):
    headers = {"content-type": "application/json"}
    if settings.API_KEY:
        headers["authorization"] = "Bearer " + settings.API_KEY
    req = urllib.request.Request(settings.BASE_URL + path, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def default_model() -> str:
    """PANTHEON_MODEL, or the first model the endpoint lists (cached once found)."""
    if settings.MODEL:
        return settings.MODEL
    if not _resolved["model"]:
        listed = [m["id"] for m in (_request("/models").get("data") or [])
                  if not any(word in m["id"].lower() for word in _NOT_CHAT)]
        if not listed:
            raise RuntimeError("no chat model at %s; pull one (e.g. `ollama pull qwen3:4b-instruct`) "
                               "or set PANTHEON_MODEL" % settings.BASE_URL)
        _resolved["model"] = listed[0]
    return _resolved["model"]


class Relay:
    def chat(self, model, messages, session_id=None, max_tokens=700, temperature=0.5,
             tier=None, timeout=120, **_):
        # Colony model names mean nothing to your endpoint; use the tier's configured model.
        started = time.time()
        try:
            model = (settings.TIERS.get(tier or "", {}).get("model") or default_model())
            out = _request("/chat/completions", {
                "model": model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "stream": False}, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:240]
            return {"ok": False, "error": "model endpoint %s: %s" % (exc.code, detail),
                    "model": model, "ms": int((time.time() - started) * 1000)}
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
            return {"ok": False, "error": "model endpoint unreachable at %s: %s"
                    % (settings.BASE_URL, exc), "model": model if isinstance(model, str) else None,
                    "ms": int((time.time() - started) * 1000)}
        choice = (out.get("choices") or [{}])[0]
        usage = out.get("usage") or {}
        usage.setdefault("total_tokens", (usage.get("prompt_tokens") or 0)
                         + (usage.get("completion_tokens") or 0))
        return {"ok": True, "content": (choice.get("message") or {}).get("content") or "",
                "model": out.get("model") or model, "usage": usage,
                "ms": int((time.time() - started) * 1000)}

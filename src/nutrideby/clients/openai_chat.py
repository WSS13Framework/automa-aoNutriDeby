"""Cliente mínimo OpenAI-compatible para ``/v1/chat/completions`` (stdlib apenas)."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

from nutrideby.clients.genai_agent import assistant_content_from_completion


def _post_json(url: str, body: dict[str, Any], api_key: str, timeout: int) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, raw


def chat_completion(
    *,
    api_base: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
    timeout: int = 120,
) -> tuple[int, str]:
    """Devolve ``(http_status, corpo_json)``. Erro de rede ou não-2xx → ``RuntimeError``."""
    api_key = api_key.strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY vazio")
    base = api_base.rstrip("/")
    url = f"{base}/v1/chat/completions" if not base.endswith("/v1") else f"{base}/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    try:
        status, text = _post_json(url, body, api_key, timeout)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"chat HTTP {e.code}: {raw[:500]}") from e
    except OSError as e:
        raise RuntimeError(f"chat rede: {e}") from e
    if not (200 <= status < 300):
        raise RuntimeError(f"chat HTTP {status}: {text[:500]}")
    return status, text


def assistant_content_from_chat(raw_json: str) -> str:
    return assistant_content_from_completion(raw_json)

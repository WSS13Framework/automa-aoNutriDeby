from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_COMPLETION_PATHS = (
    "/v1/chat/completions?agent=true",
    "/api/v1/chat/completions?agent=true",
)


def _post_json(url: str, body: dict[str, Any], access_key: str, timeout: int) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {access_key}")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, raw


def check_agent_inference(
    agent_base_url: str,
    access_key: str,
    *,
    timeout: int = 60,
) -> bool:
    """
    Envia um pedido mínimo estilo OpenAI ao agente DigitalOcean GenAI (RAG).
    Tenta /v1 e /api/v1; em 404 tenta o path seguinte; outros erros HTTP param de imediato.
    """
    base = agent_base_url.rstrip("/")
    body: dict[str, Any] = {
        "model": "ignored",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 32,
    }
    last_err: str | None = None
    for path in _COMPLETION_PATHS:
        url = f"{base}{path}"
        try:
            status, text = _post_json(url, body, access_key, timeout)
            logger.info("GenAI agent respondeu HTTP %s (path %s)", status, path)
            if 200 <= status < 300:
                logger.debug("Corpo (truncado): %s", text[:500])
                return True
            last_err = f"HTTP {status}: {text[:300]}"
            if status != 404:
                logger.error("Agente GenAI: %s", last_err)
                return False
        except OSError:
            logger.exception("Falha de rede ao contactar %s", url)
            last_err = "network error"
            return False
        except Exception:
            logger.exception("Falha ao contactar %s", url)
            last_err = "unexpected error"
            return False
    logger.error("Agente GenAI inacessível (404 em ambos os paths): %s", last_err)
    return False

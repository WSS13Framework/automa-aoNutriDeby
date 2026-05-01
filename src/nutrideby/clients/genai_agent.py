from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# A DO costuma expor /api/v1/...; /v1/... devolve 404 em muitos agentes.
_COMPLETION_PATHS = (
    "/api/v1/chat/completions?agent=true",
    "/v1/chat/completions?agent=true",
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
    Tenta /api/v1 e /v1; em 404 tenta o path seguinte; outros erros HTTP param de imediato.
    """
    access_key = access_key.strip()
    if not access_key:
        logger.error("GENAI_AGENT_ACCESS_KEY está vazio")
        return False
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
                if status in (401, 403):
                    logger.error(
                        "Agente GenAI: %s — verifica GENAI_AGENT_ACCESS_KEY no .env: "
                        "tem de ser a chave de *endpoint do agente* no painel DO (GenAI Agent), "
                        "não o Personal Access Token da conta nem o token do OpenClaw.",
                        last_err,
                    )
                else:
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

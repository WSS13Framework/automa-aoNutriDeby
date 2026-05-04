from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# O endpoint do agente com ``?agent=true`` devolve 400 se ``messages`` incluir
# ``role: system`` ou ``role: developer`` ("set via agent configuration").
# Colapsamos tudo num único ``user`` para compatibilidade com pedidos antigos ou outros callers.
def _collapse_to_single_user_message(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return [{"role": "user", "content": ""}]
    if len(messages) == 1 and str(messages[0].get("role", "user")).strip().lower() == "user":
        return messages
    chunks: list[str] = []
    saw_restricted = False
    for m in messages:
        role = str(m.get("role", "user")).strip().lower()
        c = m.get("content")
        text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        if role in ("system", "developer"):
            saw_restricted = True
            chunks.append(f"## Instruções ({role})\n\n{text}")
        elif role == "user":
            chunks.append(f"## Pedido\n\n{text}")
        elif role == "assistant":
            chunks.append(f"## Assistente (histórico)\n\n{text}")
        else:
            chunks.append(f"## {role}\n\n{text}")
    combined = "\n\n---\n\n".join(chunks)
    if saw_restricted:
        logger.info(
            "genai_agent: colapsadas mensagens system/developer num único role=user (requisito DO GenAI Agent)"
        )
    return [{"role": "user", "content": combined}]


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


def chat_completion(
    agent_base_url: str,
    access_key: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 512,
    timeout: int = 120,
    telemetry_context: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    """
    POST estilo OpenAI ao agente DO GenAI. Devolve ``(http_status, corpo_json, path_usado)``.

    Mensagens ``system`` / ``developer`` são fundidas num único ``user`` (requisito do
    endpoint com ``agent=true``). Um único ``user`` passa inalterado.

    ``telemetry_context``: metadados opcionais para indexação OpenSearch (telemetria);
    ver ``nutrideby.clients.opensearch_telemetry``.
    Erro de rede ou resposta não-2xx após esgotar paths → ``RuntimeError``.
    """
    access_key = access_key.strip()
    if not access_key:
        raise RuntimeError("GENAI_AGENT_ACCESS_KEY vazio")
    base = agent_base_url.rstrip("/")
    safe_messages = _collapse_to_single_user_message(messages)
    body: dict[str, Any] = {
        "model": "ignored",
        "messages": safe_messages,
        "max_tokens": max_tokens,
    }
    last_err: str | None = None
    for path in _COMPLETION_PATHS:
        url = f"{base}{path}"
        try:
            status, text = _post_json(url, body, access_key, timeout)
            if 200 <= status < 300:
                if telemetry_context is not None:
                    try:
                        from nutrideby.clients.opensearch_telemetry import log_rag_genai_interaction

                        log_rag_genai_interaction(
                            telemetry=telemetry_context,
                            http_status=status,
                            raw_completion_json=text,
                            assistant_text=assistant_content_from_completion(text),
                            agent_path=path,
                        )
                    except Exception:
                        logger.exception("OpenSearch telemetria: falha não bloqueante")
                return status, text, path
            last_err = f"HTTP {status}: {text[:400]}"
            if status != 404:
                raise RuntimeError(last_err)
        except OSError as e:
            raise RuntimeError(f"rede: {e}") from e
    raise RuntimeError(f"Agente inacessível (404 em ambos os paths): {last_err}")


def assistant_content_from_completion(raw_json: str) -> str:
    """Extrai ``choices[0].message.content`` do JSON do agente; fallback truncado."""
    try:
        o = json.loads(raw_json)
    except json.JSONDecodeError:
        return raw_json[:4000]
    choices = o.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict):
            c = msg.get("content")
            if isinstance(c, str):
                return c
    return raw_json[:4000]

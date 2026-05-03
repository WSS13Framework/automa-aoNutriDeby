"""Cliente mínimo OpenAI-compatible para ``/v1/embeddings`` (stdlib apenas)."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

EXPECTED_DIM = 1536


def format_vector_for_pg(vec: list[float]) -> str:
    """Literal aceite por Postgres ``::vector`` (dimensão fixa na migração 004)."""
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


def _post_json(url: str, body: dict[str, Any], api_key: str, timeout: int) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, raw


def embed_texts(
    *,
    api_base: str,
    api_key: str,
    model: str,
    inputs: list[str],
    timeout: int = 120,
) -> list[list[float]]:
    """
    Uma chamada à API de embeddings. ``inputs`` na mesma ordem que o retorno.
    Textos vazios são substituídos por um espaço (a API rejeita string vazia).
    """
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("API key de embeddings vazia")
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/embeddings"
    else:
        url = f"{base}/v1/embeddings"
    clean = [(t if t.strip() else " ") for t in inputs]
    body: dict[str, Any] = {"model": model, "input": clean}
    try:
        status, text = _post_json(url, body, api_key, timeout)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"embeddings HTTP {e.code}: {raw[:500]}") from e
    except OSError as e:
        raise RuntimeError(f"embeddings rede: {e}") from e
    if not (200 <= status < 300):
        raise RuntimeError(f"embeddings HTTP {status}: {text[:500]}")
    payload = json.loads(text)
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("resposta embeddings sem 'data' lista")
    by_index: dict[int, list[float]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        emb = item.get("embedding")
        if isinstance(idx, int) and isinstance(emb, list):
            floats = [float(x) for x in emb]
            by_index[idx] = floats
    out: list[list[float]] = []
    for i in range(len(clean)):
        vec = by_index.get(i)
        if vec is None:
            raise RuntimeError(f"embedding em falta para index={i}")
        if len(vec) != EXPECTED_DIM:
            raise RuntimeError(
                f"dimensão {len(vec)} != {EXPECTED_DIM} (ajusta modelo ou migração 004)"
            )
        out.append(vec)
    return out


def embed_single_query(
    *,
    api_base: str,
    api_key: str,
    model: str,
    text: str,
    timeout: int = 60,
) -> list[float]:
    vecs = embed_texts(api_base=api_base, api_key=api_key, model=model, inputs=[text], timeout=timeout)
    return vecs[0]

"""
Telemetria OpenSearch para consultas GenAI + RAG (cluster genai-estrela-do-mar / TOR1).

Usa ``opensearch-py`` de forma opcional. Sem ``OPENSEARCH_HOSTS`` (ou URL) não faz nada.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

CLUSTER_LABEL = "genai-estrela-do-mar"
REGION_LABEL = "TOR1"


def _build_client():
    try:
        from opensearchpy import OpenSearch
    except ImportError:
        logger.warning("opensearch-py não instalado — telemetria OpenSearch desactivada")
        return None, None

    raw_hosts = os.environ.get("OPENSEARCH_HOSTS", "").strip()
    raw_url = os.environ.get("OPENSEARCH_URL", "").strip()
    if not raw_hosts and not raw_url:
        return None, None

    user = os.environ.get("OPENSEARCH_USER", "").strip() or None
    password = os.environ.get("OPENSEARCH_PASSWORD", "").strip() or None
    verify = os.environ.get("OPENSEARCH_VERIFY_SSL", "true").lower() in ("1", "true", "yes")
    index = os.environ.get("OPENSEARCH_INDEX", "nutrideby-genai-telemetry").strip()

    if raw_url:
        u = urlparse(raw_url)
        if not u.hostname:
            return None, None
        port = u.port or (443 if u.scheme == "https" else 9200)
        use_ssl = u.scheme == "https"
        hosts = [{"host": u.hostname, "port": port}]
    else:
        use_ssl = os.environ.get("OPENSEARCH_USE_SSL", "true").lower() in ("1", "true", "yes")
        hosts = []
        for h in raw_hosts.split(","):
            part = h.strip()
            if not part:
                continue
            if "://" in part:
                u = urlparse(part)
                if u.hostname:
                    hosts.append({"host": u.hostname, "port": u.port or (443 if u.scheme == "https" else 9200)})
            else:
                hp = part.rsplit(":", 1)
                if len(hp) == 2 and hp[1].isdigit():
                    hosts.append({"host": hp[0], "port": int(hp[1])})
                else:
                    hosts.append({"host": part, "port": 443 if use_ssl else 9200})

    if not hosts:
        return None, None

    auth = (user, password) if user and password else None
    client = OpenSearch(
        hosts=hosts,
        http_auth=auth,
        use_ssl=use_ssl,
        verify_certs=verify,
        timeout=15,
    )
    return client, index


def log_rag_genai_interaction(
    *,
    telemetry: dict[str, Any],
    http_status: int,
    raw_completion_json: str,
    assistant_text: str,
    agent_path: str,
) -> None:
    """
    Indexa um documento com input/resumo RAG, output e metadados.

    ``telemetry`` deve incluir pelo menos: patient_id, query, persona, embedding_model,
    rag_hit_scores (lista de dicts com score/distance/chunk_id).
    """
    built = _build_client()
    if built[0] is None:
        return
    client, index = built
    doc_id = str(uuid.uuid4())
    doc: dict[str, Any] = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "opensearch_cluster": CLUSTER_LABEL,
        "do_region": REGION_LABEL,
        "genai_http_status": http_status,
        "genai_agent_path": agent_path,
        "patient_id": telemetry.get("patient_id"),
        "query": telemetry.get("query"),
        "persona": telemetry.get("persona"),
        "embedding_model": telemetry.get("embedding_model"),
        "rag_hit_scores": telemetry.get("rag_hit_scores") or [],
        "assistant_output": (assistant_text or "")[:12000],
        "raw_completion_truncated": (raw_completion_json or "")[:8000],
    }
    try:
        try:
            client.index(index=index, id=doc_id, body=doc, refresh=False)
        except TypeError:
            client.index(index=index, id=doc_id, document=doc, refresh=False)
        logger.info("OpenSearch: documento telemetria id=%s index=%s", doc_id, index)
    except Exception:
        logger.exception("OpenSearch: falha ao indexar telemetria (não bloqueia o fluxo)")

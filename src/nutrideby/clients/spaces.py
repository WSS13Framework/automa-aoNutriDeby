"""
DigitalOcean Spaces (S3-compatible): upload de JSON de análise (data lake).

Bucket por defeito alinhado a ``nutridebv2.lon1.digitaloceanspaces.com`` (região lon1).
Credenciais: ``SPACES_ACCESS_KEY_ID``, ``SPACES_SECRET_ACCESS_KEY`` no ``.env``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def upload_json_analysis_if_configured(
    *,
    access_key_id: str | None,
    secret_access_key: str | None,
    bucket: str,
    region: str,
    endpoint_url: str,
    payload: dict[str, Any],
    key_prefix: str = "rag-analysis",
) -> str | None:
    """
    Faz ``put_object`` do JSON. Devolve URL pública virtual-host se credenciais existirem;
    ``None`` se Spaces não estiver configurado.
    """
    if not (
        access_key_id
        and str(access_key_id).strip()
        and secret_access_key
        and str(secret_access_key).strip()
    ):
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        logger.warning("boto3 não instalado — upload Spaces ignorado")
        return None

    key = f"{key_prefix}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{uuid.uuid4()}.json"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    client = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url.rstrip("/"),
        aws_access_key_id=str(access_key_id).strip(),
        aws_secret_access_key=str(secret_access_key).strip(),
        config=Config(signature_version="s3v4"),
    )
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json; charset=utf-8",
    )
    # Virtual-hosted–style URL (DigitalOcean Spaces)
    url = f"https://{bucket}.{region}.digitaloceanspaces.com/{key}"
    logger.info("Spaces: objecto gravado key=%s", key)
    return url

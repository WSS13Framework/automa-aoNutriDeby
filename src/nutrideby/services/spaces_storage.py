"""
Upload de fotos para DigitalOcean Spaces.
Extraído de bodyscan_router._upload_photo_to_spaces e composicao_router._upload_photo.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def upload_photo_to_spaces(
    settings,
    data: bytes,
    content_type: str,
    folder: str,
    index: int,
) -> str | None:
    """
    Faz upload de uma foto para DO Spaces.

    Args:
        folder: caminho relativo, ex.: "bodyscans/{scan_id}" ou "composicao/{prefix}"
        index:  índice da foto (0, 1, 2 …)

    Returns:
        URL pública ou None se Spaces não estiver configurado.
    """
    if not (settings.spaces_access_key_id and settings.spaces_secret_access_key):
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        logger.warning("boto3 não instalado — upload Spaces ignorado")
        return None

    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    key = f"{folder}/{index}.{ext}"
    client = boto3.client(
        "s3",
        region_name=settings.spaces_region,
        endpoint_url=settings.spaces_endpoint.rstrip("/"),
        aws_access_key_id=str(settings.spaces_access_key_id).strip(),
        aws_secret_access_key=str(settings.spaces_secret_access_key).strip(),
        config=Config(signature_version="s3v4"),
    )
    client.put_object(
        Bucket=settings.spaces_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        ACL="public-read",
    )
    return (
        f"https://{settings.spaces_bucket}"
        f".{settings.spaces_region}"
        f".digitaloceanspaces.com/{key}"
    )

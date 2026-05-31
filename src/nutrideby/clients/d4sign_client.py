"""
d4sign_client.py — Cliente para a API D4Sign (assinatura digital brasileira).
Documentação: https://docapi.d4sign.com.br/
"""
from __future__ import annotations

import io
import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_BASE = "https://secure.d4sign.com.br/api/v1"


def _auth_params(token_api: str, crypt_key: str) -> str:
    return f"tokenAPI={urllib.parse.quote(token_api)}&cryptKey={urllib.parse.quote(crypt_key)}"


def _get(url: str, timeout: int = 30) -> dict:
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") if e.fp else ""
        raise RuntimeError(f"D4Sign GET {e.code}: {raw[:400]}") from e


def _post_json(url: str, body: dict, timeout: int = 30) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") if e.fp else ""
        raise RuntimeError(f"D4Sign POST {e.code}: {raw[:400]}") from e


def _post_multipart(url: str, filename: str, pdf_bytes: bytes, timeout: int = 60) -> dict:
    """Envia PDF via multipart/form-data."""
    boundary = "----D4SignBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode() + pdf_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") if e.fp else ""
        raise RuntimeError(f"D4Sign upload {e.code}: {raw[:400]}") from e


def upload_document(
    token_api: str,
    crypt_key: str,
    safe_uuid: str,
    pdf_bytes: bytes,
    filename: str,
) -> str:
    """Faz upload do PDF no cofre D4Sign. Retorna o uuid do documento criado."""
    url = f"{_BASE}/documents/{safe_uuid}/upload?{_auth_params(token_api, crypt_key)}"
    resp = _post_multipart(url, filename, pdf_bytes)
    doc_uuid = resp.get("uuid") or (resp.get("documents", [{}])[0].get("uuidDoc") if resp.get("documents") else None)
    if not doc_uuid:
        raise RuntimeError(f"D4Sign upload sem uuid: {resp}")
    logger.info("D4Sign upload ok: uuid=%s", doc_uuid)
    return doc_uuid


def add_signer(
    token_api: str,
    crypt_key: str,
    document_uuid: str,
    email: str,
    name: str,
    action: str = "sign",
) -> str:
    """Adiciona signatário ao documento. Retorna uuid do signatário."""
    url = f"{_BASE}/documents/{document_uuid}/createlist?{_auth_params(token_api, crypt_key)}"
    body = {
        "signers": [
            {
                "email": email,
                "act": "1",          # 1 = assinar
                "foreign": "0",
                "certificadoicpbr": "0",
                "assinatura_presencial": "0",
                "embed_methodauth": "email",
                "embed_smsnumber": "",
            }
        ]
    }
    resp = _post_json(url, body)
    signers = resp.get("message", [])
    if signers and isinstance(signers, list):
        return signers[0].get("key_signer", "")
    logger.warning("D4Sign createlist resp: %s", resp)
    return ""


def send_to_sign(
    token_api: str,
    crypt_key: str,
    document_uuid: str,
    message: str,
    callback_url: str,
) -> dict:
    """Dispara o fluxo de assinatura. D4Sign envia e-mail ao signatário."""
    url = f"{_BASE}/documents/{document_uuid}/sendtosign?{_auth_params(token_api, crypt_key)}"
    body = {
        "message": message,
        "workflow": "0",
        "skip_email": "0",
        "callback_url": callback_url,
    }
    return _post_json(url, body)


def get_document_info(token_api: str, crypt_key: str, document_uuid: str) -> dict:
    """Retorna status e dados do documento no D4Sign."""
    url = f"{_BASE}/documents/{document_uuid}?{_auth_params(token_api, crypt_key)}"
    return _get(url)


def download_signed_pdf(token_api: str, crypt_key: str, document_uuid: str) -> bytes:
    """Baixa o PDF final assinado do D4Sign."""
    url = f"{_BASE}/documents/{document_uuid}/download?{_auth_params(token_api, crypt_key)}&type=zip"
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, timeout=60, context=ctx) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") if e.fp else ""
        raise RuntimeError(f"D4Sign download {e.code}: {raw[:400]}") from e

"""
bodyscan_router.py — Análise corporal por Claude Vision a partir de fotos.

Rotas:
  POST /patients/{patient_id}/bodyscan        → envia até 5 fotos, obtém % gordura e % músculo
  GET  /patients/{patient_id}/bodyscan        → histórico de scans
  GET  /patients/{patient_id}/bodyscan/{sid}  → detalhe de um scan
"""
from __future__ import annotations

import base64
import json
import logging
import os
import ssl
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from psycopg.rows import dict_row

from nutrideby.api.deps import get_settings
from nutrideby.api.mobile_api import check_active_access
from nutrideby.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patients", tags=["bodyscan"])

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

VISION_PROMPT = (
    "Você é um especialista em avaliação física e composição corporal para nutrição clínica.\n"
    "Analise as fotos enviadas do paciente e estime os parâmetros abaixo com base em características "
    "visuais (silhueta, distribuição de gordura, definição muscular, postura).\n\n"
    "Retorne SOMENTE um JSON válido, sem texto extra, sem markdown, no formato:\n"
    '{\n'
    '  "body_fat_pct": <número 0-100, uma casa decimal>,\n'
    '  "muscle_mass_pct": <número 0-100, uma casa decimal>,\n'
    '  "lean_mass_kg": <número ou null>,\n'
    '  "analysis_notes": "<parágrafo em português com observações clínicas sobre composição corporal, '
    'postura e recomendações nutricionais. Seja encorajador e profissional.>"\n'
    "}\n\n"
    "Diretrizes:\n"
    "- body_fat_pct: percentual de gordura corporal total estimado visualmente\n"
    "- muscle_mass_pct: percentual de massa muscular esquelética estimado\n"
    "- lean_mass_kg: massa magra em kg (use null se não tiver referência de peso)\n"
    "- analysis_notes: 3-4 frases em português úteis para planejamento nutricional\n"
    "- Nunca faça diagnósticos médicos\n"
    "- Seja conservador e realista nas estimativas\n"
    "- Sempre responda em português"
)


def _upload_photo_to_spaces(
    settings: Settings,
    data: bytes,
    content_type: str,
    scan_id: str,
    index: int,
) -> str | None:
    if not (settings.spaces_access_key_id and settings.spaces_secret_access_key):
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        logger.warning("boto3 não instalado — upload Spaces ignorado")
        return None

    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    key = f"bodyscans/{scan_id}/{index}.{ext}"
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
    return f"https://{settings.spaces_bucket}.{settings.spaces_region}.digitaloceanspaces.com/{key}"


def _call_claude_vision(image_sources: list[dict]) -> dict[str, Any]:
    """Chama Claude Vision API diretamente via urllib."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada")

    content: list[dict] = []
    for src in image_sources:
        if src["type"] == "url":
            with urllib.request.urlopen(src["data"], timeout=30) as r:
                img_data = r.read()
            b64 = base64.b64encode(img_data).decode("ascii")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })
        else:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": src["mime"], "data": src["data"]},
            })

    content.append({"type": "text", "text": VISION_PROMPT})

    body = json.dumps({
        "model": model,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")

    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"Claude API HTTP {e.code}: {raw[:400]}")

    resp_json = json.loads(raw)
    text = resp_json["content"][0]["text"].strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].rstrip()
    return json.loads(text)


@router.post(
    "/{patient_id}/bodyscan",
    status_code=status.HTTP_201_CREATED,
    summary="Envia até 5 fotos para análise de composição corporal por Claude Vision",
)
async def create_bodyscan(
    patient_id: str,
    photos: Annotated[list[UploadFile], File(description="1 a 5 fotos corporais")],
    settings: Annotated[Settings, Depends(get_settings)],
    _access: dict = Depends(check_active_access),
):
    if not photos:
        raise HTTPException(status_code=422, detail="Envie ao menos 1 foto")
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(status_code=422, detail=f"Máximo de {MAX_PHOTOS} fotos por scan")

    for photo in photos:
        if photo.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Tipo não suportado: {photo.content_type}. Use JPEG, PNG ou WEBP.",
            )

    scan_id = str(uuid.uuid4())
    photo_urls: list[str] = []
    image_sources: list[dict] = []

    for i, photo in enumerate(photos):
        data = await photo.read()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail=f"Foto {i+1} excede 10 MB")

        url = _upload_photo_to_spaces(settings, data, photo.content_type or "image/jpeg", scan_id, i)
        if url:
            photo_urls.append(url)
            image_sources.append({"type": "url", "data": url})
        else:
            b64 = base64.b64encode(data).decode("ascii")
            image_sources.append({"type": "base64", "mime": photo.content_type or "image/jpeg", "data": b64})

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO body_scans (id, patient_id, photo_urls, status)
                   VALUES (%s, %s, %s, 'pending')""",
                (scan_id, patient_id, photo_urls),
            )

    try:
        result = _call_claude_vision(image_sources)
        body_fat = float(result.get("body_fat_pct") or 0)
        muscle = float(result.get("muscle_mass_pct") or 0)
        lean = result.get("lean_mass_kg")
        lean_kg = float(lean) if lean is not None else None
        notes = str(result.get("analysis_notes") or "")
        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

        with psycopg.connect(settings.database_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """UPDATE body_scans
                       SET status = 'done',
                           body_fat_pct = %s,
                           muscle_mass_pct = %s,
                           lean_mass_kg = %s,
                           analysis_notes = %s,
                           model_used = %s
                       WHERE id = %s
                       RETURNING *""",
                    (body_fat, muscle, lean_kg, notes, model_name, scan_id),
                )
                scan = cur.fetchone()

    except Exception as exc:
        logger.error("bodyscan claude vision error: %s", exc)
        with psycopg.connect(settings.database_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "UPDATE body_scans SET status='error', error_detail=%s WHERE id=%s RETURNING *",
                    (str(exc)[:500], scan_id),
                )
                scan = cur.fetchone()
        raise HTTPException(status_code=502, detail=f"Análise IA falhou: {exc}") from exc

    return _serialize(scan)


@router.get("/{patient_id}/bodyscan", summary="Histórico de bodyscans do paciente")
def list_bodyscans(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    _access: dict = Depends(check_active_access),
):
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, created_at, status, body_fat_pct, muscle_mass_pct,
                          lean_mass_kg, analysis_notes, photo_urls, model_used
                   FROM body_scans
                   WHERE patient_id = %s
                   ORDER BY created_at DESC
                   LIMIT 50""",
                (patient_id,),
            )
            rows = cur.fetchall()
    return [_serialize(r) for r in rows]


@router.get("/{patient_id}/bodyscan/{scan_id}", summary="Detalhe de um bodyscan")
def get_bodyscan(
    patient_id: str,
    scan_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    _access: dict = Depends(check_active_access),
):
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM body_scans WHERE id = %s AND patient_id = %s",
                (scan_id, patient_id),
            )
            scan = cur.fetchone()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan não encontrado")
    return _serialize(scan)


def _serialize(row: dict) -> dict:
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out

"""
bodyscan_router.py — Análise corporal por Claude Vision a partir de fotos.

Rotas:
  POST /patients/{patient_id}/bodyscan        → envia até 5 fotos, obtém % gordura e % músculo
  GET  /patients/{patient_id}/bodyscan        → histórico de scans
  GET  /patients/{patient_id}/bodyscan/{sid}  → detalhe de um scan
"""
from __future__ import annotations

import base64
import logging
import os
import uuid
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from psycopg.rows import dict_row

from nutrideby.api.deps import get_settings
from nutrideby.api.mobile_api import check_active_access
from nutrideby.config import Settings
from nutrideby.services.body_composition import serialize_row
from nutrideby.services.spaces_storage import upload_photo_to_spaces
from nutrideby.services.vision import call_claude_vision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patients", tags=["bodyscan"])

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


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

        url = upload_photo_to_spaces(
            settings, data, photo.content_type or "image/jpeg", f"bodyscans/{scan_id}", i
        )
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

    api_key    = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model_name = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()

    try:
        result   = call_claude_vision(image_sources, api_key, model_name)
        body_fat = float(result.get("body_fat_pct") or 0)
        muscle   = float(result.get("muscle_mass_pct") or 0)
        lean     = result.get("lean_mass_kg")
        lean_kg  = float(lean) if lean is not None else None
        notes    = str(result.get("analysis_notes") or "")

        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
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
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE body_scans SET status='error', error_detail=%s WHERE id=%s RETURNING *",
                    (str(exc)[:500], scan_id),
                )
                scan = cur.fetchone()
        raise HTTPException(status_code=502, detail=f"Análise IA falhou: {exc}") from exc

    return serialize_row(scan)


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
    return [serialize_row(r) for r in rows]


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
    return serialize_row(scan)

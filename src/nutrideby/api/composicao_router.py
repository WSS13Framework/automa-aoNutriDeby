"""
composicao_router.py — Motor unificado de composição corporal (ML + Visão IA).

Motor BIO  : GradientBoostingRegressor treinado sobre 20k amostras populacionais
             brasileiras (IBGE/POF 2019) com intervalos de confiança via quantile
             regression. Retreinável com dados DEXA reais via /composicao/retrain.

Motor VISÃO: GPT-4o Vision a partir de até 5 fotos (opcional).

Fusão      : sem fotos → BIO puro; com fotos → 60% visão / 40% BIO (gordura),
             50/50 (músculo). Fonte gravada no registro.

Rotas:
  POST /patients/{patient_id}/composicao          → avaliação completa
  GET  /patients/{patient_id}/composicao          → histórico
  GET  /patients/{patient_id}/composicao/{cid}    → detalhe
  POST /composicao/retrain                        → retreina com dados reais (admin)
"""
from __future__ import annotations

import base64
import logging
import uuid
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from psycopg.rows import dict_row

from nutrideby.api.deps import get_settings, require_api_key
from nutrideby.api.mobile_api import check_active_access
from nutrideby.config import Settings
from nutrideby.ml.bio_model import get_model
from nutrideby.services.body_composition import classifica_gordura, classifica_imc, serialize_row
from nutrideby.services.spaces_storage import upload_photo_to_spaces
from nutrideby.services.vision import call_gpt4o_vision

logger = logging.getLogger(__name__)

router = APIRouter(tags=["composicao"])

MAX_PHOTOS      = 5
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_MIME    = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


# ── Fusão ML + Visão ───────────────────────────────────────────────────────────

def _fundir(ml: dict, visao: dict | None) -> dict:
    if visao is None:
        return {
            "gordura_pct": ml["gordura_pct"],
            "smm_pct":     ml["massa_muscular_pct"],
            "fonte":       "ml_bioimpedancia",
        }
    gord = round(
        0.6 * float(visao.get("body_fat_pct", ml["gordura_pct"]))
        + 0.4 * ml["gordura_pct"], 2
    )
    musc = round(
        0.5 * float(visao.get("muscle_mass_pct", ml["massa_muscular_pct"]))
        + 0.5 * ml["massa_muscular_pct"], 2
    )
    return {
        "gordura_pct": max(3.0, min(gord, 70.0)),
        "smm_pct":     max(1.0, min(musc, 70.0)),
        "fonte":       "ml_fusao",
    }


# ── Persistência ───────────────────────────────────────────────────────────────

def _salvar_bio(conn, patient_id, altura_cm, peso_kg, idade, sexo, ml) -> str:
    cur = conn.cursor(row_factory=dict_row)
    cur.execute(
        """INSERT INTO bioimpedancia_logs
           (patient_id, altura_cm, peso_kg, idade, sexo,
            imc, gordura_pct, massa_muscular_kg, massa_muscular_pct,
            massa_gorda_kg, massa_magra_kg, classificacao_gordura, classificacao_imc)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (patient_id, altura_cm, peso_kg, idade, sexo,
         ml["imc"], ml["gordura_pct"],
         ml["massa_muscular_kg"], ml["massa_muscular_pct"],
         round(peso_kg * ml["gordura_pct"] / 100, 2),
         round(peso_kg * (1 - ml["gordura_pct"] / 100), 2),
         classifica_gordura(ml["gordura_pct"], sexo),
         classifica_imc(ml["imc"])),
    )
    return str(cur.fetchone()["id"])


def _salvar_bodyscan(conn, patient_id, photo_urls, visao) -> str:
    sid = str(uuid.uuid4())
    conn.cursor().execute(
        """INSERT INTO body_scans
           (id, patient_id, photo_urls, status, body_fat_pct, muscle_mass_pct, analysis_notes, model_used)
           VALUES (%s,%s,%s,'done',%s,%s,%s,'gpt-4o')""",
        (sid, patient_id, photo_urls,
         float(visao.get("body_fat_pct", 0)),
         float(visao.get("muscle_mass_pct", 0)),
         visao.get("notas", "")),
    )
    return sid


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/patients/{patient_id}/composicao",
    status_code=status.HTTP_201_CREATED,
    summary="Motor ML + Visão IA: avaliação unificada de composição corporal",
)
async def criar_composicao(
    patient_id: str,
    altura_cm: float  = Form(..., gt=50, lt=250),
    peso_kg:   float  = Form(..., gt=10, lt=300),
    idade:     int    = Form(..., ge=18, le=100),
    sexo:      str    = Form(..., pattern="^[MF]$"),
    photos: list[UploadFile] = File(default=[]),
    settings: Annotated[Settings, Depends(get_settings)] = None,
    _access: dict = Depends(check_active_access),
):
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(422, f"Máximo {MAX_PHOTOS} fotos")
    for p in photos:
        if p.content_type not in ALLOWED_MIME:
            raise HTTPException(415, f"Tipo não suportado: {p.content_type}")

    # 1. Motor ML
    try:
        ml = get_model().predict(altura_cm, peso_kg, idade, sexo)
    except Exception as e:
        raise HTTPException(500, f"Motor ML falhou: {e}")

    # 2. Motor Visão (opcional)
    visao: dict | None = None
    photo_urls: list[str] = []
    sources: list[dict] = []
    prefix = str(uuid.uuid4())

    if photos:
        for i, ph in enumerate(photos):
            data = await ph.read()
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, f"Foto {i+1} excede 10 MB")
            mime = ph.content_type or "image/jpeg"
            url = upload_photo_to_spaces(settings, data, mime, f"composicao/{prefix}", i)
            if url:
                photo_urls.append(url)
                sources.append({"type": "url", "data": url})
            else:
                sources.append({"type": "base64", "mime": mime,
                                 "data": base64.b64encode(data).decode()})
        try:
            visao = call_gpt4o_vision(
                sources,
                (settings.openai_api_key or "").strip(),
                settings.openai_api_base or "https://api.openai.com",
            )
        except Exception as e:
            logger.warning("Visão falhou, usando só ML: %s", e)

    # 3. Fusão
    fundido      = _fundir(ml, visao)
    gordura_f    = fundido["gordura_pct"]
    musc_pct_f   = fundido["smm_pct"]
    massa_gorda  = round(peso_kg * gordura_f / 100, 2)
    massa_magra  = round(peso_kg - massa_gorda, 2)
    smm_kg_f     = round(peso_kg * musc_pct_f / 100, 2)

    # 4. Persistência
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        bio_id = _salvar_bio(conn, patient_id, altura_cm, peso_kg, idade, sexo, ml)
        scan_id_fk = None
        if visao and photo_urls:
            scan_id_fk = _salvar_bodyscan(conn, patient_id, photo_urls, visao)

        row = conn.cursor(row_factory=dict_row).execute(
            """INSERT INTO composicao_corporal
               (patient_id, altura_cm, peso_kg, idade, sexo,
                foto_count, photo_urls, fonte,
                imc, gordura_pct, massa_muscular_kg, massa_muscular_pct,
                massa_gorda_kg, massa_magra_kg,
                classificacao_gordura, classificacao_imc, notas_clinicas,
                gordura_pct_bio, gordura_pct_visao,
                muscular_pct_bio, muscular_pct_visao,
                notas_visao, bioimpedancia_id, bodyscan_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (patient_id, altura_cm, peso_kg, idade, sexo,
             len(photos), photo_urls, fundido["fonte"],
             ml["imc"], gordura_f, smm_kg_f, musc_pct_f,
             massa_gorda, massa_magra,
             classifica_gordura(gordura_f, sexo),
             classifica_imc(ml["imc"]),
             visao.get("notas") if visao else None,
             ml["gordura_pct"],
             float(visao["body_fat_pct"]) if visao else None,
             ml["massa_muscular_pct"],
             float(visao.get("muscle_mass_pct", 0)) if visao else None,
             visao.get("notas") if visao else None,
             bio_id, scan_id_fk),
        ).fetchone()

    result = serialize_row(row)
    result["gordura_intervalo"] = {
        "lo": ml.get("gordura_pct_lo"),
        "hi": ml.get("gordura_pct_hi"),
    }
    return result


@router.get("/patients/{patient_id}/composicao", summary="Histórico de composição corporal")
def listar_composicao(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    _access: dict = Depends(check_active_access),
):
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        rows = conn.cursor().execute(
            "SELECT * FROM composicao_corporal WHERE patient_id=%s ORDER BY created_at DESC LIMIT 50",
            (patient_id,)
        ).fetchall()
    return [serialize_row(r) for r in rows]


@router.get("/patients/{patient_id}/composicao/{cid}", summary="Detalhe de avaliação")
def detalhe_composicao(
    patient_id: str, cid: str,
    settings: Annotated[Settings, Depends(get_settings)],
    _access: dict = Depends(check_active_access),
):
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        row = conn.cursor().execute(
            "SELECT * FROM composicao_corporal WHERE id=%s AND patient_id=%s",
            (cid, patient_id)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Avaliação não encontrada")
    return serialize_row(row)


@router.post(
    "/composicao/retrain",
    summary="Retreina o modelo ML com dados reais (admin)",
    dependencies=[Depends(require_api_key)],
)
def retrain_model(settings: Annotated[Settings, Depends(get_settings)]):
    """Retreina o GBR com dados reais do banco. Protegido por X-API-Key."""
    from nutrideby.ml.bio_model import BioComposicaoModel, MODEL_PATH, _features
    import numpy as np

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        rows = conn.cursor().execute(
            """SELECT altura_cm, peso_kg, idade, sexo,
                      gordura_pct, massa_muscular_kg
               FROM bioimpedancia_logs
               WHERE gordura_pct IS NOT NULL AND massa_muscular_kg IS NOT NULL
               LIMIT 50000"""
        ).fetchall()

    if len(rows) < 100:
        return {"status": "skip", "motivo": f"Apenas {len(rows)} registros reais — mínimo 100 para retreino"}

    X     = np.vstack([_features(r["altura_cm"], r["peso_kg"], r["idade"], r["sexo"]) for r in rows])
    fat_y = np.array([float(r["gordura_pct"]) for r in rows])
    smm_y = np.array([float(r["massa_muscular_kg"]) for r in rows])

    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    def _gbr(loss="squared_error", alpha=0.5):
        return Pipeline([
            ("scaler", StandardScaler()),
            ("gbr", GradientBoostingRegressor(n_estimators=300, max_depth=5,
                                               learning_rate=0.05, subsample=0.8,
                                               loss=loss, alpha=alpha, random_state=42)),
        ])

    m = BioComposicaoModel()
    m._fat_model = _gbr().fit(X, fat_y)
    m._smm_model = _gbr().fit(X, smm_y)
    m._fat_lo    = _gbr("quantile", 0.10).fit(X, fat_y)
    m._fat_hi    = _gbr("quantile", 0.90).fit(X, fat_y)
    m._trained   = True
    m.save(MODEL_PATH)

    from nutrideby.ml import bio_model as bm_module
    bm_module._model = m

    return {"status": "ok", "amostras": len(rows)}

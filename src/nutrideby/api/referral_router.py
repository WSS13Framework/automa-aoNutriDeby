"""referral_router.py — Sistema de indicação NutriDeby."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from nutrideby.api.deps import get_settings
from nutrideby.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/referral", tags=["referral"])


def _ensure_referral_code(conn, patient_id: str) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT referral_code FROM patients WHERE id = %s", (patient_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Paciente não encontrado")
        code = row["referral_code"]
        if not code:
            code = secrets.token_urlsafe(6).upper()
            cur.execute("UPDATE patients SET referral_code = %s WHERE id = %s", (code, patient_id))
            conn.commit()
    return code


@router.post("/apply-code/{patient_id}")
def apply_referral_code(
    patient_id: str,
    code: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, referred_by_id, trial_ends_at FROM patients WHERE id = %s",
                (patient_id,),
            )
            afilhado = cur.fetchone()

        if not afilhado:
            raise HTTPException(status_code=404, detail="Paciente não encontrado")

        if afilhado["referred_by_id"]:
            raise HTTPException(status_code=409, detail="Você já usou um código de indicação")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name, trial_ends_at FROM patients WHERE referral_code = %s",
                (code.upper(),),
            )
            padrinho = cur.fetchone()

        if not padrinho:
            raise HTTPException(status_code=404, detail="Código de indicação inválido")

        if str(padrinho["id"]) == patient_id:
            raise HTTPException(status_code=400, detail="Você não pode usar seu próprio código")

        now = datetime.now(tz=timezone.utc)
        bonus = timedelta(days=3)

        def _safe_trial(trial_ends_at):
            t = trial_ends_at or now
            if hasattr(t, "tzinfo") and t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return max(t, now) + bonus

        new_trial_afilhado = _safe_trial(afilhado["trial_ends_at"])
        new_trial_padrinho = _safe_trial(padrinho["trial_ends_at"])

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE patients SET referred_by_id = %s, trial_ends_at = %s WHERE id = %s",
                (padrinho["id"], new_trial_afilhado, patient_id),
            )
            cur.execute(
                "UPDATE patients SET trial_ends_at = %s WHERE id = %s",
                (new_trial_padrinho, padrinho["id"]),
            )
            cur.execute(
                """INSERT INTO referral_rewards (referrer_id, referred_id, days_awarded)
                   VALUES (%s, %s, 3) ON CONFLICT (referred_id) DO NOTHING""",
                (padrinho["id"], patient_id),
            )
            conn.commit()

    logger.info("referral aplicado: afilhado=%s padrinho=%s code=%s", patient_id, padrinho["id"], code)
    return {
        "message": f"Código aplicado! Você e {padrinho.get('display_name') or 'seu padrinho'} ganharam +3 dias Premium.",
        "new_trial_ends_at": new_trial_afilhado.isoformat(),
    }


@router.get("/status/{patient_id}")
def referral_status(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        code = _ensure_referral_code(conn, patient_id)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM referral_rewards WHERE referrer_id = %s",
                (patient_id,),
            )
            row = cur.fetchone()

    if row:
        v = row.get("total") if hasattr(row, "get") else row[0]
        total = int(v)
    else:
        total = 0
    base_url = "https://app.nutrideby.com.br"
    return {
        "referral_code": code,
        "total_referred": total,
        "share_link": f"{base_url}/cadastro?ref={code}",
        "reward_description": "+3 dias Premium para você e seu amigo",
    }

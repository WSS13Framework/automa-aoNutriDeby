"""
paciente_acesso_router.py — Onboarding de pacientes via código único.
Rotas:
  POST /api/pacientes/convite              → Gera código 6 dígitos + URL do app
  GET  /api/pacientes/{id}/validar         → Valida código e libera sessão JWT
  POST /api/pacientes/convite/bulk         → Gera convites para todos os pacientes ativos
  GET  /api/pacientes/{id}/painel          → Visão espelhada do paciente (dados + prontuários)
"""
from __future__ import annotations

import random
import string
import logging
from datetime import datetime, timezone
from typing import Annotated

import jwt
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel

from nutrideby.api.deps import get_settings
from nutrideby.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pacientes", tags=["paciente-acesso"])

_MAX_TENTATIVAS = 5


def _gerar_codigo() -> str:
    return ''.join(random.choices(string.digits, k=6))


def _codigo_unico(conn) -> str:
    for _ in range(10):
        cod = _gerar_codigo()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM acesso_paciente WHERE codigo_unico = %s", (cod,))
            if not cur.fetchone():
                return cod
    raise RuntimeError("Não foi possível gerar código único")


# ── Schemas ───────────────────────────────────────────────────────────────────

class ConviteRequest(BaseModel):
    paciente_id: str


class BulkConviteRequest(BaseModel):
    sobrescrever: bool = False  # se True, recria código mesmo para quem já tem


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/convite")
def gerar_convite(
    body: ConviteRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Gera código único de 6 dígitos para o paciente acessar o app.
    Se já tem convite pendente, devolve o existente.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Verifica se paciente existe
            cur.execute(
                "SELECT id, display_name, email FROM patients WHERE id = %s",
                (body.paciente_id,),
            )
            paciente = cur.fetchone()
            if not paciente:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")

            # Verifica se já tem convite ativo/pendente
            cur.execute(
                "SELECT codigo_unico, status_acesso FROM acesso_paciente "
                "WHERE paciente_id = %s ORDER BY data_convite DESC LIMIT 1",
                (body.paciente_id,),
            )
            existente = cur.fetchone()

        if existente and existente["status_acesso"] in ("pendente", "ativo"):
            codigo = existente["codigo_unico"]
        else:
            codigo = _codigo_unico(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO acesso_paciente (paciente_id, codigo_unico, status_acesso)
                    VALUES (%s, %s, 'pendente')
                    ON CONFLICT (codigo_unico) DO NOTHING
                    """,
                    (body.paciente_id, codigo),
                )
                conn.commit()

    base = (settings.app_base_url or "https://app.nutrideby.com").rstrip("/")
    url_app = f"{base}/entrar?codigo={codigo}&id={body.paciente_id}"

    return {
        "paciente_id": body.paciente_id,
        "paciente_nome": paciente["display_name"],
        "codigo_unico": codigo,
        "url_app": url_app,
        "instrucoes": f"Acesse {base} e informe o código: {codigo}",
    }


@router.get("/{paciente_id}/validar")
def validar_acesso(
    paciente_id: str,
    codigo: str = Query(..., min_length=6, max_length=6),
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> dict:
    """
    Valida código e libera sessão JWT para o paciente.
    Bloqueio automático após 5 tentativas erradas.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.codigo_unico, a.status_acesso,
                       a.tentativas, a.bloqueado_ate,
                       p.id as pid, p.display_name, p.email
                FROM acesso_paciente a
                JOIN patients p ON p.id = a.paciente_id
                WHERE a.paciente_id = %s
                ORDER BY a.data_convite DESC LIMIT 1
                """,
                (paciente_id,),
            )
            acesso = cur.fetchone()

        if not acesso:
            raise HTTPException(status_code=404, detail="Convite não encontrado")

        # Verifica bloqueio
        if acesso.get("bloqueado_ate") and acesso["bloqueado_ate"] > datetime.now(timezone.utc):
            raise HTTPException(status_code=429, detail="Acesso bloqueado temporariamente. Tente em 30 minutos.")

        # Valida código
        if acesso["codigo_unico"] != codigo:
            novas_tentativas = (acesso["tentativas"] or 0) + 1
            bloqueio = None
            if novas_tentativas >= _MAX_TENTATIVAS:
                from datetime import timedelta
                bloqueio = datetime.now(timezone.utc) + timedelta(minutes=30)
                novas_tentativas = 0

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE acesso_paciente SET tentativas=%s, bloqueado_ate=%s WHERE id=%s",
                    (novas_tentativas, bloqueio, acesso["id"]),
                )
                conn.commit()

            restantes = _MAX_TENTATIVAS - novas_tentativas
            raise HTTPException(
                status_code=400,
                detail=f"Código incorreto. {restantes} tentativa(s) restante(s).",
            )

        # Código correto — ativa acesso
        agora = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE acesso_paciente
                SET status_acesso = 'ativo',
                    data_primeiro_acesso = COALESCE(data_primeiro_acesso, %s),
                    tentativas = 0,
                    bloqueado_ate = NULL
                WHERE id = %s
                """,
                (agora, acesso["id"]),
            )
            conn.commit()

    # Gera JWT do paciente
    token = None
    if settings.jwt_secret:
        from datetime import timedelta
        exp = agora + timedelta(days=30)
        token = jwt.encode(
            {"sub": str(acesso["pid"]), "type": "patient", "exp": exp},
            str(settings.jwt_secret),
            algorithm="HS256",
        )

    return {
        "ok": True,
        "paciente_id": str(acesso["pid"]),
        "nome": acesso["display_name"],
        "primeiro_acesso": not acesso.get("data_primeiro_acesso"),
        "access_token": token,
        "token_type": "bearer",
    }


@router.post("/convite/bulk")
def bulk_convites(
    body: BulkConviteRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Gera convites para todos os 863 pacientes ativos de uma vez.
    Retorna lista com paciente_id, nome, código e URL.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.display_name, p.email
                FROM patients p
                WHERE p.display_name IS NOT NULL
                ORDER BY p.display_name
                """
            )
            pacientes = cur.fetchall()

        base = (settings.app_base_url or "https://app.nutrideby.com").rstrip("/")
        gerados = []
        ja_tem = 0

        for p in pacientes:
            pid = str(p["id"])

            # Verifica se já tem convite
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT codigo_unico FROM acesso_paciente "
                    "WHERE paciente_id = %s AND status_acesso IN ('pendente','ativo') LIMIT 1",
                    (pid,),
                )
                existente = cur.fetchone()

            if existente and not body.sobrescrever:
                ja_tem += 1
                gerados.append({
                    "paciente_id": pid,
                    "nome": p["display_name"],
                    "codigo": existente["codigo_unico"],
                    "url": f"{base}/entrar?codigo={existente['codigo_unico']}&id={pid}",
                    "novo": False,
                })
                continue

            codigo = _codigo_unico(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO acesso_paciente (paciente_id, codigo_unico, status_acesso)
                    VALUES (%s, %s, 'pendente')
                    ON CONFLICT DO NOTHING
                    """,
                    (pid, codigo),
                )
                conn.commit()

            gerados.append({
                "paciente_id": pid,
                "nome": p["display_name"],
                "codigo": codigo,
                "url": f"{base}/entrar?codigo={codigo}&id={pid}",
                "novo": True,
            })

        novos = sum(1 for g in gerados if g["novo"])

    return {
        "total_pacientes": len(pacientes),
        "novos_convites": novos,
        "ja_tinham_convite": ja_tem,
        "convites": gerados,
    }


@router.get("/{paciente_id}/painel")
def painel_paciente(
    paciente_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Visão espelhada — paciente vê seus próprios dados:
    perfil, medidas, prescrições, prontuários clínicos, food logs.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Perfil
            cur.execute(
                """
                SELECT id, display_name, email, subscription_status,
                       deby_level, deby_xp, current_streak, league_name,
                       daily_calories_target, daily_protein_target,
                       daily_carbs_target, daily_fat_target
                FROM patients WHERE id = %s
                """,
                (paciente_id,),
            )
            paciente = cur.fetchone()
            if not paciente:
                raise HTTPException(status_code=404, detail="Paciente não encontrado")

            # Medidas mais recentes
            cur.execute(
                """
                SELECT descricao, data_avaliacao, payload
                FROM dietbox_medidas
                WHERE patient_id = %s
                ORDER BY data_avaliacao DESC LIMIT 5
                """,
                (paciente_id,),
            )
            medidas = cur.fetchall()

            # Prontuários clínicos
            cur.execute(
                """
                SELECT cr.id, cr.status, cr.created_at, cr.signed_at,
                       cr.pdf_url, cr.d4sign_signed_pdf_url,
                       cr.extracted_biochemistry,
                       pn.name as nutricionista
                FROM clinical_records cr
                LEFT JOIN professional_nutricionistas pn ON pn.id = cr.nutricionista_id
                WHERE cr.patient_id = %s
                ORDER BY cr.created_at DESC
                """,
                (paciente_id,),
            )
            prontuarios = cur.fetchall()

            # Últimos food logs
            cur.execute(
                """
                SELECT meal_type, logged_at, total_calories, total_protein,
                       total_carbs, total_fat
                FROM food_logs
                WHERE patient_id = %s
                ORDER BY logged_at DESC LIMIT 10
                """,
                (paciente_id,),
            )
            food_logs = cur.fetchall()

    import json

    return {
        "perfil": {
            "id": str(paciente["id"]),
            "nome": paciente["display_name"],
            "email": paciente["email"],
            "assinatura": paciente["subscription_status"],
            "nivel": paciente["deby_level"],
            "xp": paciente["deby_xp"],
            "streak": paciente["current_streak"],
            "liga": paciente["league_name"],
            "metas": {
                "calorias": paciente["daily_calories_target"],
                "proteina": paciente["daily_protein_target"],
                "carboidrato": paciente["daily_carbs_target"],
                "gordura": paciente["daily_fat_target"],
            },
        },
        "medidas": [
            {
                "descricao": m["descricao"],
                "data": m["data_avaliacao"].isoformat() if m.get("data_avaliacao") else None,
                "dados": m["payload"] if isinstance(m["payload"], dict) else json.loads(m["payload"] or "{}"),
            }
            for m in medidas
        ],
        "prontuarios": [
            {
                "id": p["id"],
                "status": p["status"],
                "data": p["created_at"].isoformat() if p.get("created_at") else None,
                "assinado_em": p["signed_at"].isoformat() if p.get("signed_at") else None,
                "pdf_url": p.get("d4sign_signed_pdf_url") or p.get("pdf_url"),
                "nutricionista": p.get("nutricionista"),
            }
            for p in prontuarios
        ],
        "alimentacao_recente": [
            {
                "refeicao": f["meal_type"],
                "data": f["logged_at"].isoformat() if f.get("logged_at") else None,
                "calorias": f["total_calories"],
                "proteina": f["total_protein"],
            }
            for f in food_logs
        ],
    }

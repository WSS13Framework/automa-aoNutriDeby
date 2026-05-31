"""
Hermes Agent — NutriDeby
Seleciona pacientes por perfil → Claude/DeepSeek gera mensagem → Twilio envia.

Profiles:
  inativo_30  — sem atividade há 30+ dias
  inativo_14  — sem atividade há 14-29 dias
  inativo_7   — sem atividade há 7-13 dias
  ativo       — com atividade nos últimos 6 dias

LLM: Anthropic Claude (primário) → DeepSeek (fallback).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# ── Credenciais ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
TWILIO_SID        = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN      = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM       = os.getenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")
DATABASE_URL      = os.getenv("DATABASE_URL", "postgresql://nutrideby:nutrideby_dev@postgres:5432/nutrideby")

# ── Perfis ────────────────────────────────────────────────────────────────────
PROFILES: dict[str, dict[str, Any]] = {
    "inativo_30": {
        "label": "Inativo 30+ dias",
        "goal_statement": (
            "Reconectar pacientes que não aparecem há mais de 30 dias. "
            "O objetivo é mostrar que a nutricionista lembra deles pessoalmente e "
            "abrir porta para retomada do acompanhamento sem pressão ou cobrança."
        ),
        "days_min": 30,
        "days_max": None,
    },
    "inativo_14": {
        "label": "Inativo 14-29 dias",
        "goal_statement": (
            "Reengajar pacientes que sumiram há 2 a 4 semanas — janela crítica antes "
            "do afastamento definitivo. A mensagem deve ser calorosa e convidar resposta."
        ),
        "days_min": 14,
        "days_max": 29,
    },
    "inativo_7": {
        "label": "Inativo 7-13 dias",
        "goal_statement": (
            "Check-in leve para pacientes que faltaram uma semana. "
            "Reforçar o vínculo antes de se distanciar mais, sem alarmismo."
        ),
        "days_min": 7,
        "days_max": 13,
    },
    "ativo": {
        "label": "Ativo",
        "goal_statement": (
            "Motivar e engajar pacientes que estão ativos. "
            "Celebrar consistência, reforçar progresso e manter o momentum do acompanhamento."
        ),
        "days_min": None,
        "days_max": 6,
    },
}

ALL_PROFILES = list(PROFILES.keys())


# ── Queries ───────────────────────────────────────────────────────────────────

def get_patients_by_profile(
    conn: psycopg.Connection,
    profile: str,
    limit: int = 10,
) -> list[dict]:
    """Retorna pacientes filtrados pelo perfil de inatividade."""
    if profile not in PROFILES:
        raise ValueError(f"Perfil inválido: {profile}. Use: {ALL_PROFILES}")

    cfg = PROFILES[profile]
    days_min = cfg["days_min"]
    days_max = cfg["days_max"]

    # Filtro de dias baseado em last_logged_date ou metadata LastConsultation
    days_clauses = []
    if days_min is not None:
        days_clauses.append(
            f"(CURRENT_DATE - COALESCE(p.last_logged_date, "
            f"(p.metadata->>'LastConsultation')::date)) >= {days_min}"
        )
    if days_max is not None:
        days_clauses.append(
            f"(CURRENT_DATE - COALESCE(p.last_logged_date, "
            f"(p.metadata->>'LastConsultation')::date)) <= {days_max}"
        )

    days_filter = ("AND " + " AND ".join(days_clauses)) if days_clauses else ""

    sql = f"""
        SELECT
            p.id,
            p.display_name,
            COALESCE(
                pp.phone,
                CASE
                    WHEN length(regexp_replace(
                            p.metadata->>'MobilePhone', '[^0-9]', '', 'g')) >= 10
                    THEN '+55' || regexp_replace(
                            p.metadata->>'MobilePhone', '[^0-9]', '', 'g')
                END
            ) AS phone,
            p.metadata->>'Occupancy'         AS ocupacao,
            p.metadata->>'Birthday'          AS nascimento,
            p.metadata->>'LastConsultation'  AS ultima_consulta,
            p.metadata->>'Gender'            AS genero,
            COALESCE(
                p.last_logged_date,
                (p.metadata->>'LastConsultation')::date
            ) AS last_activity_date,
            CURRENT_DATE - COALESCE(
                p.last_logged_date,
                (p.metadata->>'LastConsultation')::date
            ) AS days_inactive
        FROM patients p
        LEFT JOIN patient_phones pp ON pp.patient_id = p.id
        WHERE (
            pp.phone IS NOT NULL
            OR (
                p.metadata->>'MobilePhone' IS NOT NULL
                AND length(regexp_replace(
                        p.metadata->>'MobilePhone', '[^0-9]', '', 'g')) >= 10
            )
        )
        AND COALESCE(
            p.last_logged_date,
            (p.metadata->>'LastConsultation')::date
        ) IS NOT NULL
        {days_filter}
        ORDER BY last_activity_date ASC NULLS LAST
        LIMIT %s
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, [limit])
        return cur.fetchall()


def get_prontuario(conn: psycopg.Connection, patient_id: str) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT c.text
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.patient_id = %s
              AND c.text IS NOT NULL
              AND c.text NOT LIKE '[Prontuário: API 204%%'
            ORDER BY d.collected_at DESC
            LIMIT 5
        """, [patient_id])
        rows = cur.fetchall()
        return " ".join(r["text"] for r in rows if r["text"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def calcular_idade(nascimento: Any) -> int | None:
    try:
        ano = int(str(nascimento)[:4])
        return datetime.now().year - ano if ano > 1900 else None
    except Exception:
        return None


def formatar_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if not digits.startswith("55"):
        return f"+55{digits}"
    return f"+{digits}"


# ── LLM ──────────────────────────────────────────────────────────────────────

def _build_prompt(
    patient: dict,
    prontuario: str,
    profile: str,
    nutricionista_nome: str,
) -> tuple[str, str]:
    """Retorna (system_prompt, user_prompt) com goal_statement embutido."""
    goal = PROFILES[profile]["goal_statement"]
    nome      = patient["display_name"] or "paciente"
    primeiro  = nome.split()[0]
    idade     = calcular_idade(patient.get("nascimento"))
    ocupacao  = patient.get("ocupacao") or ""
    ultima    = (patient.get("ultima_consulta") or "")[:10] or "algum tempo"
    dias      = patient.get("days_inactive")
    contexto  = f"Prontuário resumido: {prontuario[:500]}" if prontuario else "Sem prontuário detalhado."

    system_prompt = (
        f"Você é a assistente virtual da nutricionista {nutricionista_nome}.\n\n"
        f"OBJETIVO DESTA MENSAGEM: {goal}\n\n"
        "Regras absolutas:\n"
        "- Máximo 100 palavras\n"
        "- Tom humano, acolhedor, sem pressão\n"
        "- Mencione algo específico do prontuário se houver\n"
        f"- Mostre que {nutricionista_nome} lembra do paciente\n"
        "- Termine com UMA pergunta simples sobre como está hoje\n"
        "- Não mencione preço nem plano\n"
        f"- Assine como: Assistente da {nutricionista_nome} 🥗\n"
        "- Escreva apenas a mensagem, sem explicações"
    )

    dias_texto = f"{dias} dias" if dias is not None else "algum tempo"
    user_prompt = (
        f"Escreva uma mensagem de WhatsApp para o paciente {primeiro}.\n\n"
        f"Dados:\n"
        f"- Nome: {primeiro}\n"
        f"- Idade: {idade} anos\n"
        f"- Ocupação: {ocupacao}\n"
        f"- Última atividade: {ultima} ({dias_texto} atrás)\n"
        f"- {contexto}"
    )

    return system_prompt, user_prompt


def _claude(system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=256,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


def _deepseek(system: str, user: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
    r = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.8,
        max_tokens=200,
    )
    return r.choices[0].message.content.strip()


def gerar_mensagem(
    patient: dict,
    prontuario: str,
    profile: str,
    nutricionista_nome: str = "Dra. Débora",
) -> str:
    system, user = _build_prompt(patient, prontuario, profile, nutricionista_nome)
    primeiro = (patient["display_name"] or "paciente").split()[0]

    if ANTHROPIC_API_KEY:
        try:
            logger.info("LLM: Claude (%s)", ANTHROPIC_MODEL)
            return _claude(system, user)
        except Exception as exc:
            logger.warning("Claude falhou (%s) — usando DeepSeek como fallback", exc)

    if DEEPSEEK_API_KEY:
        try:
            logger.info("LLM: DeepSeek (fallback)")
            return _deepseek(system, user)
        except Exception as exc:
            logger.error("DeepSeek falhou: %s", exc)

    # Fallback hardcoded
    return (
        f"Oi {primeiro}! 😊 Aqui é a assistente da {nutricionista_nome}. "
        f"Faz um tempo que não nos falamos e gostaríamos de saber como você está. "
        f"A {nutricionista_nome} tem agenda aberta para retomar seu acompanhamento. "
        f"Como você está hoje?"
    )


# ── Twilio ────────────────────────────────────────────────────────────────────

def enviar_twilio(phone: str, mensagem: str) -> tuple[str, str]:
    from twilio.rest import Client as TwilioClient
    twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    msg = twilio.messages.create(
        from_=TWILIO_FROM,
        body=mensagem,
        to=f"whatsapp:{phone}",
    )
    return msg.sid, msg.status


# ── Runner ────────────────────────────────────────────────────────────────────

def run(
    limit: int = 5,
    dry_run: bool = True,
    profile: str = "inativo_30",
    nutricionista_nome: str = "Dra. Débora",
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    cfg = PROFILES[profile]
    logger.info(
        "Hermes | perfil=%s (%s) | limit=%d | dry_run=%s | nutri=%s",
        profile, cfg["label"], limit, dry_run, nutricionista_nome,
    )
    logger.info("Objetivo: %s", cfg["goal_statement"])

    with psycopg.connect(DATABASE_URL) as conn:
        patients = get_patients_by_profile(conn, profile, limit)
        logger.info("%d pacientes encontrados para perfil '%s'", len(patients), profile)

        enviados = 0
        erros    = 0

        for p in patients:
            nome      = p["display_name"] or "Paciente"
            phone_raw = p["phone"]
            phone     = formatar_phone(phone_raw)
            dias      = p.get("days_inactive")

            prontuario = get_prontuario(conn, p["id"])
            mensagem   = gerar_mensagem(p, prontuario, profile, nutricionista_nome)

            logger.info("=" * 50)
            logger.info("Para: %s (%s) | %s dias inativo", nome, phone, dias)
            logger.info("Mensagem:\n%s", mensagem)
            logger.info("=" * 50)

            if not dry_run:
                try:
                    sid, status = enviar_twilio(phone, mensagem)
                    logger.info("ENVIADO: sid=%s status=%s", sid, status)
                    enviados += 1
                except Exception as exc:
                    logger.error("ERRO ao enviar: %s", exc)
                    erros += 1
                time.sleep(30)
            else:
                logger.info("DRY RUN — não enviado")

    logger.info(
        "Hermes concluído: enviados=%d erros=%d dry_run=%s",
        enviados, erros, dry_run,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    p = argparse.ArgumentParser(description="Hermes Agent — mensagens personalizadas por perfil")
    p.add_argument("--limit",    type=int,  default=5,          help="Máx. pacientes por execução")
    p.add_argument("--profile",  default="inativo_30",          help=f"Perfil: {ALL_PROFILES}")
    p.add_argument("--nutri",    default="Dra. Débora",         help="Nome da nutricionista")
    p.add_argument("--dry-run",  action="store_true",           help="Simula sem enviar")
    p.add_argument("--send",     action="store_true",           help="Envia de verdade")
    args = p.parse_args()

    run(
        limit=args.limit,
        dry_run=not args.send,
        profile=args.profile,
        nutricionista_nome=args.nutri,
    )


if __name__ == "__main__":
    _cli()

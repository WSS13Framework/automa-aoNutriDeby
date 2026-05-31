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
        AND NOT EXISTS (
            SELECT 1 FROM inbound_messages im
            WHERE im.patient_id = p.id
              AND im.message_type = 'hermes_outbound'
              AND im.received_at::date = CURRENT_DATE
        )
        ORDER BY last_activity_date ASC NULLS LAST
        LIMIT %s
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, [limit])
        return cur.fetchall()



def get_patient_clinical_context(conn, patient_id: str) -> dict:
    """
    Cruza todos os dados clínicos disponíveis do paciente para montar
    o contexto "onde ele parou" — gatilho dopaminérgico de reconhecimento.

    Retorna dict com:
      - metas: lista de metas da nutricionista (meta export)
      - plano_resumo: objetivo + kcal + macros do plano ativo
      - comportamento: respostas do QPC sobre alimentação emocional
      - ultima_consulta_qpc: data da última consulta registrada no QPC
      - texto_completo: texto consolidado para o prompt
    """
    import json as _json
    from psycopg.rows import dict_row as _dict_row

    result = {
        "metas": [],
        "plano_resumo": "",
        "comportamento": "",
        "ultima_consulta_qpc": "",
        "texto_completo": "",
    }

    with conn.cursor(row_factory=_dict_row) as cur:
        cur.execute("""
            SELECT doc_type, content_text, collected_at
            FROM documents
            WHERE patient_id = (
              SELECT id FROM patients
              WHERE (metadata->>'dietbox_paciente_id' = %s
                     OR (source_system='dietbox' AND external_id = %s))
              LIMIT 1
            )
            AND doc_type IN ('dietbox_meta_export','dietbox_plano_alimentar','dietbox_qpc_respostas')
            ORDER BY doc_type, collected_at DESC
        """, (patient_id, patient_id))
        docs = cur.fetchall()

    for doc in docs:
        ct = doc["content_text"] or ""
        dtype = doc["doc_type"]

        if not ct.startswith("{"):
            continue
        try:
            data = _json.loads(ct)
        except Exception:
            continue

        summary = data.get("text_summary", "")

        if dtype == "dietbox_meta_export":
            items = data.get("items", [])
            for item in items:
                nome = item.get("nome") or item.get("name") or ""
                desc = item.get("descricao") or item.get("description") or ""
                if nome:
                    result["metas"].append(f"{nome}: {desc[:120]}" if desc else nome)

        elif dtype == "dietbox_plano_alimentar":
            if result["plano_resumo"]:
                continue  # só o mais recente
            plans = data.get("plans", [])
            for plan in plans:
                if plan.get("IsActive"):
                    descricao = plan.get("Description") or ""
                    kcal = plan.get("ReferenceCalories") or ""
                    prot = round((plan.get("ReferenceProteinPercentage") or 0) * 100)
                    result["plano_resumo"] = (
                        f"Plano ativo: {descricao[:200]}. "
                        f"Meta: {kcal} kcal/dia, {prot}% proteína."
                    )
                    break
            if not result["plano_resumo"] and plans:
                # pega o primeiro mesmo sem IsActive
                p = plans[0]
                descricao = p.get("Description") or ""
                kcal = p.get("ReferenceCalories") or ""
                result["plano_resumo"] = f"Último plano: {descricao[:200]}. Meta: {kcal} kcal/dia."

        elif dtype == "dietbox_qpc_respostas":
            if result["comportamento"]:
                continue
            qpcs = data.get("qpcs", [])
            if qpcs:
                # pega o QPC mais recente com respostas
                ultimo = qpcs[0]
                result["ultima_consulta_qpc"] = (ultimo.get("Date") or "")[:10]
                # extrai respostas relevantes (comportamento alimentar)
                questions_raw = ultimo.get("Questions") or "[]"
                if isinstance(questions_raw, str):
                    try:
                        questions = _json.loads(questions_raw)
                    except Exception:
                        questions = []
                else:
                    questions = questions_raw or []

                comportamentos = []
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    label = re.sub(r"<[^>]+>", "", q.get("label", "")).strip()
                    val = q.get("userData") or q.get("value") or ""
                    if val and label and q.get("type") not in ("header", "paragraph", "button"):
                        if any(kw in label.lower() for kw in
                               ["objetivo", "dificuldade", "principal", "gostaria",
                                "hábito", "motivo", "ansio", "emocion", "estress",
                                "exerc", "sono", "médica", "remédio"]):
                            comportamentos.append(f"- {label}: {str(val)[:80]}")
                        if len(comportamentos) >= 5:
                            break
                result["comportamento"] = "\n".join(comportamentos)

    # Monta texto completo para o prompt
    partes = []
    if result["metas"]:
        metas_str = "; ".join(result["metas"][:3])
        partes.append(f"Metas definidas pela nutricionista: {metas_str}")
    if result["plano_resumo"]:
        partes.append(result["plano_resumo"])
    if result["comportamento"]:
        partes.append(f"Respostas da anamnese:\n{result['comportamento']}")
    if result["ultima_consulta_qpc"]:
        partes.append(f"Última consulta registrada: {result['ultima_consulta_qpc']}")

    result["texto_completo"] = "\n\n".join(partes)
    return result

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
) -> tuple[str, str, str]:
    """Retorna (static_system, dynamic_system, user_prompt) para prompt caching."""
    goal = PROFILES[profile]["goal_statement"]
    nome      = patient["display_name"] or "paciente"
    primeiro  = nome.split()[0]
    idade     = calcular_idade(patient.get("nascimento"))
    ocupacao  = patient.get("ocupacao") or ""
    ultima    = (patient.get("ultima_consulta") or "")[:10] or "algum tempo"
    dias      = patient.get("days_inactive")
    # Usa contexto clínico rico se disponível, senão cai no prontuário básico
    if prontuario and len(prontuario) > 100:
        contexto = prontuario[:1200]
    else:
        contexto = "Sem dados clínicos detalhados disponíveis."

    # Parte estática: identidade + objetivo + contexto clínico (cacheável por perfil)
    static_system = (
        f"Você é a assistente virtual da nutricionista {nutricionista_nome}.\n\n"
        f"OBJETIVO DESTA MENSAGEM: {goal}\n\n"
        f"CONTEXTO CLÍNICO DO PACIENTE:\n{contexto}\n\n"
        "ESTRATÉGIA DE REENGAJAMENTO — GATILHO DE RECONHECIMENTO:\n"
        "A mensagem deve provar que a nutricionista LEMBRA EXATAMENTE onde o paciente parou.\n"
        "Use os dados clínicos acima para mencionar algo específico:\n"
        "  - Uma meta que o paciente estava trabalhando\n"
        "  - Um objetivo do plano alimentar (ex: ganho de massa, perda de gordura)\n"
        "  - Um hábito ou desafio que ele mencionou na consulta\n"
        "Isso ativa reconhecimento e dopamina — o paciente sente que não foi esquecido.\n\n"
        "Regras absolutas:\n"
        "- Máximo 100 palavras\n"
        "- Tom humano, acolhedor, sem pressão nem cobrança\n"
        "- Mencione UM detalhe específico do histórico do paciente\n"
        f"- Mostre que {nutricionista_nome} lembra desta pessoa especificamente\n"
        "- Termine com UMA pergunta aberta sobre como está hoje\n"
        "- Não mencione preço, plano ou pagamento\n"
        f"- Assine como: Assistente da {nutricionista_nome} 🥗\n"
        "- Escreva apenas a mensagem"
    )

    dias_texto = f"{dias} dias" if dias is not None else "algum tempo"

    # Parte dinâmica: dados específicos do paciente (não cacheável)
    dynamic_system = (
        f"Paciente: {primeiro} | Idade: {idade} anos | Ocupação: {ocupacao}\n"
        f"Última atividade: {ultima} ({dias_texto} atrás)"
    )

    user_prompt = f"Escreva uma mensagem de WhatsApp personalizada para {primeiro}."

    return static_system, dynamic_system, user_prompt


def _claude(static_system: str, dynamic_system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=256,
        timeout=30.0,
        system=[
            {
                "type": "text",
                "text": static_system,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": dynamic_system,
            },
        ],
        messages=[{"role": "user", "content": user}],
    )
    usage = msg.usage
    cache_read    = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    logger.info("cache: read=%d created=%d input=%d", cache_read, cache_created, usage.input_tokens)
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
    static_system, dynamic_system, user = _build_prompt(patient, prontuario, profile, nutricionista_nome)
    primeiro = (patient["display_name"] or "paciente").split()[0]
    system = f"{static_system}\n\n{dynamic_system}"  # combinado para fallback DeepSeek

    if ANTHROPIC_API_KEY:
        try:
            logger.info("LLM: Claude (%s)", ANTHROPIC_MODEL)
            return _claude(static_system, dynamic_system, user)
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
            # Cruza dados clínicos reais (plano alimentar + QPC + metas)
            dietbox_id = str(p.get("id") or "")
            ctx = get_patient_clinical_context(conn, dietbox_id)
            contexto_clinico = ctx["texto_completo"] or prontuario
            mensagem   = gerar_mensagem(p, contexto_clinico, profile, nutricionista_nome)

            logger.info("=" * 50)
            logger.info("Para: %s (%s) | %s dias inativo", nome, phone, dias)
            logger.info("Mensagem:\n%s", mensagem)
            logger.info("=" * 50)

            if not dry_run:
                try:
                    sid, status = enviar_twilio(phone, mensagem)
                    logger.info("ENVIADO: sid=%s status=%s", sid, status)
                    enviados += 1
                    # Registra envio para deduplicação — impede reenvio no mesmo dia
                    with conn.cursor() as _cur:
                        _cur.execute(
                            """
                            INSERT INTO inbound_messages
                              (patient_id, phone, message_type, reply_body, replied_at)
                            VALUES (%s, %s, 'hermes_outbound', %s, NOW())
                            ON CONFLICT DO NOTHING
                            """,
                            (str(p["id"]), phone, mensagem[:500]),
                        )
                        conn.commit()
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

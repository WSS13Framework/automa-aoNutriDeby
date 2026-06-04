"""
Processador de mensagens inbound WhatsApp (NutriDeby).

Fluxo:
  1. Recebe mensagem Twilio (texto, imagem ou áudio)
  2. Identifica patient_id pelo telefone (patient_phones)
  3. Se paciente NÃO existe → AUTO-REGISTER + onboarding proativo
  4. Se áudio → transcreve via Whisper → salva no prontuário
  5. Se imagem → GPT-4o Vision → extrai texto do exame/alimento
  6. Insere documento no paciente (lab_report ou food_log)
  7. Chunk + embed automático
  8. POST /v1/patients/{id}/analyze → análise clínica RAG
  9. Responde ao paciente via Twilio
"""
from __future__ import annotations

import base64
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone as _tz
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row
from twilio.rest import Client as TwilioClient

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    """Remove prefixo 'whatsapp:' e caracteres não numéricos, mantém DDI."""
    s = raw.replace("whatsapp:", "").strip()
    digits = re.sub(r"\D", "", s)
    # Garante DDI Brasil se curto (mas não se já tem DDI internacional)
    if len(digits) <= 11 and not digits.startswith("1"):
        digits = "55" + digits
    return digits


def _find_patient(conn: psycopg.Connection, phone: str) -> dict | None:
    """Resolve phone → patient via patient_phones."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT p.id, p.display_name, p.external_id, p.created_at,
                   p.subscription_status, p.trial_ends_at, p.reactivation_stage
            FROM patient_phones pp
            JOIN patients p ON p.id = pp.patient_id
            WHERE pp.phone = %s
            LIMIT 1
            """,
            (phone,),
        )
        return cur.fetchone()


def _find_patient_by_metadata(conn: psycopg.Connection, phone: str) -> dict | None:
    """Fallback: busca pelo MobilePhone no metadata (Dietbox)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, display_name, external_id, created_at,
                   subscription_status, trial_ends_at, reactivation_stage
            FROM patients
            WHERE regexp_replace(metadata->>'MobilePhone', '[^0-9]', '', 'g') = %s
               OR regexp_replace(metadata->>'MobilePhone', '[^0-9]', '', 'g') = %s
            LIMIT 1
            """,
            (phone, phone[-11:]),  # tenta com e sem DDI
        )
        row = cur.fetchone()
        if row:
            # Registra na tabela para próximas mensagens
            try:
                cur.execute(
                    """
                    INSERT INTO patient_phones (patient_id, phone, source)
                    VALUES (%s, %s, 'dietbox_auto')
                    ON CONFLICT (phone) DO NOTHING
                    """,
                    (row["id"], phone),
                )
                conn.commit()
                logger.info("phone %s → patient %s registrado automaticamente", phone, row["id"])
            except Exception as e:
                logger.warning("falha ao registrar phone: %s", e)
        return row


# ── AUTO-REGISTER: cria paciente novo automaticamente ─────────────────────────

def _auto_register_patient(conn: psycopg.Connection, phone: str) -> dict:
    """
    Cria um novo paciente automaticamente quando um número desconhecido envia mensagem.
    Trial de 7 dias começa imediatamente.
    """
    now = datetime.now(tz=_tz.utc)
    trial_end = now + timedelta(days=7)
    patient_id = uuid.uuid4()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patients (id, source_system, external_id, display_name, subscription_status,
                                  trial_ends_at, created_at, updated_at, deby_level, deby_xp,
                                  current_streak, longest_streak, league_points)
            VALUES (%s, 'whatsapp_auto', %s, %s, 'trial', %s, %s, %s, 1, 0, 0, 0, 0)
            """,
            (str(patient_id), f"wa_{phone}", f"Paciente {phone[-4:]}", trial_end, now, now),
        )
        cur.execute(
            """
            INSERT INTO patient_phones (patient_id, phone, source, verified)
            VALUES (%s, %s, 'whatsapp_auto', true)
            """,
            (str(patient_id), phone),
        )
        conn.commit()

    logger.info("AUTO-REGISTER: novo paciente %s criado para phone=%s (trial até %s)", patient_id, phone, trial_end)

    return {
        "id": patient_id,
        "display_name": f"Paciente {phone[-4:]}",
        "external_id": None,
        "created_at": now,
        "subscription_status": "trial",
        "trial_ends_at": trial_end,
    }


# ── ONBOARDING PROATIVO ──────────────────────────────────────────────────────

def _get_onboarding_step(conn: psycopg.Connection, patient_id: uuid.UUID) -> int:
    """Retorna o passo atual do onboarding (0 = não iniciado, 5 = completo)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT metadata FROM patients WHERE id = %s",
            (str(patient_id),),
        )
        row = cur.fetchone()
    if not row or not row.get("metadata"):
        return 0
    meta = row["metadata"]
    return meta.get("onboarding_step", 0)


def _save_onboarding_data(conn: psycopg.Connection, patient_id: uuid.UUID, step: int, key: str, value: str) -> None:
    """Salva dados do onboarding no metadata do paciente e avança o passo."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE patients SET
                metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(%s::text, %s::text, 'onboarding_step', %s::int),
                updated_at = NOW()
            WHERE id = %s
            """,
            (key, value, step, str(patient_id)),
        )
        # Se step 1 (nome), atualizar display_name
        if key == "nome_completo":
            cur.execute(
                "UPDATE patients SET display_name = %s WHERE id = %s",
                (value, str(patient_id)),
            )
        # Se step 3 (objetivo), salva na coluna goal_statement
        if key == "objetivo":
            cur.execute(
                "UPDATE patients SET goal_statement = %s, goal_collected_at = NOW(), goal_source = 'whatsapp' WHERE id = %s",
                (value, str(patient_id)),
            )
        conn.commit()


ONBOARDING_QUESTIONS = [
    # step 0 → pergunta para step 1
    (
        "nome_completo",
        "Olá! 😊 Eu sou a Deby, sua nutricionista inteligente! "
        "Vou montar seu prontuário personalizado agora. "
        "Para começar, qual é o seu nome completo?"
    ),
    # step 1 → pergunta para step 2
    (
        "idade",
        "{nome}, prazer em te conhecer! 💚 Qual a sua idade?"
    ),
    # step 2 → pergunta para step 3
    (
        "peso_altura",
        "Ótimo! Agora me diz: qual seu peso (kg) e altura (cm)? "
        "Pode mandar assim: '75kg 1,72m'"
    ),
    # step 3 → pergunta para step 4
    (
        "objetivo",
        "Perfeito! E qual é seu principal objetivo? "
        "(ex: emagrecer, ganhar massa muscular, saúde geral, controlar diabetes...)"
    ),
    # step 4 → pergunta para step 5
    (
        "restricoes",
        "Última pergunta! Tem alguma restrição alimentar ou alergia? "
        "(ex: lactose, glúten, vegano, nenhuma)"
    ),
]

ONBOARDING_COMPLETE_MSG = (
    "Pronto, {nome}! 🎉 Seu prontuário está aberto e personalizado! "
    "Agora você tem 7 dias de acesso TOTAL à sua nutricionista IA. "
    "Pode me mandar:\n"
    "📸 Foto de exame → analiso seus marcadores\n"
    "📸 Foto de prato → calculo calorias e macros\n"
    "🎤 Áudio → transcrevo e salvo no seu prontuário\n"
    "💬 Perguntas sobre nutrição → respondo na hora!\n\n"
    "Baixe o app para ver tudo organizado: https://app.nutrideby.com.br 💚"
)


def _handle_onboarding(conn: psycopg.Connection, patient_id: uuid.UUID, body: str, phone: str, settings: Any) -> str | None:
    """
    Gerencia o fluxo de onboarding proativo.
    Retorna a resposta se estiver em onboarding, ou None se já completou.
    """
    step = _get_onboarding_step(conn, patient_id)

    if step >= len(ONBOARDING_QUESTIONS):
        return None  # Onboarding completo, segue fluxo normal

    # Step 0: primeira vez que o paciente interage — mostra boas-vindas
    if step == 0:
        # Se body tem conteúdo e NÃO é a primeira msg (já viu boas-vindas antes)
        # Verifica se já enviamos a pergunta antes (checando inbound_messages)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM inbound_messages WHERE patient_id = %s",
                (str(patient_id),),
            )
            row = cur.fetchone()
            msg_count = int(row["count"]) if row else 0

        if msg_count > 0 and body.strip():
            # Paciente está respondendo à pergunta do nome (step 0)
            _save_onboarding_data(conn, patient_id, 1, "nome_completo", body.strip())
            # Avança para step 1 → pergunta idade
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT display_name FROM patients WHERE id = %s", (str(patient_id),))
                row = cur.fetchone()
            nome = (row["display_name"] if row else "").split()[0] or "você"
            return ONBOARDING_QUESTIONS[1][1].format(nome=nome)
        else:
            # Primeira mensagem: mostra boas-vindas + pergunta nome
            return ONBOARDING_QUESTIONS[0][1]

    # Steps 1-4: paciente está respondendo perguntas
    if body.strip():
        # Salva a resposta do step atual
        current_key = ONBOARDING_QUESTIONS[step][0]
        next_step = step + 1
        _save_onboarding_data(conn, patient_id, next_step, current_key, body.strip())

        # Se completou todas as perguntas
        if next_step >= len(ONBOARDING_QUESTIONS):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT display_name FROM patients WHERE id = %s", (str(patient_id),))
                row = cur.fetchone()
            nome = (row["display_name"] if row else "").split()[0] or "você"
            return ONBOARDING_COMPLETE_MSG.format(nome=nome)

        # Envia próxima pergunta
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT display_name FROM patients WHERE id = %s", (str(patient_id),))
            row = cur.fetchone()
        nome = (row["display_name"] if row else "").split()[0] or "você"
        return ONBOARDING_QUESTIONS[next_step][1].format(nome=nome)

    # Body vazio — repete a pergunta atual
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT display_name FROM patients WHERE id = %s", (str(patient_id),))
        row = cur.fetchone()
    nome = (row["display_name"] if row else "").split()[0] or "você"
    return ONBOARDING_QUESTIONS[step][1].format(nome=nome)


# ── TRANSCRIÇÃO DE ÁUDIO ─────────────────────────────────────────────────────

def _transcribe_audio(media_url: str, account_sid: str, auth_token: str, openai_key: str) -> str:
    """
    Baixa áudio do Twilio e transcreve via OpenAI Whisper.
    Retorna o texto transcrito.
    """
    # Download com auth Twilio
    resp = httpx.get(media_url, auth=(account_sid, auth_token), timeout=60, follow_redirects=True)
    resp.raise_for_status()

    # Envia para Whisper API
    files = {"file": ("audio.ogg", resp.content, "audio/ogg")}
    data = {"model": "whisper-1", "language": "pt"}

    r = httpx.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {openai_key}"},
        files=files,
        data=data,
        timeout=60,
    )
    r.raise_for_status()
    text = r.json().get("text", "").strip()
    logger.info("audio transcrito: %d chars", len(text))
    return text


# ── helpers existentes ────────────────────────────────────────────────────────

def _vision_extract(image_url: str, account_sid: str, auth_token: str, openai_key: str) -> str:
    """
    Baixa imagem do Twilio e envia para GPT-4o Vision.
    Retorna texto extraído (valores de exame ou descrição do alimento).
    """
    # Download com auth Twilio
    resp = httpx.get(image_url, auth=(account_sid, auth_token), timeout=30)
    resp.raise_for_status()
    b64 = base64.b64encode(resp.content).decode()
    mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]

    payload = {
        "model": "gpt-4o",
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Você é um assistente médico. Analise esta imagem e extraia:\n"
                            "1. Se for um exame laboratorial: liste TODOS os valores no formato "
                            "'Nome do exame: valor unidade' (ex: 'Glicemia: 98 mg/dL')\n"
                            "2. Se for um alimento/refeição: descreva detalhadamente o que está "
                            "na imagem (alimentos, porções estimadas, método de preparo)\n"
                            "3. Se for outro tipo: descreva o conteúdo relevante para nutrição.\n"
                            "Responda em português. Seja preciso e completo."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                    },
                ],
            }
        ],
    }

    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {openai_key}"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _insert_document(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    content_text: str,
    doc_type: str,
    source_ref: str,
) -> uuid.UUID:
    import hashlib
    sha = hashlib.sha256(content_text.encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (patient_id, doc_type, content_text, content_sha256, source_ref)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (patient_id, doc_type, content_sha256) DO NOTHING
            RETURNING id
            """,
            (patient_id, doc_type, content_text, sha, source_ref),
        )
        row = cur.fetchone()
        if row:
            conn.commit()
            return row["id"]
        # Já existia — busca o id
        cur.execute(
            "SELECT id FROM documents WHERE patient_id=%s AND doc_type=%s AND content_sha256=%s",
            (patient_id, doc_type, sha),
        )
        return cur.fetchone()["id"]


def _auto_chunk_embed(patient_id: uuid.UUID, settings: Any) -> None:
    """Chama os workers de chunk e embed via subprocess (rápido para MVP)."""
    import subprocess
    pid = str(patient_id)
    base = ["python3", "-m"]
    env_args = {"DATABASE_URL": settings.database_url, "OPENAI_API_KEY": settings.openai_api_key or ""}
    import os
    env = {**os.environ, **env_args}
    subprocess.run(
        base + ["nutrideby.workers.chunk_documents", "--patient-id", pid],
        capture_output=True, env=env, cwd="/opt/automa-aoNutriDeby",
    )
    subprocess.run(
        base + ["nutrideby.workers.embed_chunks", "--patient-id", pid, "--limit", "50"],
        capture_output=True, env=env, cwd="/opt/automa-aoNutriDeby",
    )


def _run_analysis(patient_id: uuid.UUID, query: str, settings: Any) -> str:
    """Chama run_patient_analysis e retorna texto da análise."""
    from nutrideby.rag.analyze_patient import run_patient_analysis
    try:
        result = run_patient_analysis(
            patient_id=patient_id,
            query=query,
            settings=settings,
            persona="clinical",
            use_genai=False,
            k=5,
            max_tokens=512,
        )
        return result.get("analysis", "Análise não disponível.")
    except LookupError:
        return "Não encontrei seu histórico clínico ainda. Por favor, aguarde seu cadastro ser atualizado."
    except Exception as e:
        logger.error("analyze error: %s", e)
        return "Desculpe, houve um problema ao processar sua análise. Tente novamente em instantes."


def _send_reply(to_phone: str, body: str, settings: Any) -> None:
    twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    twilio.messages.create(
        from_=settings.twilio_from_number,
        body=body,
        to=f"whatsapp:+{to_phone}",
    )


def _save_inbound(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID | None,
    phone: str,
    message_type: str,
    body: str | None,
    media_url: str | None,
    ocr_text: str | None,
    reply_body: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO inbound_messages
              (patient_id, phone, message_type, body, media_url, ocr_text,
               reply_body, replied_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                patient_id, phone, message_type, body, media_url, ocr_text,
                reply_body, datetime.now() if reply_body else None,
            ),
        )
        conn.commit()


# ── entry point ───────────────────────────────────────────────────────────────


def _check_subscription(conn, patient_id: uuid.UUID) -> str:
    """
    Retorna o status da assinatura:
    - 'trial_full': primeiros 7 dias (acesso ilimitado)
    - 'trial': após 7 dias sem assinar (3 msgs/dia)
    - 'active': assinante Premium
    - 'expired'/'canceled': bloqueado
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT subscription_status, trial_ends_at, created_at FROM patients WHERE id = %s",
            (str(patient_id),),
        )
        row = cur.fetchone()
    if not row:
        return "active"

    status = row["subscription_status"]
    now = datetime.now(tz=_tz.utc)

    if status == "active":
        return "active"

    if status == "trial":
        trial_end = row.get("trial_ends_at")
        if trial_end and now <= trial_end:
            return "trial_full"  # Primeiros 7 dias: acesso total
        else:
            return "trial"  # Após 7 dias: 3 msgs/dia

    return status  # expired, canceled, etc.


def _daily_inbound_count(conn, patient_id) -> int:
    """Conta mensagens WhatsApp recebidas do paciente hoje."""
    from datetime import date
    today = date.today()
    day_start = datetime(today.year, today.month, today.day, tzinfo=_tz.utc)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM inbound_messages WHERE patient_id = %s AND replied_at >= %s",
            (str(patient_id), day_start),
        )
        row = cur.fetchone()
    return int(row["count"]) if row else 0


def _get_or_create_referral_code(conn, patient_id) -> str:
    """Garante que o paciente tem um referral_code e o retorna."""
    import secrets
    with conn.cursor() as cur:
        cur.execute("SELECT referral_code FROM patients WHERE id = %s", (str(patient_id),))
        row = cur.fetchone()
        code = row["referral_code"] if row else None
        if not code:
            code = secrets.token_urlsafe(6).upper()
            cur.execute("UPDATE patients SET referral_code = %s WHERE id = %s", (code, str(patient_id)))
            conn.commit()
    return code


def process_inbound(
    *,
    from_raw: str,
    body: str,
    num_media: int,
    media_url: str | None,
    media_type: str | None,
    settings: Any,
) -> str:
    """
    Processa mensagem inbound completa.
    Regra v3: Deby é PROATIVA — auto-register + onboarding + áudio + trial 7 dias.
    Retorna o texto da resposta enviada ao paciente.
    """
    phone = _normalize_phone(from_raw)
    msg_type = "audio" if (media_type and "audio" in media_type) else (
        "image" if num_media > 0 and media_url else "text"
    )

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        patient = _find_patient(conn, phone) or _find_patient_by_metadata(conn, phone)

        # ── AUTO-REGISTER: número desconhecido → cria paciente + inicia onboarding ──
        if not patient:
            patient = _auto_register_patient(conn, phone)
            # Envia primeira pergunta do onboarding
            reply = _handle_onboarding(conn, uuid.UUID(str(patient["id"])), body, phone, settings)
            if not reply:
                reply = ONBOARDING_QUESTIONS[0][1]
            _save_inbound(
                conn, patient_id=uuid.UUID(str(patient["id"])), phone=phone,
                message_type=msg_type, body=body, media_url=media_url,
                ocr_text=None, reply_body=reply,
            )
            _send_reply(phone, reply, settings)
            return reply

        pid = uuid.UUID(str(patient["id"]))
        nome = (patient.get("display_name") or "").split()[0] or "você"

        # ── ONBOARDING: se ainda não completou, continua o fluxo proativo ─────
        onboarding_reply = _handle_onboarding(conn, pid, body, phone, settings)
        if onboarding_reply:
            _save_inbound(
                conn, patient_id=pid, phone=phone, message_type=msg_type,
                body=body, media_url=media_url, ocr_text=None, reply_body=onboarding_reply,
            )
            _send_reply(phone, onboarding_reply, settings)
            return onboarding_reply

        # ── Reativação: pacientes inativos ────────────────────────────────────
        if patient.get("subscription_status") == "inactive":
            react_stage = patient.get("reactivation_stage")

            # Primeira resposta de um inativo → marca como 'responded'
            if not react_stage:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE patients SET reactivation_stage='responded', updated_at=NOW() WHERE id=%s",
                        (str(pid),),
                    )
                    conn.commit()
                react_stage = "responded"
                logger.info("Paciente respondeu — aguardando agendamento: patient=%s", pid)

            if react_stage in ("responded", "scheduled"):
                # Acesso limitado: apenas chat de texto; imagens/áudio bloqueados
                if msg_type in ("image", "audio"):
                    reply = (
                        f"Oi, {nome}! 💚 Para enviar exames ou áudios, agende sua consulta "
                        "com a Dra. Débora e tenha acesso completo ao NutriDeby."
                    )
                else:
                    from nutrideby.agents.patient_engine import route as _engine_route
                    reply, _ = _engine_route(
                        patient=patient, phone=phone, body=body, msg_type="text",
                        media_url=None, media_type=None, conn=conn, settings=settings,
                        handle_onboarding_fn=None,
                    )
                    cta = (
                        "\n\n📅 *Para acesso completo* (exames, log alimentar, prontuário), "
                        "agende sua consulta com a Dra. Débora."
                    )
                    reply = reply + cta

                _save_inbound(
                    conn, patient_id=pid, phone=phone, message_type=msg_type,
                    body=body, media_url=media_url, ocr_text=None, reply_body=reply,
                )
                _send_reply(phone, reply, settings)
                return reply

            # react_stage == 'reactivated' → subscription_status já foi atualizado
            # para 'active' pelo endpoint confirm-reactivation, então cai no fluxo normal

        # ── Verifica paywall ──────────────────────────────────────────────────
        sub_status = _check_subscription(conn, pid)

        if sub_status in ("expired", "canceled"):
            code = _get_or_create_referral_code(conn, pid)
            base_url = getattr(settings, "app_base_url", None) or "https://app.nutrideby.com.br"
            share_link = f"{base_url}/cadastro?ref={code}"
            reply = (
                f"Oi, {nome}! 💚 Seu período de teste do NutriDeby encerrou. "
                f"Indique um amigo e ganhe +3 dias grátis: {share_link}\n"
                "Ou ative sua assinatura Premium no app NutriDeby!"
            )
            _save_inbound(
                conn, patient_id=pid, phone=phone, message_type=msg_type,
                body=body, media_url=media_url, ocr_text=None, reply_body=reply,
            )
            _send_reply(phone, reply, settings)
            return reply

        # ── Limite de 3 consultas diárias para trial (após 7 dias) ────────────
        if sub_status == "trial":
            daily_count = _daily_inbound_count(conn, pid)
            if daily_count >= 3:
                code = _get_or_create_referral_code(conn, pid)
                base_url = getattr(settings, "app_base_url", None) or "https://app.nutrideby.com.br"
                share_link = f"{base_url}/cadastro?ref={code}"
                reply = (
                    f"Oi, {nome}! 😊 Você atingiu o limite de 3 consultas gratuitas de hoje. "
                    f"Indique um amigo e ganhe +3 dias Premium para os dois! "
                    f"Seu link exclusivo: {share_link}"
                )
                _save_inbound(
                    conn, patient_id=pid, phone=phone, message_type=msg_type,
                    body=body, media_url=media_url, ocr_text=None, reply_body=reply,
                )
                _send_reply(phone, reply, settings)
                return reply

        # ── trial_full ou active: patient_engine router ────────────────────────

        from nutrideby.agents.patient_engine import route as _engine_route

        reply, ocr_text = _engine_route(
            patient=patient,
            phone=phone,
            body=body,
            msg_type=msg_type,
            media_url=media_url,
            media_type=media_type,
            conn=conn,
            settings=settings,
            handle_onboarding_fn=None,  # onboarding já tratado acima
        )

        _save_inbound(
            conn, patient_id=pid, phone=phone, message_type=msg_type,
            body=body, media_url=media_url, ocr_text=ocr_text, reply_body=reply,
        )
        _send_reply(phone, reply, settings)
        logger.info("inbound processado: phone=%s patient=%s type=%s", phone, pid, msg_type)
        return reply

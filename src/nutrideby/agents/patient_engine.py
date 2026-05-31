"""
patient_engine.py — Orquestrador Central NutriDeby

Toda mensagem inbound passa por aqui antes de qualquer resposta.
Substitui a lógica dispersa do inbound_processor.py.

Responsabilidades:
  1. FEEDBACK LOOP    — foto de refeição → Vision → comparar com goal → reforço/correção
  2. MEMORY           — carrega últimas 5 mensagens para contexto contínuo
  3. ALERT ENGINE     — 3+ dias fora do objetivo → notifica nutricionista
  4. AUTO-UPDATE      — novos dados (comida/peso/exame) → atualiza prontuário
  5. DECISION ROUTER  — onboarding | foto | áudio | texto → rota correta

Ponto de entrada: route(...)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone as _tz
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Número da nutricionista para alertas (configurável via env)
import os
_NUTRI_NOTIFY_RAW = os.getenv(
    "NUTRI_NOTIFY_PHONE",
    os.getenv("TWILIO_TEST_NUMBER", ""),
).replace("whatsapp:", "").replace("+", "").strip()


# ── 1. CONVERSATION MEMORY ────────────────────────────────────────────────────

def _load_memory(conn: psycopg.Connection, patient_id: uuid.UUID, n: int = 5) -> list[dict]:
    """
    Carrega as últimas n mensagens do paciente (corpo + resposta).
    Retorna lista [{role, content}] no formato de histórico de chat.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT body, reply_body, message_type, received_at
            FROM inbound_messages
            WHERE patient_id = %s
              AND received_at >= NOW() - INTERVAL '7 days'
            ORDER BY received_at DESC
            LIMIT %s
            """,
            (str(patient_id), n),
        )
        rows = cur.fetchall()

    history = []
    for r in reversed(rows):
        if r["body"]:
            history.append({"role": "user", "content": r["body"]})
        if r["reply_body"]:
            history.append({"role": "assistant", "content": r["reply_body"]})
    return history


def _memory_as_text(history: list[dict]) -> str:
    """Formata histórico como bloco de texto para injetar no prompt RAG."""
    if not history:
        return ""
    lines = []
    for msg in history:
        prefix = "Paciente" if msg["role"] == "user" else "Deby"
        lines.append(f"{prefix}: {msg['content'][:200]}")
    return "Histórico recente:\n" + "\n".join(lines)


# ── 2. ALERT ENGINE ───────────────────────────────────────────────────────────

def _days_without_log(conn: psycopg.Connection, patient_id: uuid.UUID) -> int:
    """Quantos dias desde o último food_log ou last_logged_date."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT last_logged_date FROM patients WHERE id = %s",
            (str(patient_id),),
        )
        row = cur.fetchone()
    if not row or not row["last_logged_date"]:
        return 999
    delta = date.today() - row["last_logged_date"]
    return delta.days


def _patient_summary(conn: psycopg.Connection, patient_id: uuid.UUID) -> str:
    """Resumo compacto do paciente para notificação à nutricionista."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT display_name, goal_statement, current_streak,
                   last_logged_date, subscription_status,
                   metadata->>'MobilePhone' AS meta_phone
            FROM patients WHERE id = %s
            """,
            (str(patient_id),),
        )
        p = cur.fetchone()
    if not p:
        return f"Paciente {patient_id}"

    nome    = p["display_name"] or "Desconhecido"
    goal    = (p["goal_statement"] or "sem objetivo definido")[:80]
    streak  = p["current_streak"] or 0
    ultimo  = str(p["last_logged_date"]) if p["last_logged_date"] else "nunca"
    status  = p["subscription_status"] or "?"
    dias    = _days_without_log(conn, patient_id)

    return (
        f"👤 {nome}\n"
        f"🎯 Objetivo: {goal}\n"
        f"📅 Último registro: {ultimo} ({dias}d atrás)\n"
        f"🔥 Streak atual: {streak} dias\n"
        f"📱 Status: {status}"
    )


def _already_alerted_today(conn: psycopg.Connection, patient_id: uuid.UUID) -> bool:
    """Evita enviar o mesmo alerta várias vezes no mesmo dia."""
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=_tz.utc)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 1 FROM inbound_messages
            WHERE patient_id = %s
              AND reply_body LIKE '%%ALERTA DEBY%%'
              AND received_at >= %s
            LIMIT 1
            """,
            (str(patient_id), today_start),
        )
        return cur.fetchone() is not None


def check_and_send_alert(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    settings: Any,
    threshold_days: int = 3,
) -> bool:
    """
    Se paciente tem goal e está há threshold_days+ dias sem log → alerta nutricionista.
    Retorna True se alerta foi enviado.
    """
    # Só alerta se paciente tem objetivo definido
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT goal_statement FROM patients WHERE id = %s",
            (str(patient_id),),
        )
        row = cur.fetchone()
    if not row or not row["goal_statement"]:
        return False

    dias = _days_without_log(conn, patient_id)
    if dias < threshold_days:
        return False

    if _already_alerted_today(conn, patient_id):
        return False

    if not _NUTRI_NOTIFY_RAW:
        logger.warning("alert: NUTRI_NOTIFY_PHONE não configurado — pulando alerta")
        return False

    summary = _patient_summary(conn, patient_id)
    msg = (
        f"⚠️ ALERTA DEBY — Paciente inativo\n\n"
        f"{summary}\n\n"
        f"Este paciente está {dias} dias sem registrar refeições. "
        f"Recomendo mensagem de reengajamento hoje."
    )

    try:
        from twilio.rest import Client as TwilioClient
        twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
        twilio.messages.create(
            from_=settings.twilio_from_number,
            body=msg,
            to=f"whatsapp:+{_NUTRI_NOTIFY_RAW}",
        )
        logger.info("alert: notificação enviada para nutricionista — patient=%s dias=%d", patient_id, dias)

        # Marca o alerta com tag especial no log
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inbound_messages (patient_id, phone, message_type, reply_body, replied_at)
                VALUES (%s, %s, 'system_alert', %s, NOW())
                """,
                (str(patient_id), _NUTRI_NOTIFY_RAW, f"ALERTA DEBY: {dias}d inativo"),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("alert: falha ao notificar nutricionista: %s", exc)
        return False


# ── 3. FEEDBACK LOOP (foto de refeição) ──────────────────────────────────────

def _classify_meal_alignment(
    food_description: str,
    goal_statement: str,
    memory_text: str,
    openai_key: str,
    model: str = "gpt-4o-mini",
) -> dict:
    """
    Usa LLM para determinar se a refeição está alinhada com o objetivo.
    Retorna {aligned: bool, feedback: str, alert_level: str, nutrients: dict}
    """
    system = (
        "Você é uma nutricionista clínica especializada em análise comportamental alimentar. "
        "Analise se a refeição descrita está alinhada com o objetivo do paciente. "
        "Responda APENAS com JSON válido, sem markdown."
    )

    prompt = (
        f"Objetivo do paciente: {goal_statement}\n\n"
        f"Refeição detectada: {food_description}\n\n"
        f"{memory_text}\n\n"
        "Retorne JSON com:\n"
        '{"aligned": true/false, '
        '"feedback": "mensagem curta e acolhedora (max 80 palavras)", '
        '"alert_level": "ok|warning|critical", '
        '"estimated_calories": número_inteiro, '
        '"proteins_g": número, "carbs_g": número, "fat_g": número, '
        '"foods_detected": ["alimento1", "alimento2"]}'
    )

    try:
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {openai_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens": 300,
                "temperature": 0.3,
            },
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        # Remove markdown code fences se presentes
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        logger.warning("meal classification failed: %s", exc)
        return {
            "aligned": True,
            "feedback": "Registrei sua refeição! Continue assim 💚",
            "alert_level": "ok",
            "estimated_calories": 0,
            "proteins_g": 0,
            "carbs_g": 0,
            "fat_g": 0,
            "foods_detected": [],
        }


def _save_food_log(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    food_description: str,
    classification: dict,
    photo_url: str | None,
) -> uuid.UUID:
    """Insere registro em food_logs e retorna o id."""
    foods_json = json.dumps(
        [{"name": f} for f in (classification.get("foods_detected") or [])],
        ensure_ascii=False,
    )
    meal_type = _infer_meal_type()
    log_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO food_logs
              (id, patient_id, meal_type, photo_url, source, foods,
               total_calories, total_protein, total_carbs, total_fat)
            VALUES (%s, %s, %s, %s, 'whatsapp', %s::jsonb, %s, %s, %s, %s)
            """,
            (
                str(log_id), str(patient_id), meal_type, photo_url,
                foods_json,
                float(classification.get("estimated_calories") or 0),
                float(classification.get("proteins_g") or 0),
                float(classification.get("carbs_g") or 0),
                float(classification.get("fat_g") or 0),
            ),
        )
        # Atualiza last_logged_date e streak
        cur.execute(
            """
            UPDATE patients SET
                last_logged_date = CURRENT_DATE,
                current_streak = CASE
                    WHEN last_logged_date = CURRENT_DATE - 1 THEN current_streak + 1
                    WHEN last_logged_date = CURRENT_DATE THEN current_streak
                    ELSE 1
                END,
                longest_streak = GREATEST(
                    longest_streak,
                    CASE
                        WHEN last_logged_date = CURRENT_DATE - 1 THEN current_streak + 1
                        ELSE 1
                    END
                ),
                updated_at = NOW()
            WHERE id = %s
            """,
            (str(patient_id),),
        )
        conn.commit()
    logger.info("food_log salvo: patient=%s calories=%.0f alert=%s",
                patient_id, classification.get("estimated_calories", 0),
                classification.get("alert_level"))
    return log_id


def _infer_meal_type() -> str:
    """Infere tipo de refeição pelo horário."""
    hora = datetime.now().hour
    if hora < 10:
        return "cafe_manha"
    if hora < 12:
        return "lanche_manha"
    if hora < 15:
        return "almoco"
    if hora < 18:
        return "lanche_tarde"
    if hora < 22:
        return "jantar"
    return "ceia"


# ── 4. PRONTUÁRIO AUTO-UPDATE ─────────────────────────────────────────────────

def _update_prontuario(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    content: str,
    doc_type: str,
    source: str,
    changed_fields: dict | None = None,
) -> None:
    """
    Insere/atualiza documento no prontuário e loga o que mudou.
    doc_type: food_log | lab_report | clinical_note | weight_log | alert_log
    """
    import hashlib
    sha = hashlib.sha256(content.encode()).hexdigest()
    changelog = json.dumps(changed_fields or {}, ensure_ascii=False)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents
              (patient_id, doc_type, content_text, content_sha256, source_ref)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (patient_id, doc_type, content_sha256) DO NOTHING
            """,
            (str(patient_id), doc_type, content, sha, source),
        )
        conn.commit()

    if changed_fields:
        logger.info(
            "prontuario updated: patient=%s doc_type=%s changes=%s",
            patient_id, doc_type, changelog,
        )


# ── 5. DECISION ROUTER ────────────────────────────────────────────────────────

def _get_patient_goal(conn: psycopg.Connection, patient_id: uuid.UUID) -> str | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT goal_statement FROM patients WHERE id = %s",
            (str(patient_id),),
        )
        row = cur.fetchone()
    return (row or {}).get("goal_statement")


def _handle_image_feedback(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    nome: str,
    media_url: str,
    goal_statement: str | None,
    memory: list[dict],
    settings: Any,
) -> tuple[str, str | None]:
    """
    Feedback loop completo para foto de refeição.
    Retorna (reply_text, ocr_text).
    """
    import base64

    # Download + Vision
    try:
        resp = httpx.get(
            media_url,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        b64  = base64.b64encode(resp.content).decode()
        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    except Exception as exc:
        logger.error("image download error: %s", exc)
        return (
            f"Recebi sua foto, {nome}! 📸 Estou processando — já atualizo seu painel!",
            None,
        )

    # Detecta tipo: exame ou refeição
    detect_prompt = (
        "Analise esta imagem. Responda APENAS com JSON: "
        '{"type": "meal" ou "lab_exam" ou "other", '
        '"description": "descrição detalhada em português"}'
    )
    try:
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": "gpt-4o",
                "max_tokens": 512,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": detect_prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                    ],
                }],
            },
            timeout=60,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        vision_result = json.loads(raw)
    except Exception as exc:
        logger.warning("vision detect failed: %s — fallback to meal", exc)
        vision_result = {"type": "meal", "description": "Refeição detectada (detalhe indisponível)"}

    img_type    = vision_result.get("type", "meal")
    description = vision_result.get("description", "")

    # ── Exame laboratorial ────────────────────────────────────────────────────
    if img_type == "lab_exam":
        _update_prontuario(
            conn, patient_id, description, "lab_report",
            source=f"whatsapp_image:{datetime.now().date()}",
            changed_fields={"source": "foto_whatsapp", "type": "lab_exam"},
        )
        return (
            f"{nome}, analisei seu exame! 🔬 Já salvei todos os valores no seu prontuário. "
            "Confira no app NutriDeby para ver o que ficou fora da referência! 💚",
            description,
        )

    # ── Foto de refeição → FEEDBACK LOOP ─────────────────────────────────────
    memory_text = _memory_as_text(memory)

    if goal_statement:
        classification = _classify_meal_alignment(
            food_description=description,
            goal_statement=goal_statement,
            memory_text=memory_text,
            openai_key=settings.openai_api_key or "",
            model=getattr(settings, "openai_chat_model", "gpt-4o-mini"),
        )
    else:
        # Sem objetivo definido: só registra sem julgamento
        classification = {
            "aligned": True,
            "feedback": f"Registrei sua refeição, {nome}! 🥗",
            "alert_level": "ok",
            "estimated_calories": 0,
            "proteins_g": 0, "carbs_g": 0, "fat_g": 0,
            "foods_detected": [],
        }

    # Salva food_log
    _save_food_log(conn, patient_id, description, classification, photo_url=media_url)

    # Atualiza prontuário com o log da refeição
    changed = {
        "meal_type": _infer_meal_type(),
        "alignment": "aligned" if classification["aligned"] else "misaligned",
        "alert_level": classification.get("alert_level", "ok"),
        "calories": classification.get("estimated_calories", 0),
    }
    _update_prontuario(
        conn, patient_id, description, "food_log",
        source=f"whatsapp_photo:{datetime.now().date()}",
        changed_fields=changed,
    )

    # Salva alerta no prontuário se desalinhado
    if not classification["aligned"]:
        alert_text = (
            f"[ALERTA] Refeição desalinhada em {datetime.now().date()} — "
            f"{description[:200]} — Objetivo: {goal_statement[:100]}"
        )
        _update_prontuario(
            conn, patient_id, alert_text, "alert_log",
            source="feedback_loop",
            changed_fields={"trigger": "meal_misalignment"},
        )

    feedback  = classification.get("feedback", "")
    kcal      = int(classification.get("estimated_calories") or 0)
    ptn       = classification.get("proteins_g") or 0
    alert_lvl = classification.get("alert_level", "ok")

    kcal_line = f"\n📊 ~{kcal} kcal | {ptn:.0f}g proteína" if kcal > 0 else ""
    emoji     = "✅" if classification["aligned"] else ("⚠️" if alert_lvl == "warning" else "🔴")

    reply = f"{emoji} {feedback}{kcal_line}\n\nVeja sua evolução no app NutriDeby! 💚"
    return reply, description


def _handle_text_goal_aware(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    nome: str,
    body: str,
    goal_statement: str | None,
    memory: list[dict],
    settings: Any,
) -> str:
    """Resposta textual com consciência do objetivo e memória de conversa."""
    from nutrideby.rag.analyze_patient import run_patient_analysis

    memory_text = _memory_as_text(memory)
    goal_ctx    = f"Objetivo do paciente: {goal_statement}" if goal_statement else ""

    query = (
        f"{memory_text}\n\n"
        f"{goal_ctx}\n\n"
        f"Mensagem atual do paciente: '{body}'\n\n"
        "Responda em português, máximo 3 frases, tom acolhedor e personalizado. "
        "Se relevante, conecte ao objetivo do paciente."
    )

    try:
        result = run_patient_analysis(
            patient_id=patient_id,
            query=query,
            settings=settings,
            persona="clinical",
            use_genai=False,
            k=5,
            max_tokens=400,
        )
        analysis = result.get("analysis", "")
        if len(analysis) > 450:
            analysis = analysis[:440] + "…"
        return f"{analysis}\n\nAcesse o app NutriDeby para mais detalhes! 💚"
    except Exception as exc:
        logger.warning("rag analysis failed: %s", exc)
        return (
            f"Oi, {nome}! 😊 Recebi sua mensagem. "
            "Confira seu painel completo no app NutriDeby! 💚"
        )


# ── Entry Point ───────────────────────────────────────────────────────────────

def route(
    *,
    patient: dict,
    phone: str,
    body: str,
    msg_type: str,          # "text" | "image" | "audio"
    media_url: str | None,
    media_type: str | None,
    conn: psycopg.Connection,
    settings: Any,
    # Passados pelo inbound_processor para evitar duplicação
    handle_onboarding_fn: Any = None,
    onboarding_questions: list | None = None,
) -> tuple[str, str | None]:
    """
    Roteador central. Retorna (reply_text, ocr_text).

    Ordem de decisão:
      1. Onboarding incompleto → delega ao handler existente
      2. Alerta de inatividade (background, não bloqueia resposta)
      3. Áudio → transcrição + prontuário
      4. Imagem → Vision + feedback loop
      5. Texto → RAG + goal-aware
    """
    pid  = uuid.UUID(str(patient["id"]))
    nome = (patient.get("display_name") or "").split()[0] or "você"

    # ── 1. Onboarding: delega ao handler do inbound_processor (evita duplicar) ──
    if handle_onboarding_fn is not None:
        onb_reply = handle_onboarding_fn(conn, pid, body, phone, settings)
        if onb_reply:
            return onb_reply, None

    # ── 2. Alert Engine (assíncrono — não bloqueia) ───────────────────────────
    try:
        check_and_send_alert(conn, pid, settings, threshold_days=3)
    except Exception as exc:
        logger.warning("alert engine error (ignorado): %s", exc)

    # Carrega memória e objetivo
    memory         = _load_memory(conn, pid, n=5)
    goal_statement = _get_patient_goal(conn, pid)

    # ── 3. Áudio ──────────────────────────────────────────────────────────────
    if msg_type == "audio" and media_url:
        from nutrideby.agents.inbound_processor import _transcribe_audio
        try:
            transcription = _transcribe_audio(
                media_url,
                settings.twilio_account_sid,
                settings.twilio_auth_token,
                settings.openai_api_key or "",
            )
            _update_prontuario(
                conn, pid, transcription, "clinical_note",
                source=f"whatsapp_audio:{phone}:{datetime.now().date()}",
                changed_fields={"source": "audio_whatsapp", "chars": len(transcription)},
            )
            reply = (
                f"{nome}, recebi seu áudio! 🎤 Já transcrevi e salvei no seu prontuário. "
                "Confira tudo no app NutriDeby! 💚"
            )
            return reply, transcription
        except Exception as exc:
            logger.error("audio error: %s", exc)
            return (
                f"Recebi seu áudio, {nome}! 🎤 Estou processando — já atualizo seu prontuário!",
                None,
            )

    # ── 4. Imagem → Vision + Feedback Loop ───────────────────────────────────
    if msg_type == "image" and media_url:
        return _handle_image_feedback(
            conn=conn,
            patient_id=pid,
            nome=nome,
            media_url=media_url,
            goal_statement=goal_statement,
            memory=memory,
            settings=settings,
        )

    # ── 5. Texto → RAG + goal-aware ───────────────────────────────────────────
    if body and body.strip():
        reply = _handle_text_goal_aware(
            conn=conn,
            patient_id=pid,
            nome=nome,
            body=body,
            goal_statement=goal_statement,
            memory=memory,
            settings=settings,
        )
        return reply, None

    # Fallback
    return f"Oi, {nome}! Como posso ajudar? 💚", None

"""
Máquina de estados da sabatina de sintomas (MSQ ultra-curto) via WhatsApp.

Espelha o padrão de ``_handle_onboarding`` (estado em ``patients.metadata``):
  - dispara por palavra-chave curta ("sintomas", "sabatina", "triagem") OU continua
    uma sabatina já em andamento;
  - pergunta 1 sintoma por mensagem, nota 0-4;
  - ao terminar: grava documento + embed (entra no pgvector), persiste os scores
    estruturados (``patient_symptom_surveys``) e roda ``run_patient_analysis`` para
    cruzar sintomas × exames/prontuário e devolver conduta.

Sem import de ``inbound_processor`` (evita ciclo); reusa apenas o módulo RAG.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from nutrideby.sabatina import msq

logger = logging.getLogger(__name__)

_TRIGGER_WORDS = ("sabatina", "triagem", "sintomas", "rastreio")
_CANCEL_WORDS = {"sair", "parar", "cancelar", "cancela", "stop", "encerrar"}
_NUM_RE = re.compile(r"([0-4])")

INTRO = (
    "Vamos fazer uma *triagem rápida de sintomas* 💚\n"
    f"São {len(msq.ITEMS)} perguntas curtas, cada uma de 0 a 4.\n"
    f"{msq.SCALE_HELP}\n"
    "(digite *sair* a qualquer momento para cancelar)"
)

CORRELATION_QUERY = (
    "Com base na SABATINA DE SINTOMAS do paciente e nos exames/prontuário disponíveis nos trechos: "
    "1) liste a grade de sintomas por sistema com os scores; "
    "2) destaque os sistemas de maior pontuação e relacione com achados laboratoriais ou do "
    "prontuário quando existirem nos trechos; "
    "3) finalize com uma sugestão de conduta nutricional prática e segura. "
    "Use apenas dados presentes nos trechos; se não houver exame correlacionável, declare isso."
)


# ── gatilho / estado ──────────────────────────────────────────────────────────

def sabatina_triggered(body: str | None) -> bool:
    """True se a mensagem é um comando curto pedindo a sabatina (evita falso positivo)."""
    if not body:
        return False
    t = body.strip().lower()
    return len(t) <= 25 and any(w in t for w in _TRIGGER_WORDS)


def _load_state(conn: psycopg.Connection, patient_id: uuid.UUID) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT metadata FROM patients WHERE id = %s", (str(patient_id),))
        row = cur.fetchone()
    meta = (row or {}).get("metadata") or {}
    return meta.get("sabatina") or {}


def sabatina_in_progress(conn: psycopg.Connection, patient_id: uuid.UUID) -> bool:
    return bool(_load_state(conn, patient_id).get("active"))


def _save_state(conn: psycopg.Connection, patient_id: uuid.UUID, state: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE patients SET
              metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('sabatina', %s::jsonb),
              updated_at = NOW()
            WHERE id = %s
            """,
            (Json(state), str(patient_id)),
        )
        conn.commit()


def _question(idx: int) -> str:
    it = msq.ITEMS[idx]
    return (
        f"*{idx + 1}/{len(msq.ITEMS)}* — Nos últimos 30 dias, com que intensidade você teve:\n"
        f"_{it['label']}_ ({it['system']})\n\n"
        f"Responda *0 a 4*:\n{msq.SCALE_HELP}"
    )


def _parse_score(body: str | None) -> int | None:
    if not body:
        return None
    m = _NUM_RE.search(body)
    return int(m.group(1)) if m else None


# ── entry point ────────────────────────────────────────────────────────────────

def handle_sabatina(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    body: str | None,
    phone: str,
    settings: Any,
) -> str | None:
    """
    Retorna o texto da resposta se a sabatina deve responder esta mensagem,
    ou ``None`` se não é a vez dela (segue o fluxo normal do inbound).
    """
    state = _load_state(conn, patient_id)

    if not state.get("active"):
        if not sabatina_triggered(body):
            return None
        state = {"active": True, "idx": 0, "scores": []}
        _save_state(conn, patient_id, state)
        return INTRO + "\n\n" + _question(0)

    # Em andamento: permite cancelar.
    if body and body.strip().lower() in _CANCEL_WORDS:
        _save_state(conn, patient_id, {"active": False, "idx": int(state.get("idx", 0)),
                                       "scores": list(state.get("scores", []))})
        return "Triagem cancelada 👍 Quando quiser refazer, é só mandar *sintomas*."

    idx = int(state.get("idx", 0))
    scores = list(state.get("scores", []))

    val = _parse_score(body)
    if val is None:
        return "Por favor, responda com um número de *0 a 4* 🙂\n\n" + _question(idx)

    scores.append(val)
    idx += 1

    if idx < len(msq.ITEMS):
        _save_state(conn, patient_id, {"active": True, "idx": idx, "scores": scores})
        return _question(idx)

    # Completou — encerra e finaliza.
    _save_state(conn, patient_id, {"active": False, "idx": idx, "scores": scores})
    return _finalize(conn, patient_id, scores, settings)


# ── finalização: documento + embed + persistência + correlação RAG ──────────────

def _finalize(conn: psycopg.Connection, patient_id: uuid.UUID, scores: list[int], settings: Any) -> str:
    survey_text = msq.render_survey_text(scores)
    summary = msq.render_summary_whatsapp(scores)

    doc_id: uuid.UUID | None = None
    try:
        doc_id = _insert_document(conn, patient_id, survey_text, "symptom_survey", "whatsapp_sabatina")
        _chunk_embed(patient_id, settings)
    except Exception:
        logger.exception("sabatina: falha ao gravar/embed documento")

    try:
        _persist_survey(conn, patient_id, scores, doc_id)
    except Exception:
        logger.exception("sabatina: falha ao persistir patient_symptom_surveys")

    analysis = _run_correlation(patient_id, settings)

    parts = [summary]
    if analysis:
        parts.append("\n🩺 *Análise da Deby:*\n" + analysis)
    parts.append(
        "\n_Triagem educativa de apoio — não substitui a avaliação da sua nutricionista._"
    )
    return "\n".join(parts)[:3500]


def _insert_document(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    content_text: str,
    doc_type: str,
    source_ref: str,
) -> uuid.UUID | None:
    sha = hashlib.sha256(content_text.encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (patient_id, doc_type, content_text, content_sha256, source_ref)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (patient_id, doc_type, content_sha256) DO NOTHING
            RETURNING id
            """,
            (str(patient_id), doc_type, content_text, sha, source_ref),
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            return row["id"]
        cur.execute(
            "SELECT id FROM documents WHERE patient_id=%s AND doc_type=%s AND content_sha256=%s",
            (str(patient_id), doc_type, sha),
        )
        r = cur.fetchone()
        return r["id"] if r else None


def _chunk_embed(patient_id: uuid.UUID, settings: Any) -> None:
    """Chunk + embed do paciente via workers (mesmo caminho do inbound)."""
    pid = str(patient_id)
    env = {
        **os.environ,
        "DATABASE_URL": settings.database_url,
        "OPENAI_API_KEY": settings.openai_api_key or "",
    }
    for mod in (
        ["nutrideby.workers.chunk_documents", "--patient-id", pid],
        ["nutrideby.workers.embed_chunks", "--patient-id", pid, "--limit", "50"],
    ):
        subprocess.run(["python3", "-m", *mod], capture_output=True, env=env)


def _persist_survey(
    conn: psycopg.Connection,
    patient_id: uuid.UUID,
    scores: list[int],
    doc_id: uuid.UUID | None,
) -> None:
    by_sys = msq.score_by_system(scores)
    total = msq.total_score(scores)
    items = [
        {"key": it["key"], "system": it["system"], "label": it["label"], "score": int(v)}
        for it, v in zip(msq.ITEMS, scores)
    ]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patient_symptom_surveys
              (patient_id, instrument, total_score, max_score, burden_level,
               system_scores, items, document_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(patient_id), "msq_ultra_curto", total, msq.MAX_TOTAL,
                msq.burden_level(total), Json(by_sys), Json(items),
                str(doc_id) if doc_id else None,
            ),
        )
        conn.commit()


def _run_correlation(patient_id: uuid.UUID, settings: Any) -> str:
    try:
        from nutrideby.rag.analyze_patient import run_patient_analysis

        res = run_patient_analysis(
            patient_id=patient_id,
            query=CORRELATION_QUERY,
            settings=settings,
            persona="motor",
            use_genai=False,
            k=6,
            max_tokens=700,
        )
        return (res.get("analysis") or "").strip()
    except LookupError:
        return ""
    except Exception:
        logger.exception("sabatina: falha na análise de correlação")
        return ""

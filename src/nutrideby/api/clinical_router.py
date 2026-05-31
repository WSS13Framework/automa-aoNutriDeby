"""
clinical_router.py — Módulo WSS13: Exames Bioquímicos + Assinatura Digital + PDF
Rotas:
  POST /api/clinical/upload-exam/{patient_id}  → Paciente envia exame (PDF/Foto)
  POST /api/clinical/sign-record/{record_id}   → Nutricionista assina o plano
  GET  /api/clinical/records/{patient_id}      → Lista prontuários do paciente
  GET  /api/clinical/verify/{token}            → Verifica autenticidade do PDF
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from psycopg.rows import dict_row
from pydantic import BaseModel

from nutrideby.api.deps import get_settings
from nutrideby.clients.openai_chat import chat_completion, assistant_content_from_chat
from nutrideby.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clinical", tags=["clinical-wss13"])

_BIOMARKERS = (
    "Glicose, Colesterol Total, HDL, LDL, Triglicerídeos, "
    "Vitamina D, Ferro Sérico, Ferritina, TSH, T3, T4"
)

_OCR_SYSTEM = (
    "Você é um extrator de dados laboratoriais médico-nutricionais. "
    "Extraia apenas os valores dos seguintes marcadores bioquímicos se existirem: "
    f"{_BIOMARKERS}. "
    "Retorne EXCLUSIVAMENTE um objeto JSON com as chaves em snake_case e valores numéricos. "
    "Exemplo: {{\"glicose\": 95, \"hdl\": 45}}. "
    "NUNCA extraia nome do paciente, nome do médico, CRM ou dados do laboratório (LGPD). "
    "Se não encontrar nenhum marcador, retorne {{}}."
)

_PLAN_SYSTEM = (
    "Você é a Deby, nutricionista funcional IA do NutriDeby. "
    "Com base nos dados bioquímicos fornecidos, crie um plano alimentar funcional "
    "personalizado e detalhado para o dia. Retorne EXCLUSIVAMENTE um objeto JSON com as chaves: "
    "cafe_da_manha, lanche_manha, almoco, lanche_tarde, jantar, ceia. "
    "Cada valor deve ser uma string descritiva com foco funcional e anti-inflamatório. "
    "Responda em português brasileiro."
)


class SignRecordRequest(BaseModel):
    nutricionista_id: int


def _extract_json_from_text(text: str) -> dict:
    """Extrai JSON de uma resposta que pode conter texto extra."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return {}
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return {}


def _call_vision_ocr(file_bytes: bytes, content_type: str, settings: Settings) -> dict:
    """Chama GPT-4o Vision para extrair biomarcadores do exame."""
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY não configurada — usando dados de fallback")
        return {}

    # Detecta mime type para o data URL
    mime = content_type if content_type in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"
    if "pdf" in (content_type or ""):
        # PDF: não suportado diretamente pela Vision API, retorna vazio
        logger.info("PDF recebido — OCR via Vision não suportado nativamente, retornando vazio")
        return {}

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    messages = [
        {"role": "system", "content": _OCR_SYSTEM},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": "high"},
                }
            ],
        },
    ]

    try:
        _, raw = chat_completion(
            api_base=settings.openai_api_base,
            api_key=settings.openai_api_key,
            model="gpt-4o",
            messages=messages,
            max_tokens=512,
            timeout=60,
        )
        text = assistant_content_from_chat(raw)
        return _extract_json_from_text(text)
    except Exception as exc:
        logger.error("Vision OCR falhou: %s", exc)
        return {}


def _call_meal_plan(biochemistry: dict, settings: Settings) -> dict:
    """Gera plano alimentar funcional baseado nos biomarcadores extraídos."""
    if not settings.openai_api_key:
        return _fallback_meal_plan()

    bio_text = json.dumps(biochemistry, ensure_ascii=False) if biochemistry else "Nenhum marcador disponível"

    messages = [
        {"role": "system", "content": _PLAN_SYSTEM},
        {
            "role": "user",
            "content": f"Dados bioquímicos do paciente: {bio_text}",
        },
    ]

    try:
        _, raw = chat_completion(
            api_base=settings.openai_api_base,
            api_key=settings.openai_api_key,
            model=settings.openai_chat_model,
            messages=messages,
            max_tokens=1024,
            timeout=60,
        )
        text = assistant_content_from_chat(raw)
        plan = _normalize_meal_plan(_extract_json_from_text(text))
        return plan if plan else _fallback_meal_plan()
    except Exception as exc:
        logger.error("Geração de plano alimentar falhou: %s", exc)
        return _fallback_meal_plan()


def _fallback_meal_plan() -> dict:
    return {
        "cafe_da_manha": "Suco verde com gengibre e cúrcuma + Ovos mexidos com semente de linhaça",
        "lanche_manha": "Frutas vermelhas com iogurte natural integral",
        "almoco": "Filé de peixe grelhado + Arroz de brócolis + Salada de folhas com abacate",
        "lanche_tarde": "Mix de castanhas e amêndoas + Chá verde",
        "jantar": "Sopa creme de abóbora com sementes de abóbora e gengibre",
        "ceia": "Chá de camomila com erva-cidreira",
    }


_MEAL_KEY_ALIASES: dict[str, str] = {
    # variações que o GPT costuma inventar → chave canônica
    "cafe_manha": "cafe_da_manha",
    "cafe": "cafe_da_manha",
    "lanche_maquina": "lanche_manha",
    "lanche_da_manha": "lanche_manha",
    "lanche_matinal": "lanche_manha",
    "lanche_da_tarde": "lanche_tarde",
    "lanche_vespertino": "lanche_tarde",
    "almoço": "almoco",
    "janta": "jantar",
    "ceia_noturna": "ceia",
}


def _normalize_meal_plan(raw: dict) -> dict:
    """Mapeia chaves não-canônicas do GPT para as chaves esperadas."""
    canonical = {}
    for k, v in raw.items():
        normalized = k.lower().strip().replace(" ", "_")
        target = _MEAL_KEY_ALIASES.get(normalized, normalized)
        # se já existe a chave canônica, não sobrescreve
        if target not in canonical:
            canonical[target] = v
    return canonical


@router.post("/upload-exam/{patient_id}")
async def upload_exam(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
) -> dict:
    """
    Paciente envia PDF/Foto do exame de sangue.
    IA extrai apenas métricas macro (LGPD-compliant) e gera rascunho de plano alimentar.
    Status: PENDENTE até nutricionista assinar.
    """
    file_bytes = await file.read()
    content_type = file.content_type or ""

    # OCR via GPT-4o Vision
    extracted_data = _call_vision_ocr(file_bytes, content_type, settings)

    # Plano alimentar funcional via GPT-4o
    suggested_plan = _call_meal_plan(extracted_data, settings)

    verification_token = str(uuid.uuid4())

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clinical_records
                (patient_id, extracted_biochemistry, suggested_meal_plan, status, verification_token)
                VALUES (%s, %s, %s, 'PENDENTE', %s)
                RETURNING id, created_at
                """,
                (patient_id, json.dumps(extracted_data), json.dumps(suggested_plan), verification_token),
            )
            row = cur.fetchone()
            conn.commit()

    return {
        "message": "Exame processado com sucesso. Plano alimentar aguardando assinatura da nutricionista.",
        "record_id": row["id"],
        "verification_token": verification_token,
        "extracted_data": extracted_data,
        "markers_found": len(extracted_data),
        "status": "PENDENTE",
    }


@router.post("/sign-record/{record_id}")
def sign_record(
    record_id: int,
    req: SignRecordRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Nutricionista (B2B) aprova e assina digitalmente o plano gerado pela IA.
    Gera PDF final com assinatura e QR Code de verificação.
    Conformidade CFN 856/2026: Human-in-the-Loop obrigatório.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clinical_records WHERE id = %s", (record_id,))
            record = cur.fetchone()
            if not record:
                raise HTTPException(status_code=404, detail="Registro clínico não encontrado")
            if record["status"] == "ASSINADO":
                raise HTTPException(status_code=400, detail="Registro já foi assinado")

            cur.execute(
                "SELECT * FROM professional_nutricionistas WHERE id = %s AND is_active = true",
                (req.nutricionista_id,),
            )
            nutri = cur.fetchone()
            if not nutri:
                raise HTTPException(status_code=400, detail="Nutricionista inválida ou inativa")

            pdf_filename = f"prontuario_{record_id}_{record['verification_token'][:8]}.pdf"
            pdf_path = f"/app/static/pdfs/{pdf_filename}"

            _generate_signed_pdf(record, nutri, pdf_path)

            now = datetime.now(timezone.utc)
            cur.execute(
                """
                UPDATE clinical_records
                SET status = 'ASSINADO', nutricionista_id = %s, signed_at = %s, pdf_url = %s
                WHERE id = %s
                """,
                (req.nutricionista_id, now, f"/static/pdfs/{pdf_filename}", record_id),
            )
            conn.commit()

    return {
        "message": "Plano alimentar assinado e homologado com sucesso!",
        "pdf_url": f"/static/pdfs/{pdf_filename}",
        "signed_at": now.isoformat(),
        "nutricionista": nutri["name"],
        "crn": nutri["crn"],
    }


@router.get("/records/{patient_id}")
def list_records(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Lista todos os prontuários clínicos de um paciente."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cr.id, cr.status, cr.created_at, cr.signed_at, cr.pdf_url,
                       pn.name as nutricionista_name, pn.crn
                FROM clinical_records cr
                LEFT JOIN professional_nutricionistas pn ON cr.nutricionista_id = pn.id
                WHERE cr.patient_id = %s
                ORDER BY cr.created_at DESC
                """,
                (patient_id,),
            )
            records = cur.fetchall()

    return {
        "patient_id": patient_id,
        "total": len(records),
        "records": [
            {
                "id": r["id"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "signed_at": r["signed_at"].isoformat() if r["signed_at"] else None,
                "pdf_url": r["pdf_url"],
                "nutricionista": r["nutricionista_name"],
                "crn": r["crn"],
            }
            for r in records
        ],
    }


@router.get("/verify/{token}")
def verify_record(
    token: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Verifica autenticidade de um prontuário via QR Code."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cr.id, cr.status, cr.signed_at, cr.patient_id,
                       pn.name as nutricionista_name, pn.crn
                FROM clinical_records cr
                LEFT JOIN professional_nutricionistas pn ON cr.nutricionista_id = pn.id
                WHERE cr.verification_token = %s
                """,
                (token,),
            )
            record = cur.fetchone()

    if not record:
        raise HTTPException(status_code=404, detail="Token de verificação inválido")

    return {
        "valid": record["status"] == "ASSINADO",
        "record_id": record["id"],
        "status": record["status"],
        "signed_at": record["signed_at"].isoformat() if record["signed_at"] else None,
        "nutricionista": record["nutricionista_name"],
        "crn": record["crn"],
    }


_BIOMARKER_META: dict[str, tuple[str, str, float, float]] = {
    # chave: (nome display, unidade, ref_min, ref_max)
    "glicose":         ("Glicose em Jejum",       "mg/dL",  70,   99),
    "colesterol_total":("Colesterol Total",        "mg/dL",  0,    199),
    "hdl":             ("HDL Colesterol",          "mg/dL",  40,   999),
    "ldl":             ("LDL Colesterol",          "mg/dL",  0,    129),
    "triglicerideos":  ("Triglicerídeos",          "mg/dL",  0,    149),
    "vitamina_d":      ("Vitamina D (25-OH)",      "ng/mL",  30,   100),
    "ferro_serico":    ("Ferro Sérico",            "µg/dL",  60,   170),
    "ferritina":       ("Ferritina",               "ng/mL",  15,   150),
    "tsh":             ("TSH",                     "µUI/mL", 0.4,  4.0),
    "t3":              ("T3 Livre",                "pg/mL",  2.3,  4.2),
    "t4":              ("T4 Livre",                "ng/dL",  0.8,  1.8),
}

_MEAL_LABELS: dict[str, str] = {
    "cafe_da_manha": "Café da Manhã",
    "lanche_manha":  "Lanche da Manhã",
    "almoco":        "Almoço",
    "lanche_tarde":  "Lanche da Tarde",
    "jantar":        "Jantar",
    "ceia":          "Ceia",
}

_MEAL_ICONS: dict[str, str] = {
    "cafe_da_manha": "☀",
    "lanche_manha":  "🍎",
    "almoco":        "🍽",
    "lanche_tarde":  "🥗",
    "jantar":        "🌙",
    "ceia":          "🌿",
}


def _generate_signed_pdf(record: dict, nutri: dict, output_path: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        Image, HRFlowable, KeepTogether,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    import qrcode

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    W, H = A4
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
    )
    styles = getSampleStyleSheet()

    GREEN      = colors.HexColor("#059669")
    GREEN_DARK = colors.HexColor("#065F46")
    GREEN_BG   = colors.HexColor("#ECFDF5")
    GREEN_MID  = colors.HexColor("#D1FAE5")
    RED        = colors.HexColor("#DC2626")
    RED_BG     = colors.HexColor("#FEF2F2")
    AMBER      = colors.HexColor("#D97706")
    SLATE      = colors.HexColor("#475569")
    SLATE_DARK = colors.HexColor("#1E293B")
    SLATE_LIGHT= colors.HexColor("#94A3B8")
    BORDER     = colors.HexColor("#E2E8F0")
    WHITE      = colors.white

    title_style = ParagraphStyle(
        "DocTitle", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=20,
        textColor=WHITE, leading=24,
    )
    subtitle_style = ParagraphStyle(
        "DocSub", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9,
        textColor=colors.HexColor("#A7F3D0"), leading=13,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=11,
        textColor=GREEN_DARK, spaceBefore=10, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=SLATE,
    )
    meal_label_style = ParagraphStyle(
        "MealLabel", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=9.5,
        textColor=SLATE_DARK, spaceBefore=5, spaceAfter=1,
    )
    meal_body_style = ParagraphStyle(
        "MealBody", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=SLATE,
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontName="Helvetica", fontSize=7.5,
        textColor=SLATE_LIGHT, leading=11,
    )

    signed_at = record.get("signed_at") or datetime.now(timezone.utc)
    if isinstance(signed_at, str):
        signed_at = datetime.fromisoformat(signed_at)

    story = []

    # ── Cabeçalho verde ───────────────────────────────────────────────────────
    header_data = [[
        Paragraph("NutriDeby", title_style),
        Paragraph(
            f"<b>Prontuário</b> #{record['id']}<br/>"
            f"<b>Data</b> {signed_at.strftime('%d/%m/%Y')}<br/>"
            f"<b>Nutricionista</b> {nutri['name']}",
            subtitle_style,
        ),
    ]]
    header_table = Table(header_data, colWidths=[doc.width * 0.6, doc.width * 0.4])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), GREEN),
        ("TOPPADDING",  (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0,0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",       (1, 0), (1, 0),   "RIGHT"),
        ("RIGHTPADDING",(1, 0), (1, 0),   12),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    # ── Análise Bioquímica ────────────────────────────────────────────────────
    bio = record.get("extracted_biochemistry") or {}
    if isinstance(bio, str):
        bio = json.loads(bio)

    story.append(Paragraph("Análise Bioquímica", section_style))

    if bio:
        col_w = [doc.width * 0.38, doc.width * 0.15, doc.width * 0.15, doc.width * 0.20, doc.width * 0.12]
        bio_rows = [[
            Paragraph("<b>Marcador</b>", ParagraphStyle("th", parent=body_style, fontName="Helvetica-Bold", textColor=GREEN_DARK)),
            Paragraph("<b>Resultado</b>", ParagraphStyle("th", parent=body_style, fontName="Helvetica-Bold", textColor=GREEN_DARK)),
            Paragraph("<b>Unidade</b>", ParagraphStyle("th", parent=body_style, fontName="Helvetica-Bold", textColor=GREEN_DARK)),
            Paragraph("<b>Referência</b>", ParagraphStyle("th", parent=body_style, fontName="Helvetica-Bold", textColor=GREEN_DARK)),
            Paragraph("<b>Status</b>", ParagraphStyle("th", parent=body_style, fontName="Helvetica-Bold", textColor=GREEN_DARK)),
        ]]
        style_cmds = [
            ("BACKGROUND",   (0, 0), (-1, 0), GREEN_BG),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("GRID",         (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ]

        for i, (key, val) in enumerate(bio.items()):
            row_num = i + 1
            meta = _BIOMARKER_META.get(key)
            if meta:
                label, unit, ref_min, ref_max = meta
                try:
                    fval = float(val)
                    if fval < ref_min:
                        flag, flag_color, bg = "↓ Baixo", AMBER, colors.HexColor("#FFFBEB")
                    elif fval > ref_max:
                        flag, flag_color, bg = "↑ Alto", RED, RED_BG
                    else:
                        flag, flag_color, bg = "Normal", GREEN, GREEN_BG if i % 2 == 0 else WHITE
                except (ValueError, TypeError):
                    flag, flag_color, bg = "—", SLATE_LIGHT, WHITE

                ref_str = (
                    f"{'> ' if ref_min == 0 and ref_max < 999 else ''}"
                    f"{'< ' if ref_min == 0 else ''}"
                    f"{ref_min if ref_min > 0 else ''}"
                    f"{' – ' if ref_min > 0 and ref_max < 999 else ''}"
                    f"{ref_max if ref_max < 999 else ''}"
                ).strip()
                if ref_min == 0:
                    ref_str = f"< {ref_max}"
                elif ref_max == 999:
                    ref_str = f"> {ref_min}"
                else:
                    ref_str = f"{ref_min} – {ref_max}"
            else:
                label = key.replace("_", " ").title()
                unit, ref_str = "—", "—"
                flag, flag_color, bg = "—", SLATE_LIGHT, WHITE

            flag_style = ParagraphStyle("flag", parent=body_style, textColor=flag_color, fontName="Helvetica-Bold", fontSize=8.5)
            val_style  = ParagraphStyle("val",  parent=body_style, fontName="Helvetica-Bold", textColor=SLATE_DARK)

            bio_rows.append([
                Paragraph(label, body_style),
                Paragraph(str(val), val_style),
                Paragraph(unit, body_style),
                Paragraph(ref_str, body_style),
                Paragraph(flag, flag_style),
            ])
            style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), bg))

        t = Table(bio_rows, colWidths=col_w)
        t.setStyle(TableStyle(style_cmds))
        story.append(t)
    else:
        story.append(Paragraph("Nenhum marcador bioquímico extraído do documento.", body_style))

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))

    # ── Plano Alimentar ───────────────────────────────────────────────────────
    story.append(Paragraph("Plano Alimentar Funcional", section_style))

    plan = record.get("suggested_meal_plan") or {}
    if isinstance(plan, str):
        plan = json.loads(plan)

    # Normaliza chaves do GPT antes de ordenar
    plan = _normalize_meal_plan(plan)

    _meal_order = ["cafe_da_manha", "lanche_manha", "almoco", "lanche_tarde", "jantar", "ceia"]
    ordered_plan = {k: plan[k] for k in _meal_order if k in plan}
    ordered_plan.update({k: v for k, v in plan.items() if k not in _meal_order})

    # Layout 2 colunas: 3 refeições à esquerda, 3 à direita
    meals_list = list(ordered_plan.items())
    left_meals  = meals_list[:3]
    right_meals = meals_list[3:]

    def _meal_cell(items):
        cell = []
        for meal, desc in items:
            label = _MEAL_LABELS.get(meal, meal.replace("_", " ").title())
            cell.append(Paragraph(f"<b>{label}</b>", meal_label_style))
            cell.append(Paragraph(str(desc), meal_body_style))
            cell.append(Spacer(1, 5))
        return cell

    if left_meals and right_meals:
        col_table = Table(
            [[_meal_cell(left_meals), _meal_cell(right_meals)]],
            colWidths=[doc.width * 0.49, doc.width * 0.49],
        )
        col_table.setStyle(TableStyle([
            ("VALIGN",      (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",(0, 0), (-1, -1), 6),
            ("TOPPADDING",  (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0,0), (-1, -1), 0),
        ]))
        story.append(col_table)
    else:
        for meal, desc in ordered_plan.items():
            label = _MEAL_LABELS.get(meal, meal.replace("_", " ").title())
            story.append(Paragraph(f"<b>{label}</b>", meal_label_style))
            story.append(Paragraph(str(desc), meal_body_style))
            story.append(Spacer(1, 4))

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Spacer(1, 5))

    # ── Bloco de Assinatura + QR ──────────────────────────────────────────────
    qr_url = f"https://nutrideby.com.br/api/clinical/verify/{record['verification_token']}"
    qr_img = qrcode.QRCode(version=1, box_size=4, border=2)
    qr_img.add_data(qr_url)
    qr_img.make(fit=True)
    qr_pil = qr_img.make_image(fill_color="black", back_color="white")
    qr_path = f"/tmp/qr_{record['id']}.png"
    qr_pil.save(qr_path)

    sig_name_style = ParagraphStyle("SigName", parent=body_style, fontName="Helvetica-Bold", fontSize=10, textColor=SLATE_DARK)
    sig_detail_style = ParagraphStyle("SigDetail", parent=body_style, fontSize=9, textColor=SLATE)
    qr_label_style = ParagraphStyle("QRLabel", parent=small_style, alignment=1)

    sig_block = [
        [
            [
                Paragraph(nutri["name"], sig_name_style),
                Paragraph(nutri["crn"], sig_detail_style),
                Paragraph("Nutricionista Responsável", sig_detail_style),
                Paragraph("Assinado digitalmente", ParagraphStyle("signed", parent=small_style, textColor=GREEN)),
            ],
            [
                Image(qr_path, width=58, height=58),
                Paragraph("Verificar autenticidade", qr_label_style),
            ],
        ]
    ]
    sig_table = Table(sig_block, colWidths=[doc.width * 0.7, doc.width * 0.3])
    sig_table.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",        (1, 0), (1, 0),   "CENTER"),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX",          (0, 0), (-1, -1), 0.5, BORDER),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(sig_table)

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Documento gerado com auxílio de IA e revisado/assinado por nutricionista habilitada, "
        "em conformidade com a Resolução CFN nº 856/2026. Autenticidade verificável pelo QR Code acima.",
        small_style,
    ))

    doc.build(story)

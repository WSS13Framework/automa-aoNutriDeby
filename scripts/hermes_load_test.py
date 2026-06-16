#!/usr/bin/env python3
"""
hermes_load_test.py — Teste de carga real do Hermes Agent

Dispara múltiplos perfis em paralelo, mede latência por mensagem,
taxa de cache hits Claude, e qualidade das mensagens geradas.

Uso:
  python3 scripts/hermes_load_test.py --dry-run     # só gera mensagens
  python3 scripts/hermes_load_test.py --send        # envia de verdade
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

# Adiciona src ao path
sys.path.insert(0, "/app/src")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nutrideby:nutrideby_dev@postgres:5432/nutrideby")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
TWILIO_SID        = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN      = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM       = os.getenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")
OPENCLAW_URL      = os.getenv("OPENCLAW_SEND_URL", "")
OPENCLAW_KEY      = os.getenv("OPENCLAW_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SEP = "=" * 65


@dataclass
class MessageResult:
    profile: str
    patient_name: str
    phone: str
    dias_inativo: int
    mensagem: str
    latencia_s: float
    cache_read: int = 0
    cache_created: int = 0
    input_tokens: int = 0
    enviado: bool = False
    sid: str = ""
    erro: str = ""


@dataclass
class ProfileResult:
    profile: str
    label: str
    total: int = 0
    ok: int = 0
    erros: int = 0
    latencia_total: float = 0.0
    cache_hits: int = 0
    tokens_total: int = 0
    mensagens: list[MessageResult] = field(default_factory=list)


# ── Perfis de teste ────────────────────────────────────────────────────────────

PERFIS_TESTE = [
    {
        "profile": "inativo_7",
        "label": "Inativo 7-13 dias",
        "limit": 5,
        "goal": "Check-in leve para pacientes que faltaram uma semana. Reforçar o vínculo antes de se distanciar mais, sem alarmismo.",
        "days_min": 7, "days_max": 13,
    },
    {
        "profile": "inativo_30",
        "label": "Inativo 30+ dias",
        "limit": 5,
        "goal": "Reconectar pacientes que não aparecem há mais de 30 dias. Mostrar que a nutricionista lembra deles pessoalmente.",
        "days_min": 30, "days_max": None,
    },
    {
        "profile": "inativo_14",
        "label": "Inativo 14-29 dias",
        "limit": 5,
        "goal": "Reengajar pacientes que sumiram há 2 a 4 semanas — janela crítica antes do afastamento definitivo.",
        "days_min": 14, "days_max": 29,
    },
]


# ── Busca pacientes do banco ───────────────────────────────────────────────────

def get_patients_for_test(cfg: dict) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row

    days_min = cfg["days_min"]
    days_max = cfg["days_max"]

    clauses = []
    if days_min:
        clauses.append(f"(CURRENT_DATE - COALESCE(p.last_logged_date, (p.metadata->>'LastConsultation')::date)) >= {days_min}")
    if days_max:
        clauses.append(f"(CURRENT_DATE - COALESCE(p.last_logged_date, (p.metadata->>'LastConsultation')::date)) <= {days_max}")
    days_filter = ("AND " + " AND ".join(clauses)) if clauses else ""

    sql = f"""
        SELECT p.id, p.display_name,
            COALESCE(pp.phone,
                CASE WHEN length(regexp_replace(p.metadata->>'MobilePhone','[^0-9]','','g')) >= 10
                     THEN '+55' || regexp_replace(p.metadata->>'MobilePhone','[^0-9]','','g')
                END
            ) AS phone,
            p.metadata->>'Occupancy' AS ocupacao,
            p.metadata->>'Birthday'  AS nascimento,
            p.metadata->>'LastConsultation' AS ultima_consulta,
            CURRENT_DATE - COALESCE(p.last_logged_date, (p.metadata->>'LastConsultation')::date) AS days_inactive,
            (SELECT string_agg(LEFT(d.content_text, 300), ' | ')
             FROM documents d
             WHERE d.patient_id = p.id
               AND d.doc_type IN ('dietbox_plano_alimentar','dietbox_qpc_respostas','dietbox_meta_export')
             LIMIT 3
            ) AS clinical_summary
        FROM patients p
        LEFT JOIN patient_phones pp ON pp.patient_id = p.id
        WHERE (pp.phone IS NOT NULL
               OR length(regexp_replace(p.metadata->>'MobilePhone','[^0-9]','','g')) >= 10)
          AND COALESCE(p.last_logged_date, (p.metadata->>'LastConsultation')::date) IS NOT NULL
          {days_filter}
        ORDER BY last_logged_date ASC NULLS LAST
        LIMIT {cfg['limit']}
    """
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


# ── Geração de mensagem ────────────────────────────────────────────────────────

def gerar_mensagem_claude(patient: dict, cfg: dict) -> tuple[str, int, int, int]:
    import anthropic

    nome = (patient["display_name"] or "paciente").split()[0]
    dias = patient["days_inactive"] or 0
    ocupacao = patient.get("ocupacao") or ""
    ultima = (patient.get("ultima_consulta") or "")[:10]
    clinical = (patient.get("clinical_summary") or "")[:600]

    static_system = (
        f"Você é a assistente virtual da nutricionista Dra. Débora.\n\n"
        f"OBJETIVO: {cfg['goal']}\n\n"
        f"Contexto clínico do paciente:\n{clinical}\n\n"
        "Regras:\n"
        "- Máximo 100 palavras\n"
        "- Tom humano, acolhedor, sem pressão\n"
        "- Mencione algo específico do histórico clínico se houver\n"
        "- Mostre que a Dra. Débora lembra do paciente pessoalmente\n"
        "- Termine com UMA pergunta sobre como está hoje\n"
        "- Não mencione preço\n"
        "- Assine como: Assistente da Dra. Débora 🥗\n"
        "- Escreva apenas a mensagem"
    )
    dynamic_system = (
        f"Paciente: {nome} | Ocupação: {ocupacao}\n"
        f"Dias inativo: {dias} | Última consulta: {ultima}"
    )
    user = f"Escreva uma mensagem de WhatsApp personalizada para {nome}."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=200,
        system=[
            {"type": "text", "text": static_system, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_system},
        ],
        messages=[{"role": "user", "content": user}],
    )
    usage = msg.usage
    return (
        msg.content[0].text.strip(),
        getattr(usage, "cache_read_input_tokens", 0) or 0,
        getattr(usage, "cache_creation_input_tokens", 0) or 0,
        usage.input_tokens,
    )


# ── Envio Twilio ───────────────────────────────────────────────────────────────

def enviar_twilio(phone: str, mensagem: str) -> tuple[str, str]:
    from twilio.rest import Client
    twilio = Client(TWILIO_SID, TWILIO_TOKEN)
    msg = twilio.messages.create(from_=TWILIO_FROM, body=mensagem, to=f"whatsapp:{phone}")
    return msg.sid, msg.status


# ── Processar um paciente ──────────────────────────────────────────────────────

def processar_paciente(patient: dict, cfg: dict, dry_run: bool) -> MessageResult:
    import re
    nome = patient["display_name"] or "Paciente"
    phone_raw = patient["phone"] or ""
    digits = re.sub(r"\D", "", phone_raw)
    if not digits.startswith("55"):
        phone = f"+55{digits}"
    else:
        phone = f"+{digits}"

    t0 = time.perf_counter()
    try:
        mensagem, cache_read, cache_created, input_tok = gerar_mensagem_claude(patient, cfg)
        latencia = time.perf_counter() - t0

        result = MessageResult(
            profile=cfg["profile"],
            patient_name=nome,
            phone=phone,
            dias_inativo=int(patient.get("days_inactive") or 0),
            mensagem=mensagem,
            latencia_s=round(latencia, 2),
            cache_read=cache_read,
            cache_created=cache_created,
            input_tokens=input_tok,
        )

        if not dry_run and phone and len(digits) >= 10:
            try:
                sid, status = enviar_twilio(phone, mensagem)
                result.enviado = True
                result.sid = sid
            except Exception as e:
                result.erro = f"Twilio: {e}"
        return result

    except Exception as e:
        return MessageResult(
            profile=cfg["profile"],
            patient_name=nome,
            phone=phone,
            dias_inativo=0,
            mensagem="",
            latencia_s=round(time.perf_counter() - t0, 2),
            erro=str(e),
        )


# ── Runner por perfil ──────────────────────────────────────────────────────────

def run_perfil(cfg: dict, dry_run: bool) -> ProfileResult:
    result = ProfileResult(profile=cfg["profile"], label=cfg["label"])
    patients = get_patients_for_test(cfg)
    result.total = len(patients)

    logger.info("Perfil %-15s → %d pacientes encontrados", cfg["profile"], len(patients))

    for p in patients:
        mr = processar_paciente(p, cfg, dry_run)
        result.mensagens.append(mr)
        result.latencia_total += mr.latencia_s
        result.tokens_total += mr.input_tokens
        if mr.cache_read > 0:
            result.cache_hits += 1
        if mr.erro:
            result.erros += 1
        else:
            result.ok += 1
        time.sleep(0.5)  # rate limit gentil

    return result


# ── Relatório ──────────────────────────────────────────────────────────────────

def imprimir_relatorio(resultados: list[ProfileResult], dry_run: bool) -> None:
    print(f"\n{'#'*65}")
    print(f"  RELATÓRIO — HERMES LOAD TEST {'(DRY RUN)' if dry_run else '(ENVIO REAL)'}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*65}\n")

    total_ok = total_erros = total_tokens = total_cache = 0
    total_latencia = 0.0

    for r in resultados:
        print(f"\n{SEP}")
        print(f"  PERFIL: {r.label} ({r.profile})")
        print(f"  Pacientes: {r.total} | OK: {r.ok} | Erros: {r.erros}")
        if r.ok > 0:
            avg_lat = r.latencia_total / r.ok
            print(f"  Latência média: {avg_lat:.1f}s | Total tokens: {r.tokens_total}")
            print(f"  Cache hits: {r.cache_hits}/{r.ok} ({round(r.cache_hits/r.ok*100)}%)")
        print(f"{SEP}")

        for mr in r.mensagens:
            status = "✅" if not mr.erro else "❌"
            cache_icon = "💾" if mr.cache_read > 0 else "🔄"
            enviado_icon = "📤" if mr.enviado else ("🚫" if not dry_run else "🔍")
            print(f"\n{status} {enviado_icon} {cache_icon} {mr.patient_name} (+{mr.dias_inativo}d inativo)")
            print(f"   📱 {mr.phone} | ⏱ {mr.latencia_s}s | tokens: {mr.input_tokens} (cache_read: {mr.cache_read})")
            if mr.mensagem:
                for linha in mr.mensagem.split("\n"):
                    print(f"   │ {linha}")
            if mr.erro:
                print(f"   ⚠️  ERRO: {mr.erro}")
            if mr.sid:
                print(f"   SID: {mr.sid}")

        total_ok += r.ok
        total_erros += r.erros
        total_tokens += r.tokens_total
        total_cache += r.cache_hits
        total_latencia += r.latencia_total

    print(f"\n{'#'*65}")
    print(f"  RESUMO GERAL")
    print(f"  Mensagens geradas: {total_ok} | Erros: {total_erros}")
    if total_ok > 0:
        print(f"  Latência média global: {total_latencia/total_ok:.1f}s")
        print(f"  Cache hits total: {total_cache}/{total_ok} ({round(total_cache/total_ok*100)}%)")
        print(f"  Tokens consumidos: {total_tokens}")
    print(f"{'#'*65}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes Load Test — situação real")
    parser.add_argument("--send",    action="store_true", help="Envia de verdade via Twilio")
    parser.add_argument("--dry-run", action="store_true", help="Só gera mensagens (padrão)")
    parser.add_argument("--perfil",  default="todos", help="inativo_7|inativo_14|inativo_30|todos")
    parser.add_argument("--limit",   type=int, default=0, help="Override de limit por perfil")
    parser.add_argument("--workers", type=int, default=3, help="Perfis em paralelo")
    args = parser.parse_args()

    dry_run = not args.send

    perfis = PERFIS_TESTE if args.perfil == "todos" else [p for p in PERFIS_TESTE if p["profile"] == args.perfil]
    if args.limit > 0:
        for p in perfis:
            p["limit"] = args.limit

    print(f"\n{SEP}")
    print(f"  HERMES LOAD TEST — {'DRY RUN' if dry_run else 'ENVIO REAL'}")
    print(f"  Perfis: {[p['profile'] for p in perfis]}")
    print(f"  Paralelo: {args.workers} workers | Modelo: {ANTHROPIC_MODEL}")
    print(f"{SEP}\n")

    resultados: list[ProfileResult] = []
    t_inicio = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_perfil, cfg, dry_run): cfg for cfg in perfis}
        for future in as_completed(futures):
            resultados.append(future.result())

    t_total = time.perf_counter() - t_inicio
    imprimir_relatorio(resultados, dry_run)
    print(f"  Tempo total de execução: {t_total:.1f}s\n")


if __name__ == "__main__":
    main()

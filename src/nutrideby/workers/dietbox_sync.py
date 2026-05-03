"""
Conector Dietbox (API v2) — Sprint 1 / MVP.

  python3 -m nutrideby.workers.dietbox_sync --probe PACIENTE_ID   # no Ubuntu host; no Docker: … worker python -m …
  python3 -m nutrideby.workers.dietbox_sync --sync-one PACIENTE_ID   # prontuário → documents
  python3 -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 1
  python3 -m nutrideby.workers.dietbox_sync --meta PACIENTE_ID --meta-take 50
  python3 -m nutrideby.workers.dietbox_sync --sync-meta-patient PACIENTE_ID [--meta-max-pages 100]
  python3 -m nutrideby.workers.dietbox_sync --sync-meta-all [--meta-all-limit 20] [--meta-all-sleep-ms 350]
  python3 -m nutrideby.workers.dietbox_sync --formula-imc 28.5 --formula-idade 42
  python3 -m nutrideby.workers.dietbox_sync --sync-formula-imc-all --formula-workers 4
  python3 -m nutrideby.workers.dietbox_sync --feed-list
  python3 -m nutrideby.workers.dietbox_sync --subscription
  python3 -m nutrideby.workers.dietbox_sync --sync-subscription
  python3 -m nutrideby.workers.dietbox_sync --sync-prontuario-all [--prontuario-limit N] [--prontuario-sleep-ms 250]
  python3 -m nutrideby.workers.dietbox_sync --sync-prontuario-all --prontuario-resume-run-id UUID
  python3 -m nutrideby.workers.dietbox_sync --smoke   # cron: JWT; exit 3 em HTTP 401

Requer .env: DATABASE_URL, DIETBOX_BEARER_TOKEN; opcional DIETBOX_API_BASE, DIETBOX_WEB_BASE.
Tabela ``external_snapshots``: ``infra/sql/002_external_snapshots.sql`` (subscription persistida).
"""

from __future__ import annotations

import argparse
import json
import logging
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import psycopg

from nutrideby.clients.dietbox_api import (
    DietboxClient,
    extract_dietbox_paged_items,
    extract_imc_idade_from_payload,
    extract_list_payload,
    get_formula_situacao_imc,
    get_mvc_feed_list,
    join_dietbox_url,
    parse_json_body,
    patient_detail_item_from_response,
    patient_record_from_item,
)
from nutrideby.config import Settings
from nutrideby.persist.crm_persist import insert_document_if_new, upsert_patient
from nutrideby.persist.extraction_runs import (
    JOB_DIETBOX_PRONTUARIO_BULK,
    create_run,
    finish_run,
    get_run,
    update_run,
)
from nutrideby.persist.snapshots import (
    KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION,
    upsert_external_snapshot,
)

logger = logging.getLogger(__name__)

SOURCE = "dietbox"


def _client(settings: Settings) -> DietboxClient:
    base = settings.dietbox_api_base or "https://api.dietbox.me"
    return DietboxClient(base, settings.dietbox_bearer_token or "")


def probe_prontuario(settings: Settings, patient_id: str) -> int:
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    st, body = c.get_prontuario(patient_id)
    if st == 204:
        logger.info(
            "probe paciente=%s HTTP=204 sem corpo (igual ao browser — não é erro)",
            patient_id,
        )
    else:
        logger.info("probe paciente=%s HTTP=%s bytes=%s", patient_id, st, len(body))
    return 0 if st in (200, 204) else 1


def probe_meta(
    settings: Settings,
    patient_id: str,
    *,
    skip: int = 0,
    take: int = 50,
) -> int:
    """GET /v2/meta — inspecciona paginação e chaves do primeiro item (sem gravar na base)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    st, raw = c.get_meta(patient_id, skip=skip, take=take)
    if st != 200:
        logger.error("meta HTTP=%s corpo=%r", st, raw[:400])
        return 1
    data = parse_json_body(raw)
    if isinstance(data, dict) and data.get("Success") is False:
        logger.error(
            "Success=false: %s",
            data.get("Message") or data.get("message"),
        )
        return 1
    items, total_items, total_pages = extract_dietbox_paged_items(data)
    logger.info(
        "meta paciente=%s skip=%s take=%s itens_pagina=%s TotalItems=%s TotalPages=%s",
        patient_id,
        skip,
        take,
        len(items),
        total_items,
        total_pages,
    )
    if items:
        keys = list(items[0].keys())
        logger.info("Chaves do 1º item (máx. 40): %s", keys[:40])
    else:
        logger.info("Nenhum item em Items — expande Data no Preview ou aumenta take/skip")
    return 0


def probe_formula_imc(settings: Settings, imc: float, idade: int) -> int:
    """GET site ``.../Formulas/SituacaoIMC`` — só loga HTTP + JSON (não grava na base)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env (mesmo token da API).")
        return 2
    st, raw = get_formula_situacao_imc(
        settings.dietbox_bearer_token,
        imc=imc,
        idade=idade,
        web_base=settings.dietbox_web_base,
        locale=settings.dietbox_web_locale,
    )
    if st != 200:
        logger.error("SituacaoIMC HTTP=%s corpo=%r", st, raw[:500])
        return 1
    data = parse_json_body(raw)
    logger.info("SituacaoIMC OK imc=%s idade=%s tipo=%s", imc, idade, type(data).__name__)
    if isinstance(data, dict):
        logger.info("Chaves JSON: %s", list(data.keys()))
    logger.info("Corpo (truncado): %s", str(data)[:800])
    return 0


def probe_subscription(settings: Settings) -> int:
    """GET ``/v2/nutritionist/subscription`` — subscrição / plano (URL sem ``v2//``)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN")
        return 2
    c = _client(settings)
    st, raw = c.get_nutritionist_subscription()
    if st != 200:
        logger.error("subscription HTTP=%s corpo=%r", st, raw[:500])
        return 1
    data = parse_json_body(raw)
    logger.info("subscription OK tipo=%s", type(data).__name__)
    if isinstance(data, dict):
        logger.info("Chaves topo: %s", list(data.keys())[:50])
    logger.info("Corpo (truncado): %s", str(data)[:1500])
    return 0


def sync_subscription_persist(settings: Settings) -> int:
    """GET subscription e ``upsert`` em ``external_snapshots`` (chave estável)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN")
        return 2
    c = _client(settings)
    st, raw = c.get_nutritionist_subscription()
    if st != 200:
        logger.error("subscription HTTP=%s corpo=%r", st, raw[:500])
        return 1
    data = parse_json_body(raw)
    if isinstance(data, (dict, list)):
        payload: Any = data
    else:
        payload = {"_raw_type": type(data).__name__, "repr": str(data)[:8000]}
    try:
        with psycopg.connect(settings.database_url) as conn:
            upsert_external_snapshot(
                conn,
                key=KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION,
                payload=payload,
                http_status=st,
            )
    except psycopg.errors.UndefinedTable:
        logger.error(
            "Tabela external_snapshots em falta. Aplica: psql $DATABASE_URL -f infra/sql/002_external_snapshots.sql",
        )
        return 2
    logger.info("sync-subscription gravada key=%s", KEY_DIETBOX_NUTRITIONIST_SUBSCRIPTION)
    return 0


def probe_feed_list(settings: Settings) -> int:
    """GET ``/pt-BR/Feed/List`` (site MVC) — vê actividade global / notificações (JSON pequeno)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN")
        return 2
    st, raw = get_mvc_feed_list(
        settings.dietbox_bearer_token,
        web_base=settings.dietbox_web_base,
        locale=settings.dietbox_web_locale,
    )
    if st != 200:
        logger.error("Feed/List HTTP=%s corpo=%r", st, raw[:500])
        return 1
    data = parse_json_body(raw)
    logger.info("Feed/List OK tipo_raiz=%s", type(data).__name__)
    if isinstance(data, dict):
        logger.info("Chaves topo: %s", list(data.keys())[:40])
    logger.info("Corpo (truncado): %s", str(data)[:1200])
    return 0


def sync_meta_for_patient(
    settings: Settings,
    patient_id: str,
    *,
    take: int = 50,
    max_pages: int = 100,
) -> int:
    """
    Pagina ``GET /v2/meta`` e grava um documento JSON agregado (``doc_type=dietbox_meta_export``).

    Re-correr com a mesma linha do tempo idempotente (mesmo ``content_sha256``) não duplica;
    quando a API acrescentar eventos, o hash muda e grava-se um documento novo.
    """
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    all_items: list[dict[str, Any]] = []
    skip = 0
    pages = 0
    while pages < max_pages:
        st, raw = c.get_meta(patient_id, skip=skip, take=take)
        if st != 200:
            logger.error("meta sync paciente=%s HTTP=%s corpo=%r", patient_id, st, raw[:400])
            return 1
        data = parse_json_body(raw)
        if isinstance(data, dict) and data.get("Success") is False:
            logger.error(
                "meta Success=false paciente=%s: %s",
                patient_id,
                data.get("Message") or data.get("message"),
            )
            return 1
        items, total_items, total_pages = extract_dietbox_paged_items(data)
        if not items:
            break
        all_items.extend(items)
        pages += 1
        if len(items) < take:
            break
        if total_pages is not None and pages >= total_pages:
            break
        skip += take

    if not all_items:
        logger.info("sync-meta paciente=%s: nenhum item (não grava documento)", patient_id)
        return 0

    bundle: dict[str, Any] = {
        "schema": "dietbox_meta_export_v1",
        "paciente_external_id": patient_id,
        "item_count": len(all_items),
        "items": all_items,
    }
    text = json.dumps(bundle, ensure_ascii=False, indent=2)
    ref = join_dietbox_url(
        settings.dietbox_api_base or "https://api.dietbox.me",
        f"v2/meta?idPaciente={urllib.parse.quote(str(patient_id), safe='')}",
    )
    meta = {
        "dietbox_paciente_id": patient_id,
        "meta_export_pages": pages,
        "meta_export_items": len(all_items),
    }
    with psycopg.connect(settings.database_url) as conn:
        pid = upsert_patient(
            conn,
            source_system=SOURCE,
            external_id=str(patient_id).strip(),
            display_name=None,
            metadata=meta,
        )
        new_id = insert_document_if_new(
            conn,
            patient_id=pid,
            doc_type="dietbox_meta_export",
            content_text=text,
            source_ref=ref,
        )
    logger.info(
        "sync-meta paciente=%s páginas=%s itens=%s doc_novo=%s",
        patient_id,
        pages,
        len(all_items),
        new_id is not None,
    )
    return 0


def sync_meta_all(
    settings: Settings,
    *,
    take: int,
    max_pages_per_patient: int,
    patient_limit: int | None,
    sleep_ms: int,
) -> int:
    """``sync_meta_for_patient`` para cada ``patients`` com ``source_system=dietbox``."""
    sleep_s = max(0, sleep_ms) / 1000.0
    failed = 0
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            q = """
                SELECT external_id FROM patients
                WHERE source_system = %s
                ORDER BY external_id ASC
            """
            params: list[Any] = [SOURCE]
            if patient_limit is not None and patient_limit > 0:
                q += " LIMIT %s"
                params.append(patient_limit)
            cur.execute(q, params)
            ids = [str(r[0]) for r in cur.fetchall()]
    logger.info("sync-meta-all: pacientes_na_fila=%s", len(ids))
    for ext in ids:
        rc = sync_meta_for_patient(
            settings,
            ext,
            take=take,
            max_pages=max_pages_per_patient,
        )
        if rc != 0:
            failed += 1
            logger.warning("sync-meta-all: paciente=%s exit=%s", ext, rc)
        if sleep_s > 0:
            time.sleep(sleep_s)
    logger.info("sync-meta-all concluído falhas=%s", failed)
    return 0 if failed == 0 else 1


def _post_smoke_alert_webhook(url: str, body: dict[str, Any]) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url.strip(),
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "nutrideby-dietbox-smoke/1.0",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
        resp.read()


def run_dietbox_smoke(settings: Settings) -> int:
    """
    Smoke leve: GET ``/v2/nutritionist/subscription`` (um pedido, sem gravar na base).

    Códigos de saída (úteis em cron):

    - ``0`` — HTTP 200, JWT aceite.
    - ``1`` — outro HTTP, rede, ou erro inesperado.
    - ``2`` — ``DIETBOX_BEARER_TOKEN`` em falta.
    - ``3`` — HTTP **401** (JWT expirado ou inválido); opcional POST para
      ``NUTRIDEBY_SMOKE_ALERT_WEBHOOK_URL``.
    """
    if not settings.dietbox_bearer_token:
        logger.error("smoke: DIETBOX_BEARER_TOKEN em falta")
        return 2
    c = _client(settings)
    try:
        st, raw = c.get_nutritionist_subscription()
    except urllib.error.URLError:
        logger.exception("smoke: falha de rede/SSL ao chamar Dietbox")
        return 1
    except Exception:
        logger.exception("smoke: erro inesperado ao chamar Dietbox")
        return 1
    if st == 200:
        logger.info("smoke OK GET /v2/nutritionist/subscription HTTP=200 bytes=%s", len(raw))
        return 0
    if st == 401:
        msg = (
            "NutriDeby smoke: Dietbox GET /v2/nutritionist/subscription → HTTP 401 "
            "(renovar DIETBOX_BEARER_TOKEN no servidor / .env)"
        )
        logger.error(msg)
        hook = settings.nutrideby_smoke_alert_webhook_url
        if hook and str(hook).strip():
            try:
                _post_smoke_alert_webhook(
                    str(hook).strip(),
                    {
                        "text": msg,
                        "source": "nutrideby.dietbox_sync",
                        "check": "smoke",
                        "http_status": 401,
                    },
                )
                logger.info("smoke: alerta enviado para webhook")
            except Exception:
                logger.exception("smoke: falha ao POST no webhook (exit 3 mantém-se)")
        return 3
    logger.error("smoke: subscription HTTP=%s corpo=%r", st, raw[:400])
    return 1


def _formula_imc_one_row(
    settings: Settings,
    row: tuple[Any, Any, Any],
    *,
    dry_run: bool,
    fetch_patient: bool,
) -> tuple[str, str]:
    """
    Processa uma linha de ``patients``. Devolve (etiqueta, external_id ou mensagem curta).
    etiqueta: ok | skip | http | err
    """
    pid, ext_id, meta = row[0], str(row[1]).strip(), row[2]
    if not ext_id:
        return "err", "external_id vazio"
    item: dict[str, Any] = dict(meta) if isinstance(meta, dict) else {}
    if fetch_patient and settings.dietbox_bearer_token:
        c = _client(settings)
        path = f"v2/paciente/{urllib.parse.quote(ext_id, safe='')}"
        st, raw = c.get_path(path)
        if st == 200:
            data = parse_json_body(raw)
            got = patient_detail_item_from_response(data)
            if isinstance(got, dict):
                item = {**item, **got}
    imc, idade = extract_imc_idade_from_payload(item)
    if imc is None or idade is None:
        return "skip", ext_id
    if not settings.dietbox_bearer_token:
        return "err", ext_id
    st, raw = get_formula_situacao_imc(
        settings.dietbox_bearer_token,
        imc=imc,
        idade=idade,
        web_base=settings.dietbox_web_base,
        locale=settings.dietbox_web_locale,
    )
    if st != 200:
        return "http", f"{ext_id}:{st}"
    data = parse_json_body(raw)
    text = (
        json.dumps(data, ensure_ascii=False, indent=2)
        if data is not None
        else raw.decode("utf-8", errors="replace")
    )
    base = settings.dietbox_web_base.rstrip("/")
    loc = settings.dietbox_web_locale.strip().strip("/")
    ref = f"{base}/{loc}/Formulas/SituacaoIMC?imc={imc}&idade={idade}"
    if dry_run:
        return "ok", ext_id
    with psycopg.connect(settings.database_url) as conn:
        insert_document_if_new(
            conn,
            patient_id=pid,
            doc_type="dietbox_situacao_imc",
            content_text=text,
            source_ref=ref,
        )
    return "ok", ext_id


def sync_formula_imc_all(
    settings: Settings,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    fetch_patient: bool = True,
    max_workers: int = 4,
) -> int:
    """
    Para cada paciente ``source_system=dietbox`` na base: obtém IMC+idade (metadata e/ou GET
    paciente), chama SituacaoIMC e grava ``documents`` (idempotente por hash do JSON).

    ``max_workers`` > 1 faz pedidos em paralelo (cuidado com rate limit da Dietbox).
    """
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN")
        return 2
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, external_id, metadata FROM patients
                WHERE source_system = %s
                ORDER BY external_id
                """,
                (SOURCE,),
            )
            rows = list(cur.fetchall())
    if limit is not None and limit > 0:
        rows = rows[:limit]
    n = len(rows)
    if n == 0:
        logger.warning("Nenhum paciente com source_system=%s na base.", SOURCE)
        return 0
    logger.info(
        "SituacaoIMC em lote: pacientes=%s dry_run=%s fetch_patient=%s workers=%s",
        n,
        dry_run,
        fetch_patient,
        max_workers,
    )
    ok = skip = http = err = 0
    if max_workers <= 1:
        for r in rows:
            tag, _ = _formula_imc_one_row(settings, r, dry_run=dry_run, fetch_patient=fetch_patient)
            if tag == "ok":
                ok += 1
            elif tag == "skip":
                skip += 1
            elif tag == "http":
                http += 1
            else:
                err += 1
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(_formula_imc_one_row, settings, r, dry_run=dry_run, fetch_patient=fetch_patient)
                for r in rows
            ]
            for fut in as_completed(futures):
                try:
                    tag, msg = fut.result()
                except Exception:
                    logger.exception("Falha num job SituacaoIMC")
                    err += 1
                    continue
                if tag == "ok":
                    ok += 1
                elif tag == "skip":
                    skip += 1
                elif tag == "http":
                    logger.warning("HTTP não-200: %s", msg)
                    http += 1
                else:
                    err += 1
    logger.info(
        "SituacaoIMC lote concluído: ok=%s skip_sem_imc_idade=%s http_erro=%s outros=%s",
        ok,
        skip,
        http,
        err,
    )
    return 0 if err == 0 and http == 0 else 1


def _prontuario_text_from_response(st: int, body: bytes) -> str:
    if st == 204 or not body:
        return "[Prontuário: API 204 sem corpo]"
    try:
        return json.dumps(
            json.loads(body.decode("utf-8")),
            ensure_ascii=False,
            indent=2,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body.decode("utf-8", errors="replace")


def apply_prontuario_response(
    settings: Settings,
    conn: psycopg.Connection,
    patient_id: str,
    st: int,
    body: bytes,
    *,
    preserve_display_name: bool,
) -> uuid.UUID | None:
    """Upsert paciente + documento idempotente. Devolve id do documento se inserido."""
    text = _prontuario_text_from_response(st, body)
    meta = {"dietbox_paciente_id": patient_id, "prontuario_http_status": st}
    ref = join_dietbox_url(
        settings.dietbox_api_base or "https://api.dietbox.me",
        f"v2/paciente/{patient_id}/prontuario",
    )
    display_name = None if preserve_display_name else f"Dietbox #{patient_id}"
    pid = upsert_patient(
        conn,
        source_system=SOURCE,
        external_id=patient_id,
        display_name=display_name,
        metadata=meta,
    )
    return insert_document_if_new(
        conn,
        patient_id=pid,
        doc_type="dietbox_prontuario",
        content_text=text,
        source_ref=ref,
    )


def sync_one_prontuario(settings: Settings, patient_id: str) -> int:
    """Grava paciente + conteúdo do prontuário (200 JSON ou 204 marcador)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN")
        return 2
    c = _client(settings)
    st, body = c.get_prontuario(patient_id)
    if st not in (200, 204):
        logger.error("HTTP %s", st)
        return 1
    with psycopg.connect(settings.database_url) as conn:
        new = apply_prontuario_response(
            settings,
            conn,
            patient_id,
            st,
            body,
            preserve_display_name=False,
        )
        logger.info("sync-one prontuário doc_novo=%s", new is not None)
    return 0


def sync_prontuario_all(
    settings: Settings,
    *,
    limit: int | None,
    sleep_ms: int,
    resume_run_id: uuid.UUID | None,
) -> int:
    """Prontuário em lote para ``patients`` com ``source_system=dietbox``; regista ``extraction_runs``."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN")
        return 2
    c = _client(settings)
    sleep_s = max(0, sleep_ms) / 1000.0
    http_other = 0
    new_docs = 0

    with psycopg.connect(settings.database_url) as conn:
        if resume_run_id is not None:
            info = get_run(conn, resume_run_id)
            if not info:
                logger.error("extraction_run não encontrado: %s", resume_run_id)
                return 2
            if info["status"] not in ("running", "failed"):
                logger.warning(
                    "Retomar run com status=%s (esperado running/failed)",
                    info["status"],
                )
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE extraction_runs
                    SET status = 'running', finished_at = NULL, error_message = NULL
                    WHERE id = %s
                    """,
                    (resume_run_id,),
                )
            run_id = resume_run_id
            cs = info["cursor_state"]
            last_ext: str | None = cs.get("last_external_id") if isinstance(cs, dict) else None
            processed = int((cs.get("processed") if isinstance(cs, dict) else 0) or 0)
        else:
            run_id = create_run(
                conn,
                cursor_state={
                    "job": JOB_DIETBOX_PRONTUARIO_BULK,
                    "last_external_id": None,
                    "processed": 0,
                },
                stats={},
            )
            last_ext = None
            processed = 0

        with conn.cursor() as cur:
            # Evitar ``NULL`` em dois placeholders seguidos: o Postgres não infere o tipo ($2).
            if last_ext is None:
                q = """
                    SELECT external_id FROM patients
                    WHERE source_system = %s
                    ORDER BY external_id ASC
                """
                params: list[Any] = [SOURCE]
            else:
                q = """
                    SELECT external_id FROM patients
                    WHERE source_system = %s AND external_id > %s
                    ORDER BY external_id ASC
                """
                params = [SOURCE, last_ext]
            if limit is not None and limit > 0:
                q += " LIMIT %s"
                params.append(limit)
            cur.execute(q, params)
            external_ids = [str(r[0]) for r in cur.fetchall()]

        logger.info(
            "sync-prontuario-all: run_id=%s retomada=%s pacientes_na_fila=%s",
            run_id,
            resume_run_id is not None,
            len(external_ids),
        )

        for ext_id in external_ids:
            st, body = c.get_prontuario(ext_id)
            if st == 401:
                finish_run(
                    conn,
                    run_id,
                    status="failed",
                    error_message="HTTP 401 (JWT inválido ou expirado)",
                    stats={"processed": processed, "new_documents": new_docs, "http_other": http_other},
                )
                logger.error("sync-prontuario-all: HTTP 401 — JWT; run marcada failed")
                return 1
            if st not in (200, 204):
                logger.warning("paciente=%s prontuário HTTP=%s (ignorar e continuar)", ext_id, st)
                http_other += 1
            else:
                new_id = apply_prontuario_response(
                    settings,
                    conn,
                    ext_id,
                    st,
                    body,
                    preserve_display_name=True,
                )
                if new_id is not None:
                    new_docs += 1

            processed += 1
            last_ext = ext_id
            update_run(
                conn,
                run_id,
                cursor_state={
                    "job": JOB_DIETBOX_PRONTUARIO_BULK,
                    "last_external_id": last_ext,
                    "processed": processed,
                },
                stats={"new_documents": new_docs, "http_other": http_other},
            )
            if sleep_s > 0:
                time.sleep(sleep_s)

        finish_run(
            conn,
            run_id,
            status="completed",
            stats={
                "processed": processed,
                "new_documents": new_docs,
                "http_other": http_other,
            },
        )

    logger.info(
        "sync-prontuario-all concluído: processados=%s docs_novos=%s http_não_200_204=%s",
        processed,
        new_docs,
        http_other,
    )
    if http_other:
        logger.warning("Alguns pedidos devolveram HTTP fora de 200/204; rever logs.")
    return 0


def sync_one_patient_detail(settings: Settings, patient_id: str) -> int:
    """GET /v2/paciente/{id} e upsert em patients (metadados da API)."""
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    path = f"v2/paciente/{urllib.parse.quote(patient_id, safe='')}"
    status, raw = c.get_path(path)
    if status == 404:
        logger.error("Paciente não encontrado: %s", patient_id)
        return 1
    if status != 200:
        logger.error("GET paciente HTTP=%s corpo=%r", status, raw[:300])
        return 1
    data = parse_json_body(raw)
    item: dict | None = None
    if isinstance(data, dict):
        if patient_record_from_item(data) is not None:
            item = data
        else:
            found = extract_list_payload(data)
            if len(found) == 1:
                item = found[0]
    if item is None:
        logger.error("Resposta inesperada para paciente=%s tipo=%s", patient_id, type(data).__name__)
        return 1
    rec = patient_record_from_item(item)
    if rec is None:
        logger.error("Não foi possível extrair id/nome do JSON para paciente=%s", patient_id)
        return 1
    ext_id, display, meta = rec
    with psycopg.connect(settings.database_url) as conn:
        upsert_patient(
            conn,
            source_system=SOURCE,
            external_id=ext_id,
            display_name=display,
            metadata=meta,
        )
    logger.info("sync-patient-detail OK external_id=%s", ext_id)
    return 0


def sync_patient_list(
    settings: Settings,
    *,
    take: int = 10,
    max_pages: int = 1,
    is_active: bool | None = True,
) -> int:
    if not settings.dietbox_bearer_token:
        logger.error("Defina DIETBOX_BEARER_TOKEN no .env")
        return 2
    c = _client(settings)
    total_upsert = 0
    skip = 0
    pages = 0
    while pages < max_pages:
        q: dict[str, str | int | bool] = {
            "skip": skip,
            "take": take,
            "order": "name",
        }
        if is_active is not None:
            q["IsActive"] = str(is_active).lower()
        qs = urllib.parse.urlencode(q)
        path = f"v2/paciente?{qs}"
        status, raw = c.get_path(path)
        if status != 200:
            logger.error("Lista pacientes HTTP=%s path=%s corpo=%r", status, path, raw[:300])
            return 1
        data = parse_json_body(raw)
        if isinstance(data, dict) and data.get("Success") is False:
            logger.error(
                "Dietbox Success=false: %s",
                data.get("Message") or data.get("message") or data,
            )
            return 1
        items = extract_list_payload(data)
        if not items:
            logger.info("sync-list: skip=%s sem itens (fim ou formato inesperado)", skip)
            if isinstance(data, dict):
                logger.info("Chaves no topo do JSON: %s", list(data.keys()))
                dv = data.get("Data", data.get("data"))
                logger.info(
                    "Campo Data: tipo=%s",
                    type(dv).__name__ if dv is not None else "None (null ou ausente)",
                )
                if isinstance(dv, list):
                    logger.info("len(Data)=%s (lista de pacientes vazia?)", len(dv))
                elif isinstance(dv, dict):
                    logger.info(
                        "Chaves dentro de Data: %s",
                        list(dv.keys())[:30],
                    )
                    for k in ("TotalItems", "totalItems", "Items", "items"):
                        if k in dv:
                            logger.info("Data.%s = %r", k, dv.get(k))
                if data.get("Success") is True:
                    logger.info(
                        "Dica: lista vazia com Success=true costuma ser filtro IsActive "
                        "(tenta --include-inactive ou --inactive-only)."
                    )
            elif data is not None:
                logger.info("Tipo do JSON raiz: %s", type(data).__name__)
            break
        with psycopg.connect(settings.database_url) as conn:
            for item in items:
                rec = patient_record_from_item(item)
                if rec is None:
                    continue
                ext_id, display, meta = rec
                upsert_patient(
                    conn,
                    source_system=SOURCE,
                    external_id=ext_id,
                    display_name=display,
                    metadata=meta,
                )
                total_upsert += 1
        pages += 1
        if len(items) < take:
            break
        skip += take
    logger.info("sync-list concluído: upserts=%s páginas=%s", total_upsert, pages)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Conector Dietbox — API v2")
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Smoke GET subscription (cron); exit 3 se HTTP 401; opcional NUTRIDEBY_SMOKE_ALERT_WEBHOOK_URL",
    )
    p.add_argument("--probe", metavar="PACIENTE_ID", help="Testa GET prontuário")
    p.add_argument(
        "--meta",
        metavar="PACIENTE_ID",
        help="Testa GET /v2/meta (linha do tempo; Data.Items paginado)",
    )
    p.add_argument(
        "--meta-take",
        type=int,
        default=50,
        help="take na query /v2/meta (--meta, --sync-meta-patient, --sync-meta-all)",
    )
    p.add_argument(
        "--meta-skip",
        type=int,
        default=0,
        help="skip na query /v2/meta (com --meta)",
    )
    p.add_argument(
        "--meta-max-pages",
        type=int,
        default=100,
        help="Máximo de páginas /v2/meta por paciente (--sync-meta-patient / --sync-meta-all)",
    )
    p.add_argument(
        "--sync-meta-patient",
        metavar="PACIENTE_ID",
        help="Pagina GET /v2/meta e grava JSON em documents (doc_type=dietbox_meta_export)",
    )
    p.add_argument(
        "--sync-meta-all",
        action="store_true",
        help="Todos os patients dietbox: export meta por paciente (pausa --meta-all-sleep-ms)",
    )
    p.add_argument(
        "--meta-all-limit",
        type=int,
        default=0,
        metavar="N",
        help="Máximo de pacientes com --sync-meta-all (0 = todos)",
    )
    p.add_argument(
        "--meta-all-sleep-ms",
        type=int,
        default=350,
        help="Pausa entre pacientes com --sync-meta-all",
    )
    p.add_argument(
        "--formula-imc",
        type=float,
        default=None,
        metavar="IMC",
        help="Com --formula-idade: testa GET Formulas/SituacaoIMC no site dietbox.me",
    )
    p.add_argument(
        "--formula-idade",
        type=int,
        default=None,
        metavar="ANOS",
        help="Idade em anos (com --formula-imc)",
    )
    p.add_argument(
        "--sync-formula-imc-all",
        action="store_true",
        help="Todos os pacientes dietbox na base: IMC+idade → SituacaoIMC → documents",
    )
    p.add_argument(
        "--formula-limit",
        type=int,
        default=0,
        help="Máximo de pacientes a processar (0 = todos)",
    )
    p.add_argument(
        "--formula-dry-run",
        action="store_true",
        help="Só pedidos HTTP + logs; não grava documents",
    )
    p.add_argument(
        "--formula-no-fetch",
        action="store_true",
        help="Não chama GET /v2/paciente/{id} (usa só metadata já na base)",
    )
    p.add_argument(
        "--formula-workers",
        type=int,
        default=4,
        help="Pedidos paralelos (1 = sequencial; reduzir se houver 429)",
    )
    p.add_argument(
        "--feed-list",
        action="store_true",
        help="Testa GET site /{locale}/Feed/List (actividade global)",
    )
    p.add_argument(
        "--subscription",
        action="store_true",
        help="Testa GET api /v2/nutritionist/subscription (subscrição; só log)",
    )
    p.add_argument(
        "--sync-subscription",
        action="store_true",
        help="GET subscription e grava JSON em external_snapshots (requer migração 002)",
    )
    p.add_argument(
        "--sync-prontuario-all",
        action="store_true",
        help="Prontuário para todos os patients dietbox; regista extraction_runs (pausa sleep entre pedidos)",
    )
    p.add_argument(
        "--prontuario-limit",
        type=int,
        default=0,
        metavar="N",
        help="Máximo de pacientes por execução (0 = todos os que couberem na query)",
    )
    p.add_argument(
        "--prontuario-sleep-ms",
        type=int,
        default=250,
        help="Pausa entre pedidos HTTP (rate limit)",
    )
    p.add_argument(
        "--prontuario-resume-run-id",
        type=uuid.UUID,
        default=None,
        metavar="UUID",
        help="Retoma último cursor (last_external_id) na mesma linha extraction_runs",
    )
    p.add_argument(
        "--sync-one",
        metavar="PACIENTE_ID",
        help="Grava prontuário (200/204) em documents + paciente",
    )
    p.add_argument(
        "--sync-patient",
        metavar="PACIENTE_ID",
        help="GET /v2/paciente/{id} e upsert só em patients (nome/metadata)",
    )
    p.add_argument(
        "--sync-list",
        action="store_true",
        help="Lista paginada GET /v2/paciente → patients",
    )
    p.add_argument("--take", type=int, default=10)
    p.add_argument("--max-pages", type=int, default=1)
    act = p.add_mutually_exclusive_group()
    act.add_argument(
        "--include-inactive",
        action="store_true",
        help="Não envia IsActive (todos os estados)",
    )
    act.add_argument(
        "--inactive-only",
        action="store_true",
        help="IsActive=false — alinha ao browser quando a lista são só inactivos",
    )
    args = p.parse_args(argv)
    settings = Settings()

    if args.smoke:
        return run_dietbox_smoke(settings)
    if args.probe:
        return probe_prontuario(settings, args.probe)
    if args.meta:
        return probe_meta(
            settings,
            args.meta,
            skip=args.meta_skip,
            take=args.meta_take,
        )
    if args.sync_meta_patient:
        return sync_meta_for_patient(
            settings,
            args.sync_meta_patient,
            take=max(1, args.meta_take),
            max_pages=max(1, args.meta_max_pages),
        )
    if args.sync_meta_all:
        lim = args.meta_all_limit if args.meta_all_limit > 0 else None
        return sync_meta_all(
            settings,
            take=max(1, args.meta_take),
            max_pages_per_patient=max(1, args.meta_max_pages),
            patient_limit=lim,
            sleep_ms=max(0, args.meta_all_sleep_ms),
        )
    if args.formula_imc is not None or args.formula_idade is not None:
        if args.formula_imc is None or args.formula_idade is None:
            logger.error("Use --formula-imc IMC e --formula-idade ANOS em conjunto.")
            return 2
        return probe_formula_imc(settings, args.formula_imc, args.formula_idade)
    if args.sync_formula_imc_all:
        lim = args.formula_limit if args.formula_limit > 0 else None
        return sync_formula_imc_all(
            settings,
            limit=lim,
            dry_run=args.formula_dry_run,
            fetch_patient=not args.formula_no_fetch,
            max_workers=max(1, args.formula_workers),
        )
    if args.feed_list:
        return probe_feed_list(settings)
    if args.sync_subscription:
        return sync_subscription_persist(settings)
    if args.subscription:
        return probe_subscription(settings)
    if args.sync_prontuario_all:
        lim = args.prontuario_limit if args.prontuario_limit > 0 else None
        return sync_prontuario_all(
            settings,
            limit=lim,
            sleep_ms=max(0, args.prontuario_sleep_ms),
            resume_run_id=args.prontuario_resume_run_id,
        )
    if args.sync_one:
        return sync_one_prontuario(settings, args.sync_one)
    if args.sync_patient:
        return sync_one_patient_detail(settings, args.sync_patient)
    if args.sync_list:
        if args.inactive_only:
            list_active: bool | None = False
        elif args.include_inactive:
            list_active = None
        else:
            list_active = True
        return sync_patient_list(
            settings,
            take=args.take,
            max_pages=args.max_pages,
            is_active=list_active,
        )
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""
NutriDeby — Onboarding Workers (RQ)
Cada worker é uma função Python chamada pelo Redis Queue.
Padrão: decripta credencial em memória → extrai → normaliza → POST /api/importar → atualiza job.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import psycopg
import requests

logger = logging.getLogger(__name__)


# ─── Helpers de job ──────────────────────────────────────────────────────────

def _update_job(conn: psycopg.Connection, job_id: str, **kwargs) -> None:
    """Atualiza campos do job em onboarding_jobs."""
    if not kwargs:
        return
    sets = ", ".join(f"{k} = %s" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with conn.cursor() as cur:
        cur.execute(f"UPDATE onboarding_jobs SET {sets} WHERE id = %s::uuid", vals)
    conn.commit()


def _get_credential(conn: psycopg.Connection, credential_id: str) -> dict:
    """Lê credencial do banco e decripta em memória."""
    from nutrideby.onboarding.vault import decrypt
    with conn.cursor() as cur:
        cur.execute(
            "SELECT platform, username, cred_enc, cred_nonce, extra_config FROM onboarding_credentials WHERE id = %s::uuid",
            (credential_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Credencial {credential_id} não encontrada.")
        platform, username, cred_enc, cred_nonce, extra_config = row
        password = decrypt(bytes(cred_enc), bytes(cred_nonce))
        return {
            "platform": platform,
            "username": username,
            "password": password,
            "extra_config": extra_config or {},
        }


def _post_importar(database_url: str, api_url: str, api_key: str,
                   platform: str, pacientes: list[dict]) -> dict:
    """Chama POST /api/importar com o JSON unificado."""
    payload = {
        "source_platform": platform,
        "data_exportacao": datetime.now(timezone.utc).isoformat(),
        "total": len(pacientes),
        "pacientes": pacientes,
    }
    resp = requests.post(
        f"{api_url}/api/importar",
        json=payload,
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Worker principal (dispatcher) ───────────────────────────────────────────

def run_import_job(
    job_id: str,
    credential_id: str,
    nutritionist_id: str,
    platform: str,
    database_url: str,
) -> None:
    """
    Função principal chamada pelo RQ.
    Despacha para o worker correto baseado na plataforma.
    """
    conn = psycopg.connect(database_url)
    try:
        _update_job(conn, job_id,
                    status="running",
                    started_at=datetime.now(timezone.utc))

        cred = _get_credential(conn, credential_id)
        platform = cred["platform"]

        api_url = os.environ.get("NUTRIDEBY_API_URL", "http://localhost:8081")
        api_key = os.environ.get("NUTRIDEBY_API_KEY", "")

        # Despachar para worker correto
        if platform == "dietbox":
            pacientes, total = _extract_dietbox(cred, job_id, conn)
        elif platform == "nutricloud":
            pacientes, total = _extract_nutricloud(cred, job_id, conn)
        elif platform == "dietsmart":
            pacientes, total = _extract_dietsmart_csv(cred, job_id, conn)
        else:
            raise NotImplementedError(f"Worker para '{platform}' ainda não implementado.")

        _update_job(conn, job_id, progress=80, total_records=total)

        # Importar via API
        result = _post_importar(database_url, api_url, api_key, platform, pacientes)

        _update_job(conn, job_id,
                    status="done",
                    progress=100,
                    processed=result.get("total_recebidos", total),
                    inserted=result.get("inseridos", 0),
                    updated=result.get("atualizados", 0),
                    errors=json.dumps(result.get("erros", []), ensure_ascii=False),
                    finished_at=datetime.now(timezone.utc),
                    log=f"Importação concluída: {result.get('inseridos',0)} inseridos, "
                        f"{result.get('atualizados',0)} atualizados.")

        logger.info(f"Job {job_id} concluído: {result}")

    except Exception as e:
        logger.error(f"Job {job_id} falhou: {e}", exc_info=True)
        try:
            _update_job(conn, job_id,
                        status="error",
                        finished_at=datetime.now(timezone.utc),
                        log=str(e)[:2000])
        except Exception:
            pass
    finally:
        conn.close()


# ─── Worker Dietbox ───────────────────────────────────────────────────────────

def _extract_dietbox(cred: dict, job_id: str, conn: psycopg.Connection) -> tuple[list[dict], int]:
    """
    Extrai pacientes do Dietbox via API REST.
    Usa o extrator existente em scripts/extractors/dietbox_extractor.py.
    """
    sys.path.insert(0, "/opt/automa-aoNutriDeby/scripts/extractors")
    try:
        from dietbox_extractor import DietboxExtractor
        extractor = DietboxExtractor(
            username=cred["username"],
            password=cred["password"],
            base_url=cred["extra_config"].get("base_url", "https://api.dietbox.me"),
        )
        pacientes = extractor.extract_all()
        _update_job(conn, job_id, progress=60, total_records=len(pacientes))
        return pacientes, len(pacientes)
    except ImportError:
        # Fallback: chamar script diretamente via subprocess
        import subprocess, tempfile, json as _json
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        subprocess.run([
            sys.executable,
            "/opt/automa-aoNutriDeby/scripts/extractors/dietbox_extractor.py",
            "--username", cred["username"],
            "--password", cred["password"],
            "--output", out_path,
        ], check=True, timeout=600)
        with open(out_path) as f:
            data = _json.load(f)
        pacientes = data.get("pacientes", [])
        return pacientes, len(pacientes)


# ─── Worker NutriCloud ────────────────────────────────────────────────────────

def _extract_nutricloud(cred: dict, job_id: str, conn: psycopg.Connection) -> tuple[list[dict], int]:
    """Extrai pacientes do NutriCloud via CSV."""
    sys.path.insert(0, "/opt/automa-aoNutriDeby/scripts/extractors")
    try:
        from nutricloud_extractor import NutriCloudExtractor
        extractor = NutriCloudExtractor(
            username=cred["username"],
            password=cred["password"],
        )
        pacientes = extractor.extract_all()
        return pacientes, len(pacientes)
    except ImportError:
        raise NotImplementedError("NutriCloud extractor não disponível no path do worker.")


# ─── Worker DietSmart (CSV fallback) ─────────────────────────────────────────

def _extract_dietsmart_csv(cred: dict, job_id: str, conn: psycopg.Connection) -> tuple[list[dict], int]:
    """
    DietSmart via CSV exportado.
    O CSV deve ter sido enviado via upload e o path estar em extra_config['csv_path'].
    """
    csv_path = cred["extra_config"].get("csv_path")
    if not csv_path:
        raise ValueError("DietSmart requer csv_path em extra_config. Faça upload do CSV primeiro.")
    sys.path.insert(0, "/opt/automa-aoNutriDeby/scripts/extractors")
    from dietsmart_extractor import DietSmartExtractor
    extractor = DietSmartExtractor(csv_path=csv_path)
    pacientes = extractor.extract_all()
    return pacientes, len(pacientes)

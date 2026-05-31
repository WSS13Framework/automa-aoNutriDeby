"""
Token Watchdog — NutriDeby SaaS

Roda como cron (diariamente) e:
1. Verifica credenciais que expiram em < 7 dias
2. Tenta validar tokens "pending" ou "valid" com uma chamada de smoke
3. Marca como "expired" se a chamada falhar (HTTP 401)
4. Notifica o nutricionista via WhatsApp com instruções de renovação

Uso:
  python3 -m nutrideby.workers.token_watchdog
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import ssl
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://nutrideby:nutrideby_dev@postgres:5432/nutrideby")
VAULT_KEY = os.getenv("ONBOARDING_VAULT_KEY", "")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM_NUMBER", "")


def _decrypt(encrypted: bytes) -> str:
    key = (VAULT_KEY * ((len(encrypted) // len(VAULT_KEY)) + 1))[:len(encrypted)]
    return bytes(a ^ b for a, b in zip(encrypted, key.encode())).decode()


def _smoke_dietbox(token: str) -> bool:
    """Retorna True se o token ainda é válido."""
    req = urllib.request.Request(
        "https://api.dietbox.me/v2/nutritionist/subscription",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                 "Origin": "https://dietbox.me"},
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        return e.code != 401
    except Exception:
        return False  # rede — não marca como expirado


def _notify_whatsapp(phone: str, name: str, platform: str, days_left: int | None) -> None:
    """Envia alerta de token expirando via Twilio."""
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, phone]):
        return
    from twilio.rest import Client
    msg = (
        f"⚠️ {name}, seu token do {platform.title()} "
        + (f"expira em {days_left} dias." if days_left else "expirou.")
        + "\n\nPara renovar:\n"
        "1. Acesse o Dietbox no navegador\n"
        "2. Abra DevTools (F12) → Aba Network\n"
        "3. Recarregue a página\n"
        "4. Clique em qualquer requisição para api.dietbox.me\n"
        "5. Copie o valor depois de 'Bearer ' no header Authorization\n"
        "6. Cole em: https://app.nutrideby.com/credenciais\n\n"
        "_NutriDeby_ 🥗"
    )
    try:
        Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
            from_=TWILIO_FROM, body=msg, to=f"whatsapp:{phone}"
        )
        logger.info("Alerta enviado para %s", phone)
    except Exception as e:
        logger.warning("Falha ao notificar %s: %s", phone, e)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    logger.info("Token watchdog iniciado")

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pc.id, pc.platform, pc.credential_type, pc.encrypted_data,
                       pc.expires_at, pc.validation_status,
                       a.name, a.email,
                       (SELECT pp.phone FROM patient_phones pp
                        WHERE pp.account_id = a.id LIMIT 1) AS phone
                FROM platform_credentials pc
                JOIN accounts a ON a.id = pc.account_id
                WHERE pc.validation_status IN ('valid', 'pending')
                ORDER BY pc.expires_at ASC NULLS LAST
            """)
            creds = cur.fetchall()

        logger.info("Verificando %d credenciais", len(creds))

        for cred in creds:
            cred_id = cred["id"]
            days_left = None
            if cred["expires_at"]:
                days_left = (cred["expires_at"] - datetime.now()).days

            # Só notifica se expira em < 7 dias
            should_alert = days_left is not None and days_left <= 7

            # Smoke test
            try:
                data = json.loads(_decrypt(bytes(cred["encrypted_data"])))
                token = data.get("bearer_token", "")
            except Exception:
                token = ""

            if not token:
                continue

            valid = _smoke_dietbox(token) if cred["platform"] == "dietbox" else True

            new_status = "valid" if valid else "expired"

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE platform_credentials
                    SET validation_status = %s,
                        last_validated_at = now(),
                        error_message = CASE WHEN %s = 'expired'
                            THEN 'Token rejeitado pela API (HTTP 401)'
                            ELSE NULL END
                    WHERE id = %s
                    """,
                    (new_status, new_status, cred_id),
                )
                conn.commit()

            if not valid or should_alert:
                _notify_whatsapp(
                    cred.get("phone") or "",
                    cred["name"],
                    cred["platform"],
                    days_left if valid else None,
                )
                logger.info(
                    "Alerta: conta=%s platform=%s status=%s days_left=%s",
                    cred["email"], cred["platform"], new_status, days_left,
                )

    logger.info("Token watchdog concluído")


if __name__ == "__main__":
    run()

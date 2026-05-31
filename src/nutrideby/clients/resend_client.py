"""Cliente Resend para e-mails transacionais (convite + reset de senha)."""
from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def send_email(
    *,
    api_key: str,
    from_email: str,
    to: str,
    subject: str,
    html: str,
) -> bool:
    """Envia e-mail via Resend. Retorna True se enviado, False se falhou."""
    if not api_key:
        logger.warning("RESEND_API_KEY não configurada — e-mail não enviado para %s", to)
        logger.info("SIMULANDO e-mail: subject=%s to=%s", subject, to)
        return False

    body = json.dumps({"from": from_email, "to": [to], "subject": subject, "html": html}).encode()
    req = urllib.request.Request(_RESEND_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", "Mozilla/5.0")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            resp = json.loads(r.read().decode())
            logger.info("Resend ok: id=%s to=%s", resp.get("id"), to)
            return True
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") if e.fp else ""
        logger.error("Resend HTTP %s: %s", e.code, raw[:300])
        return False
    except Exception as exc:
        logger.error("Resend erro: %s", exc)
        return False


# ── Templates ─────────────────────────────────────────────────────────────────

def _base_html(title: str, body_content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title></head>
<body style="margin:0;padding:0;background:#f0fdf4;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:40px 16px">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
      <tr><td style="background:#059669;padding:24px 32px">
        <span style="color:#fff;font-size:22px;font-weight:700">🥗 NutriDeby</span>
        <span style="color:#a7f3d0;font-size:13px;margin-left:8px">Nutrição Funcional Inteligente</span>
      </td></tr>
      <tr><td style="padding:32px">
        {body_content}
      </td></tr>
      <tr><td style="background:#f8fafc;padding:16px 32px;text-align:center">
        <span style="color:#94a3b8;font-size:11px">© 2026 NutriDeby · Este e-mail foi enviado automaticamente, não responda.</span>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def invite_email_html(name: str, invite_url: str) -> str:
    body = f"""
    <h2 style="color:#059669;margin:0 0 8px">Bem-vinda, {name}! 👋</h2>
    <p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 24px">
      Você foi adicionada como nutricionista no <strong>NutriDeby</strong>.<br/>
      Clique no botão abaixo para criar sua senha e acessar o painel.
    </p>
    <a href="{invite_url}" style="display:inline-block;background:#059669;color:#fff;text-decoration:none;padding:14px 28px;border-radius:8px;font-weight:700;font-size:15px">
      Criar minha senha →
    </a>
    <p style="color:#94a3b8;font-size:12px;margin:24px 0 0">
      Este link expira em <strong>48 horas</strong>. Se não foi você, ignore este e-mail.
    </p>"""
    return _base_html("Convite NutriDeby", body)


def reset_email_html(name: str, reset_url: str) -> str:
    body = f"""
    <h2 style="color:#1e293b;margin:0 0 8px">Redefinir senha</h2>
    <p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 8px">
      Olá, <strong>{name}</strong>. Recebemos uma solicitação para redefinir sua senha.
    </p>
    <p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 24px">
      Clique no botão abaixo para criar uma nova senha:
    </p>
    <a href="{reset_url}" style="display:inline-block;background:#059669;color:#fff;text-decoration:none;padding:14px 28px;border-radius:8px;font-weight:700;font-size:15px">
      Redefinir senha →
    </a>
    <p style="color:#94a3b8;font-size:12px;margin:24px 0 0">
      Este link expira em <strong>1 hora</strong>. Se não foi você, ignore este e-mail — sua senha não será alterada.
    </p>"""
    return _base_html("Redefinir senha — NutriDeby", body)

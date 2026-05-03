"""
Heurísticas para JSON de webhook Kiwify (painel → POST).

A Kiwify não publica um schema único estável no código; este módulo tenta
vários caminhos comuns. Quando receberes payloads reais, confirma as chaves
no log do worker e, se necessário, estende ``_event_candidates`` /
``_order_id_candidates`` / ``_customer_blob``.
"""

from __future__ import annotations

import re
from typing import Any

# Eventos explícitos (normalizados) de compra aprovada.
_APPROVED_EVENTS = frozenset(
    {
        "compra_aprovada",
        "purchase_approved",
        "order_approved",
        "payment_approved",
    }
)


def _norm_event(s: str) -> str:
    t = s.strip().lower()
    t = re.sub(r"\s+", "_", t)
    return t


def _event_from_payload(d: dict[str, Any]) -> str | None:
    keys = (
        "webhook_event",
        "event",
        "type",
        "order_status",
        "status",
        "event_type",
        "trigger",
    )
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return _norm_event(v)
    return None


def _dig(d: dict[str, Any], *path: str) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _order_id_from_payload(d: dict[str, Any]) -> str | None:
    direct = (
        "order_id",
        "orderId",
        "order_ref",
        "OrderId",
        "sale_id",
        "SaleId",
        "reference",
    )
    for k in direct:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    for path in (
        ("order", "id"),
        ("order", "order_id"),
        ("Order", "id"),
        ("data", "order_id"),
        ("data", "id"),
        ("sale", "id"),
        ("purchase", "id"),
    ):
        v = _dig(d, *path)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _customer_blob(d: dict[str, Any]) -> dict[str, Any] | None:
    for k in ("Customer", "customer", "buyer", "client", "comprador", "data"):
        v = d.get(k)
        if isinstance(v, dict) and v:
            if any(x in v for x in ("email", "Email", "name", "fullname", "full_name")):
                return v
    inner = _dig(d, "order", "customer")
    if isinstance(inner, dict):
        return inner
    inner = _dig(d, "data", "customer")
    if isinstance(inner, dict):
        return inner
    return None


def _str_field(blob: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = blob.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def parse_kiwify_purchase(payload: Any) -> dict[str, Any] | None:
    """
    Se o JSON for reconhecido como compra aprovada com ``order_id``, devolve::

        {
          "event": str,
          "order_id": str,
          "display_name": str | None,
          "email": str | None,
          "phone": str | None,
          "product_id": str | None,
        }

    Caso contrário ``None`` (evento diferente ou dados insuficientes).
    """
    if not isinstance(payload, dict):
        return None
    event = _event_from_payload(payload)
    if not event:
        return None
    if not _is_compra_aprovada_event(event):
        return None
    oid = _order_id_from_payload(payload)
    if not oid:
        return None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    product_id: str | None = None
    cb = _customer_blob(payload)
    if cb:
        name = _str_field(cb, "fullname", "full_name", "name", "nome", "FullName")
        email = _str_field(cb, "email", "Email", "mail")
        phone = _str_field(cb, "mobile", "phone", "telefone", "whatsapp", "Mobile")
    if not name:
        name = _str_field(payload, "customer_name", "buyer_name", "nome")
    if not email:
        email = _str_field(payload, "email", "customer_email")
    prod = (
        payload.get("product_id")
        or payload.get("productId")
        or _dig(payload, "order", "product_id")
        or _dig(payload, "product", "id")
    )
    if prod is not None and str(prod).strip():
        product_id = str(prod).strip()
    return {
        "event": event,
        "order_id": oid,
        "display_name": name,
        "email": email,
        "phone": phone,
        "product_id": product_id,
    }


def is_compra_aprovada_payload(payload: Any) -> bool:
    return parse_kiwify_purchase(payload) is not None


def _is_compra_aprovada_event(event: str) -> bool:
    e = event.strip().lower().replace(" ", "_")
    if e in _APPROVED_EVENTS:
        return True
    if "compra" in e and "aprov" in e:
        return True
    if "purchase" in e and "approv" in e:
        return True
    return False

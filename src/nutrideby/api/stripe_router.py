"""stripe_router.py — Monetização NutriDeby (Stripe Subscriptions)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

import psycopg
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.rows import dict_row

from nutrideby.api.deps import get_settings
from nutrideby.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


def _get_patient(conn, patient_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, display_name, email, stripe_customer_id, stripe_subscription_id, "
            "subscription_status, trial_ends_at, subscription_ends_at FROM patients WHERE id = %s",
            (patient_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")
    return row


@router.post("/create-checkout/{patient_id}")
def create_checkout(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe não configurado (STRIPE_SECRET_KEY ausente)")
    stripe.api_key = settings.stripe_secret_key

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        patient = _get_patient(conn, patient_id)

        customer_id = patient["stripe_customer_id"]
        if not customer_id:
            customer = stripe.Customer.create(
                email=patient["email"] or "",
                name=patient["display_name"] or "",
                metadata={"patient_id": patient_id},
            )
            customer_id = customer["id"]
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE patients SET stripe_customer_id = %s WHERE id = %s",
                    (customer_id, patient_id),
                )
                conn.commit()

    if not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="STRIPE_PRICE_ID não configurado")

    base_url = settings.app_base_url or "https://app.nutrideby.com.br"
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/payment/cancel",
        metadata={"patient_id": patient_id},
    )

    logger.info("checkout criado patient=%s session=%s", patient_id, session["id"])
    return {"checkout_url": session["url"], "session_id": session["id"]}


@router.post("/customer-portal/{patient_id}")
def customer_portal(
    patient_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe não configurado (STRIPE_SECRET_KEY ausente)")
    stripe.api_key = settings.stripe_secret_key

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        patient = _get_patient(conn, patient_id)

    if not patient["stripe_customer_id"]:
        raise HTTPException(status_code=400, detail="Paciente não possui conta Stripe ainda")

    base_url = settings.app_base_url or "https://app.nutrideby.com.br"
    portal = stripe.billing_portal.Session.create(
        customer=patient["stripe_customer_id"],
        return_url=f"{base_url}/settings",
    )
    return {"portal_url": portal["url"]}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET não configurado")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except stripe.error.SignatureVerificationError:
        logger.warning("stripe webhook: assinatura inválida")
        raise HTTPException(status_code=400, detail="Assinatura inválida")

    ev_type = event["type"]
    logger.info("stripe event: %s", ev_type)

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            if ev_type == "checkout.session.completed":
                session = event["data"]["object"]
                pid = (session.get("metadata") or {}).get("patient_id")
                sub_id = session.get("subscription")
                if pid and sub_id:
                    cur.execute(
                        """UPDATE patients SET stripe_subscription_id = %s,
                           subscription_status = 'active', subscription_ends_at = NULL
                           WHERE id = %s""",
                        (sub_id, pid),
                    )
                    logger.info("checkout.completed patient=%s sub=%s", pid, sub_id)

            elif ev_type == "customer.subscription.updated":
                sub = event["data"]["object"]
                status_map = {
                    "active": "active", "past_due": "past_due",
                    "canceled": "canceled", "unpaid": "expired", "trialing": "trial",
                }
                new_status = status_map.get(sub["status"], sub["status"])
                ends_at = None
                if sub.get("current_period_end"):
                    ends_at = datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc)
                cur.execute(
                    """UPDATE patients SET subscription_status = %s, subscription_ends_at = %s
                       WHERE stripe_subscription_id = %s""",
                    (new_status, ends_at, sub["id"]),
                )

            elif ev_type == "customer.subscription.deleted":
                sub = event["data"]["object"]
                ends_at = None
                if sub.get("current_period_end"):
                    ends_at = datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc)
                cur.execute(
                    """UPDATE patients SET subscription_status = 'canceled',
                       subscription_ends_at = %s WHERE stripe_subscription_id = %s""",
                    (ends_at, sub["id"]),
                )

            conn.commit()

    return {"received": True}

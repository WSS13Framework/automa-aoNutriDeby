"""waitlist_router.py — Landing page de pré-lançamento NutriDeby."""
from __future__ import annotations

import logging
import secrets
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

from nutrideby.api.deps import get_settings
from nutrideby.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])

BASE_URL = "https://nutrideby.com.br"


class WaitlistRegisterRequest(BaseModel):
    name: str
    phone: str
    email: str
    ref: str | None = None


def get_user_position(user_id: str, conn) -> int:
    with conn.cursor(row_factory=None) as cur:
        cur.execute(
            """SELECT COUNT(*) + 1 AS position FROM waitlist_users
               WHERE points > (SELECT points FROM waitlist_users WHERE id = %s)
               OR (
                 points = (SELECT points FROM waitlist_users WHERE id = %s)
                 AND created_at < (SELECT created_at FROM waitlist_users WHERE id = %s)
               )""",
            (user_id, user_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return 1
        v = row.get("position") if hasattr(row, "get") else row[0]
        return int(v)


@router.post("/register", status_code=201)
def waitlist_register(
    payload: WaitlistRegisterRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM waitlist_users WHERE email = %s", (payload.email,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Email já cadastrado na waitlist")

            if payload.ref:
                cur.execute(
                    "SELECT id FROM waitlist_users WHERE referral_code = %s", (payload.ref.upper(),)
                )
                referrer = cur.fetchone()
                if referrer:
                    cur.execute(
                        "UPDATE waitlist_users SET points = points + 10 WHERE id = %s",
                        (str(referrer["id"]),),
                    )

            code = secrets.token_urlsafe(6).upper()
            cur.execute(
                """INSERT INTO waitlist_users (name, phone, email, referral_code, referred_by, points)
                   VALUES (%s, %s, %s, %s, %s, 0) RETURNING id""",
                (payload.name, payload.phone, payload.email, code, payload.ref),
            )
            new_id = str(cur.fetchone()["id"])
            conn.commit()

        position = get_user_position(new_id, conn)

    logger.info("waitlist register email=%s position=%d", payload.email, position)
    return {
        "message": "Cadastro realizado! Indique amigos para subir na fila.",
        "position": position,
        "referral_code": code,
        "share_link": f"{BASE_URL}/?ref={code}",
    }


@router.get("/position/{user_id}")
def get_position(
    user_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, referral_code, points FROM waitlist_users WHERE id = %s",
                (user_id,),
            )
            user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        position = get_user_position(user_id, conn)

    return {
        "position": position,
        "points": user["points"],
        "referral_code": user["referral_code"],
        "share_link": f"{BASE_URL}/?ref={user['referral_code']}",
    }


import os as _os
from fastapi.responses import HTMLResponse as _HTMLResponse

_HTML_FILE = _os.path.join(_os.path.dirname(__file__), "waitlist_index.html")


@router.get("/", response_class=_HTMLResponse, include_in_schema=False)
def waitlist_landing() -> _HTMLResponse:
    with open(_HTML_FILE, encoding="utf-8") as f:
        return _HTMLResponse(content=f.read())

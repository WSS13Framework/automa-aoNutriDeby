"""Dependências FastAPI partilhadas (evita import circular main ↔ analyze)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from nutrideby.config import Settings


def get_settings() -> Settings:
    return Settings()


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    expected = settings.nutrideby_api_key
    if not (expected and str(expected).strip()):
        return
    if not x_api_key or x_api_key.strip() != str(expected).strip():
        raise HTTPException(status_code=401, detail="X-API-Key inválida ou em falta")

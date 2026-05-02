"""Cliente HTTP para api.dietbox.me (Bearer JWT) + helpers de parsing JSON."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class DietboxClient:
    """Pedidos GET com cabeçalhos alinhados ao browser (CORS / API Dietbox)."""

    def __init__(self, base_url: str, bearer_token: str) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self._token = bearer_token

    def _request(self, method: str, path: str) -> tuple[int, bytes]:
        url = urljoin(self.base_url, path.lstrip("/"))
        req = urllib.request.Request(
            url,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json, text/javascript, */*;q=0.01",
                "Origin": "https://dietbox.me",
                "Referer": "https://dietbox.me/",
            },
        )
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            body = e.read() if e.fp else b""
            return e.code, body

    def get_path(self, path: str) -> tuple[int, bytes]:
        """GET relativo à base (ex.: v2/paciente?skip=0&take=10)."""
        return self._request("GET", path.lstrip("/"))

    def get_prontuario(self, paciente_id: str) -> tuple[int, bytes]:
        path = f"v2/paciente/{paciente_id}/prontuario"
        return self._request("GET", path)


def request_json(
    method: str,
    url: str,
    *,
    bearer_token: str,
    timeout: int = 60,
) -> tuple[int, bytes]:
    """GET por URL absoluta (sem classe)."""
    req = urllib.request.Request(url, method=method.upper())
    req.add_header("Authorization", f"Bearer {bearer_token}")
    req.add_header("Accept", "application/json")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        return e.code, body


def extract_list_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("data", "items", "results", "records", "value", "patients"):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def patient_record_from_item(item: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]] | None:
    ext = (
        item.get("id")
        or item.get("patientId")
        or item.get("external_id")
        or item.get("externalId")
    )
    if ext is None:
        return None
    ext_s = str(ext).strip()
    if not ext_s:
        return None
    name = (
        item.get("name")
        or item.get("displayName")
        or item.get("nome")
        or item.get("fullName")
        or item.get("patientName")
    )
    display = str(name).strip() if name is not None else None
    if display == "":
        display = None
    meta = {k: v for k, v in item.items() if k not in ("name", "displayName", "nome", "fullName")}
    return ext_s, display, meta


def parse_json_body(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corpo não-JSON (primeiros 200 bytes): %r", raw[:200])
        return None

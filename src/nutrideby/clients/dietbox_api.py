"""Cliente HTTP mínimo para api.dietbox.me (Bearer JWT)."""

from __future__ import annotations

import logging
import ssl
import urllib.error
import urllib.request
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class DietboxClient:
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

    def get_prontuario(self, paciente_id: str) -> tuple[int, bytes]:
        path = f"v2/paciente/{paciente_id}/prontuario"
        return self._request("GET", path)

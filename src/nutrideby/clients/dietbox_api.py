"""Cliente HTTP para api.dietbox.me (Bearer JWT) + helpers de parsing JSON."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def normalize_dietbox_api_base(base_url: str) -> str:
    """Raiz do host só; remove sufixo ``/v2`` para paths poderem usar sempre ``v2/...``."""
    s = (base_url or "").strip().rstrip("/")
    if s.lower().endswith("/v2"):
        s = s[:-3].rstrip("/")
    return s or "https://api.dietbox.me"


def join_dietbox_url(base_url: str, path: str) -> str:
    """
    Junta base + path sem ``v2//segmento`` (ex.: base ``.../v2/`` + ``/nutritionist/...`` no browser).
    Preserva query string. Remove segmentos vazios de ``//`` acidentais no path.
    """
    base = normalize_dietbox_api_base(base_url).rstrip("/")
    raw = (path or "").strip()
    if not raw:
        return base
    if "?" in raw:
        path_only, q = raw.split("?", 1)
        suffix = "?" + q
    else:
        path_only, suffix = raw, ""
    segs = [seg for seg in path_only.split("/") if seg]
    path_clean = "/".join(segs)
    return f"{base}/{path_clean}{suffix}"


class DietboxClient:
    """Pedidos GET com cabeçalhos alinhados ao browser (CORS / API Dietbox)."""

    def __init__(self, base_url: str, bearer_token: str) -> None:
        self._base = normalize_dietbox_api_base(base_url)
        self._token = bearer_token

    def _request(self, method: str, path: str) -> tuple[int, bytes]:
        url = join_dietbox_url(self._base, path)
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
        """GET prontuário; a API pode responder 204 sem corpo. O query ?_= no browser é só cache-bust."""
        path = f"v2/paciente/{paciente_id}/prontuario"
        return self._request("GET", path)

    def get_nutritionist_subscription(self) -> tuple[int, bytes]:
        """GET /v2/nutritionist/subscription (metadados da conta)."""
        return self._request("GET", "v2/nutritionist/subscription")

    def get_meta(self, paciente_id: str, *, skip: int = 0, take: int = 50) -> tuple[int, bytes]:
        """
        Linha do tempo / actividade do paciente na UI (``GET /v2/meta``).

        Query alinhada ao browser: ``idPaciente``, ``skip``, ``take``.
        O JSON pode misturar tipos de evento; confirmar no DevTools se inclui consultas.
        """
        q = urllib.parse.urlencode(
            {"idPaciente": str(paciente_id), "skip": str(skip), "take": str(take)}
        )
        return self._request("GET", f"v2/meta?{q}")


def get_absolute_dietbox_ui(
    url: str,
    bearer_token: str,
    *,
    timeout: int = 60,
    referer: str = "https://dietbox.me/",
) -> tuple[int, bytes]:
    """GET a URL absoluta com cabeçalhos alinhados ao site dietbox.me (ex.: fórmulas MVC, ``food.dietbox.me``)."""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/json, text/javascript, */*;q=0.01",
            "Origin": "https://dietbox.me",
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        body = e.read() if e.fp else b""
        return e.code, body


def get_meal_plan_bases(
    bearer_token: str,
    patient_id: str,
    *,
    skip: int = 0,
    take: int = 5,
    food_base: str = "https://food.dietbox.me",
) -> tuple[int, bytes]:
    """
    Planos alimentares / lembretes (``food.dietbox.me``) — **não** é a agenda de consultas.

    Parâmetros alinhados ao pedido típico da UI.
    """
    q = urllib.parse.urlencode(
        {
            "Skip": str(skip),
            "Take": str(take),
            "PatientId": str(patient_id),
            "IsReminder": "true",
            "OrderBy": "UpdatedAt",
            "SortDirection": "Descending",
        }
    )
    url = f"{food_base.rstrip('/')}/v1/meal-plans/bases?{q}"
    return get_absolute_dietbox_ui(url, bearer_token)


def get_mvc_feed_list(
    bearer_token: str,
    *,
    web_base: str = "https://dietbox.me",
    locale: str = "pt-BR",
) -> tuple[int, bytes]:
    """
    Feed global do site (MVC), ex. ``GET /pt-BR/Feed/List`` — notificações / actividade recente.

    Usa **um** ``/`` entre locale e ``Feed`` (evita ``pt-BR//Feed`` do browser).
    """
    base = web_base.rstrip("/")
    loc = locale.strip().strip("/")
    url = f"{base}/{loc}/Feed/List"
    return get_absolute_dietbox_ui(url, bearer_token, referer=f"{base}/{loc}/Patient")


def get_formula_situacao_imc(
    bearer_token: str,
    *,
    imc: float,
    idade: int,
    web_base: str = "https://dietbox.me",
    locale: str = "pt-BR",
) -> tuple[int, bytes]:
    """
    Fórmula **SituacaoIMC** no site (IIS), não na ``api.dietbox.me``.

    Usa o mesmo ``DIETBOX_BEARER_TOKEN``; **não** persiste cookies ASP.NET.
    Para RAG: gravar o JSON/texto em ``documents`` com ``source_ref`` estável.
    """
    q = urllib.parse.urlencode({"imc": str(imc), "idade": str(idade)})
    base = web_base.rstrip("/")
    loc = locale.strip().strip("/")
    url = f"{base}/{loc}/Formulas/SituacaoIMC?{q}"
    referer = f"{base}/{loc}/"
    return get_absolute_dietbox_ui(url, bearer_token, referer=referer)


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


def extract_dietbox_paged_items(
    data: Any,
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    """
    Envelope paginado típico: ``{ "Data": { "Items": [...], "TotalItems": N, "TotalPages": P } }``.

    Devolve ``(itens_dict_nesta_página, total_items, total_pages)``.
    """
    if not isinstance(data, dict):
        return [], None, None
    inner = data.get("Data") or data.get("data")
    if not isinstance(inner, dict):
        return extract_list_payload(data), None, None

    items: list[dict[str, Any]] = []
    for key in ("Items", "items", "Results", "results"):
        raw = inner.get(key)
        if isinstance(raw, list):
            items = [x for x in raw if isinstance(x, dict)]
            break
    if not items:
        items = extract_list_payload(inner)

    def _as_int(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    total_items = _as_int(inner.get("TotalItems") or inner.get("totalItems"))
    total_pages = _as_int(inner.get("TotalPages") or inner.get("totalPages"))
    return items, total_items, total_pages


def extract_list_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    # Dietbox / .NET: { "Data": [...], "Success": true, "Message": null }
    for key in (
        "Data",
        "data",
        "items",
        "Items",
        "results",
        "Results",
        "records",
        "Records",
        "value",
        "Value",
        "patients",
        "Patients",
    ):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            nested = extract_list_payload(v)
            if nested:
                return nested
    return []


def patient_record_from_item(item: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]] | None:
    ext = (
        item.get("id")
        or item.get("Id")
        or item.get("patientId")
        or item.get("PatientId")
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
        or item.get("Name")
        or item.get("displayName")
        or item.get("DisplayName")
        or item.get("nome")
        or item.get("Nome")
        or item.get("fullName")
        or item.get("FullName")
        or item.get("patientName")
        or item.get("PatientName")
    )
    display = str(name).strip() if name is not None else None
    if display == "":
        display = None
    _skip_meta = {
        "name",
        "Name",
        "displayName",
        "DisplayName",
        "nome",
        "Nome",
        "fullName",
        "FullName",
        "patientName",
        "PatientName",
        "id",
        "Id",
        "patientId",
        "PatientId",
    }
    meta = {k: v for k, v in item.items() if k not in _skip_meta}
    return ext_s, display, meta


def patient_detail_item_from_response(data: Any) -> dict[str, Any] | None:
    """Extrai o dicionário de um único paciente a partir da resposta de ``GET /v2/paciente/{id}``."""
    if not isinstance(data, dict):
        return None
    if patient_record_from_item(data) is not None:
        return data
    found = extract_list_payload(data)
    if len(found) == 1:
        return found[0]
    return None


def parse_birth_date(value: Any) -> date | None:
    """Datas ``YYYY-MM-DD``, ISO com hora, ou ``DD/MM/YYYY`` (comum em CSV PT)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    return None


def age_years_from_birth(birth: date, *, today: date | None = None) -> int:
    t = today or date.today()
    return t.year - birth.year - ((t.month, t.day) < (birth.month, birth.day))


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def extract_imc_idade_from_payload(item: dict[str, Any]) -> tuple[float | None, int | None]:
    """
    Obtém IMC e idade (anos) a partir do JSON de paciente ou de ``metadata`` mesclado.

    Heurísticas: chaves comuns na API .NET + peso/altura + data de nascimento.
    """
    imc: float | None = None
    for k in ("imc", "IMC", "valorImc", "ValorImc", "bodyMassIndex", "BodyMassIndex"):
        x = _as_float(item.get(k))
        if x is not None and 12.0 <= x <= 70.0:
            imc = x
            break
    if imc is None:
        peso = _as_float(item.get("peso") or item.get("Peso") or item.get("weight") or item.get("Weight"))
        alt = _as_float(
            item.get("altura") or item.get("Altura") or item.get("height") or item.get("Height")
        )
        if peso is not None and alt is not None and alt > 0:
            alt_m = alt / 100.0 if alt > 3.0 else alt
            if alt_m > 0.4:
                imc = peso / (alt_m**2)
                if imc is not None and not (12.0 <= imc <= 70.0):
                    imc = None
    idade = _as_int(item.get("idade") or item.get("Idade") or item.get("age") or item.get("Age"))
    if idade is None:
        for bk in (
            "dataNascimento",
            "DataNascimento",
            "birthDate",
            "BirthDate",
            "dataDeNascimento",
            "DataDeNascimento",
        ):
            birth = parse_birth_date(item.get(bk))
            if birth is not None:
                idade = age_years_from_birth(birth)
                break
    return imc, idade


def parse_json_body(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corpo não-JSON (primeiros 200 bytes): %r", raw[:200])
        return None

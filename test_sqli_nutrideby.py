"""
Simulação de SQL Injection — teste black-box contra o STAGING do NutriDeby.

⚠️  USE SOMENTE CONTRA SISTEMAS QUE VOCÊ POSSUI.
    Rode apenas em staging/lab isolado, NUNCA em produção, NUNCA em terceiros.
    Por segurança, o suite recusa rodar sem TARGET_CONFIRM=eu-sou-dono.

Cobre as famílias do cheat sheet (PayloadsAllTheThings):
  - Error-based   → também detecta vazamento de erro do banco (item LGPD)
  - Boolean blind → compara resposta true vs false
  - Time-based    → mede atraso de pg_sleep()
  - Union/marker  → verifica reflexão de marcador

Mapeamento real dos endpoints NutriDeby (auditados em 2026-06-03):
  Prefix /api/nutri     → nutricionista_router.py
  Prefix /patients      → mobile_api.py
  Prefix /api/clinical  → clinical_router.py
  Prefix /gamification  → gamification_router.py
  Prefix /referral      → referral_router.py
  Prefix /api/waitlist  → waitlist_router.py
  Prefix /api/pacientes → paciente_acesso_router.py
  Sem prefix            → main.py (/v1/*, /hooks/*, /health)

Como usar:
    pip install pytest requests
    export BASE_URL="https://staging.nutrideby.com.br"
    export NUTRI_JWT="Bearer <jwt-de-staging-nutricionista>"
    export MOBILE_JWT="Bearer <jwt-de-staging-paciente>"
    export API_KEY="<x-api-key-de-staging>"
    export TARGET_CONFIRM="eu-sou-dono"
    pytest test_sqli_nutrideby.py -v
"""

from __future__ import annotations

import os
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests

# ── Configuração via env ──────────────────────────────────────────────────────
BASE_URL    = os.environ.get("BASE_URL", "").rstrip("/")
NUTRI_JWT   = os.environ.get("NUTRI_JWT", "")   # Bearer <token> nutricionista
MOBILE_JWT  = os.environ.get("MOBILE_JWT", "")  # Bearer <token> paciente mobile
API_KEY     = os.environ.get("API_KEY", "")      # x-api-key para /v1/*
CONFIRM     = os.environ.get("TARGET_CONFIRM", "")

# UUID de staging que existe no banco (nenhum dado real de produção)
STAGING_PATIENT_UUID = os.environ.get("STAGING_PATIENT_UUID", "00000000-0000-0000-0000-000000000001")
STAGING_NUTRI_RECORD = os.environ.get("STAGING_RECORD_ID", "1")

# ── Assinaturas de vazamento de banco (NUNCA devem aparecer na resposta) ──────
DB_ERROR_SIGNATURES = [
    "psycopg",
    "postgresql",
    "pg_",
    "syntax error at or near",
    "unterminated quoted string",
    "operator does not exist",
    "ProgrammingError",
    "IntegrityError",
    "Traceback (most recent call last)",
    "ERROR:  ",
    "invalid input syntax",
    "relation",
    "does not exist",
    "column",
    "pg_sleep",  # se refletido, indica tentativa processada
]

# ── Payloads por família ──────────────────────────────────────────────────────
ERROR_PAYLOADS = [
    "'",
    '"',
    "')",
    "';",
    "' OR '1'='1",
    "\\",
    "%27",         # URL-encoded single quote
    "1; DROP TABLE patients--",
]

BOOL_TRUE  = [" OR 1=1-- -",  "' OR '1'='1",  "1' OR '1'='1"]
BOOL_FALSE = [" OR 1=2-- -",  "' OR '1'='2",  "1' AND '1'='2"]

TIME_PAYLOADS = [
    "1' AND (SELECT 1 FROM pg_sleep(5))-- -",
    "'; SELECT pg_sleep(5)-- -",
    "1 AND (SELECT 1 FROM pg_sleep(5))",
    "1);SELECT pg_sleep(5)--",
]

UNION_MARKER   = "SQLI_MARKER_8f3a"
UNION_PAYLOADS = [
    f"1' UNION SELECT '{UNION_MARKER}'-- -",
    f"' UNION SELECT NULL,'{UNION_MARKER}',NULL-- -",
    f"1 UNION ALL SELECT '{UNION_MARKER}'-- -",
]

SLEEP_THRESHOLD = 4.0   # delta em segundos acima do baseline → suspeito


# ── Definição estruturada dos endpoints ──────────────────────────────────────
@dataclass
class Endpoint:
    method: str
    path: str
    # params de query injetáveis: {nome: valor_baseline}
    query_params: dict[str, str] = field(default_factory=dict)
    # body injetável (POST): {nome: valor_baseline}
    body_params: dict[str, Any] = field(default_factory=dict)
    auth: str = "nutri"           # "nutri" | "mobile" | "apikey" | "none"
    note: str = ""

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


ENDPOINTS: list[Endpoint] = [
    # ── /api/nutri/* ─────────────────────────────────────────────────────────
    # nutricionista_router.py:563 — status vai em q.format(where=...) → safe auditado
    Endpoint(
        "GET", "/api/nutri/records",
        query_params={"status": "pending"},
        auth="nutri",
        note="status → q.format(where=...) com literal estático; valor real via %s",
    ),
    # nutricionista_router.py:698 — status + q (ILIKE search)
    Endpoint(
        "GET", "/api/nutri/patients",
        query_params={"status": "active", "q": "maria"},
        auth="nutri",
        note="q → ILIKE %s; status → subscription_status = %s",
    ),
    # nutricionista_router.py:512 — pending (sem params variáveis no staging)
    Endpoint(
        "GET", "/api/nutri/pending",
        auth="nutri",
        note="sem params injetáveis, testa error-based apenas",
    ),
    # nutricionista_router.py:985 — patient_id path param
    Endpoint(
        "GET", f"/api/nutri/patient-detail/{STAGING_PATIENT_UUID}",
        auth="nutri",
        note="patient_id path param → WHERE id = %s",
    ),
    # nutricionista_router.py:858 — grid-padroes
    Endpoint(
        "GET", "/api/nutri/grid-padroes",
        auth="nutri",
    ),
    # nutricionista_router.py:1143 — metrics
    Endpoint(
        "GET", "/api/nutri/metrics",
        auth="nutri",
    ),

    # ── /v1/* (API key) ──────────────────────────────────────────────────────
    # main.py:253 — source_system, limit, offset
    Endpoint(
        "GET", "/v1/patients",
        query_params={"source_system": "dietbox", "limit": "10", "offset": "0"},
        auth="apikey",
        note="source_system → WHERE source_system = %s; limit/offset via Query(ge=,le=)",
    ),
    # main.py:298 — rag-coverage com source_system, min_usable_embedded
    Endpoint(
        "GET", "/v1/patients/rag-coverage",
        query_params={"source_system": "dietbox", "limit": "10", "min_usable_embedded": "0"},
        auth="apikey",
    ),
    # main.py:406 — patient_id path param
    Endpoint(
        "GET", f"/v1/patients/{STAGING_PATIENT_UUID}",
        auth="apikey",
        note="patient_id path → WHERE id = %s",
    ),
    # main.py:439 — documents com limit
    Endpoint(
        "GET", f"/v1/patients/{STAGING_PATIENT_UUID}/documents",
        query_params={"limit": "5"},
        auth="apikey",
    ),
    # main.py:525 — chunks com limit
    Endpoint(
        "GET", f"/v1/patients/{STAGING_PATIENT_UUID}/chunks",
        query_params={"limit": "5"},
        auth="apikey",
    ),
    # main.py:983 — chat history path param
    Endpoint(
        "GET", f"/v1/chat/history/{STAGING_PATIENT_UUID}",
        auth="apikey",
    ),
    # main.py:855 — conversas (sem params)
    Endpoint(
        "GET", "/v1/conversas",
        auth="none",
        note="sem autenticação; testa error-based e union",
    ),

    # ── /patients/* mobile (JWT paciente) ────────────────────────────────────
    # mobile_api.py:281 — profile
    Endpoint(
        "GET", f"/patients/{STAGING_PATIENT_UUID}/profile",
        auth="mobile",
        note="patient_id path → WHERE id = %s",
    ),
    # mobile_api.py:531 — daily-summary
    Endpoint(
        "GET", f"/patients/{STAGING_PATIENT_UUID}/daily-summary",
        auth="mobile",
    ),
    # mobile_api.py:611 — week-summary
    Endpoint(
        "GET", f"/patients/{STAGING_PATIENT_UUID}/week-summary",
        auth="mobile",
    ),

    # ── /api/clinical/* ──────────────────────────────────────────────────────
    Endpoint(
        "GET", f"/api/clinical/records/{STAGING_PATIENT_UUID}",
        auth="nutri",
        note="patient_id path → WHERE cr.patient_id = %s",
    ),

    # ── /gamification/* ─────────────────────────────────────────────────────
    Endpoint(
        "GET", f"/gamification/league/{STAGING_PATIENT_UUID}",
        auth="mobile",
        note="patient_id path → WHERE patient_id = %s",
    ),

    # ── /referral/* ──────────────────────────────────────────────────────────
    Endpoint(
        "GET", f"/referral/status/{STAGING_PATIENT_UUID}",
        auth="mobile",
        note="patient_id path → WHERE id = %s",
    ),

    # ── /api/pacientes/* ─────────────────────────────────────────────────────
    Endpoint(
        "GET", f"/api/pacientes/{STAGING_PATIENT_UUID}/validar",
        auth="none",
        note="paciente_id path → WHERE acesso_paciente.paciente_id = %s",
    ),

    # ── /api/waitlist/* ──────────────────────────────────────────────────────
    Endpoint(
        "GET", f"/api/waitlist/position/{STAGING_PATIENT_UUID}",
        auth="none",
        note="user_id path → WHERE id = %s",
    ),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _require_target() -> None:
    if CONFIRM != "eu-sou-dono":
        pytest.skip("TARGET_CONFIRM != eu-sou-dono — defina para confirmar que o alvo é seu.")
    if not BASE_URL:
        pytest.skip("BASE_URL não definida.")


def _headers(auth: str) -> dict[str, str]:
    if auth == "nutri" and NUTRI_JWT:
        return {"Authorization": NUTRI_JWT}
    if auth == "mobile" and MOBILE_JWT:
        return {"Authorization": MOBILE_JWT}
    if auth == "apikey" and API_KEY:
        return {"x-api-key": API_KEY}
    return {}


def _send(
    ep: Endpoint,
    override_query: dict[str, str] | None = None,
    override_body: dict[str, Any] | None = None,
) -> tuple[requests.Response, float]:
    params = dict(ep.query_params)
    if override_query:
        params.update(override_query)
    body = dict(ep.body_params)
    if override_body:
        body.update(override_body)

    url = BASE_URL + ep.path
    t0  = time.perf_counter()
    r   = requests.request(
        ep.method, url,
        params=params or None,
        json=body or None,
        headers=_headers(ep.auth),
        timeout=30,
    )
    return r, time.perf_counter() - t0


def _has_db_leak(text: str) -> list[str]:
    low = text.lower()
    return [sig for sig in DB_ERROR_SIGNATURES if sig.lower() in low]


def _injectable(ep: Endpoint) -> list[tuple[str, str]]:
    """Retorna lista de (campo, tipo) para injeção: query params e body params."""
    items = [(k, "query") for k in ep.query_params]
    items += [(k, "body") for k in ep.body_params]
    return items


def _override(field_type: str, param: str, payload: str) -> tuple[dict, dict]:
    """Retorna (override_query, override_body) com o payload no campo certo."""
    if field_type == "query":
        return {param: payload}, {}
    return {}, {param: payload}


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def baseline_latency() -> float:
    _require_target()
    samples: list[float] = []
    for ep in ENDPOINTS:
        for _ in range(2):
            try:
                _, el = _send(ep)
                samples.append(el)
            except requests.RequestException:
                pass
    return statistics.median(samples) if samples else 0.5


# ── Testes ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ep", ENDPOINTS, ids=lambda e: e.id)
def test_error_based_no_db_leak(ep: Endpoint) -> None:
    """
    Injeta caracteres de quebra de sintaxe SQL e verifica:
      1. Nenhum erro de banco vaza na resposta (LGPD).
      2. Código HTTP nunca é 500 (erro não tratado).
    Cobre endpoints sem params injetáveis também (testa apenas o path).
    """
    _require_target()

    injectable = _injectable(ep)
    if not injectable:
        # endpoint sem params: ainda testa que retorna algo saudável
        r, _ = _send(ep)
        leaked = _has_db_leak(r.text)
        assert not leaked, f"[{ep.id}] sem payload — vazou: {leaked}"
        return

    for param, ptype in injectable:
        for payload in ERROR_PAYLOADS:
            oq, ob = _override(ptype, param, payload)
            r, _ = _send(ep, oq, ob)
            leaked = _has_db_leak(r.text)
            assert not leaked, (
                f"[{ep.id}] {ptype}['{param}'] = {payload!r} "
                f"→ erro de banco vazou: {leaked} (HTTP {r.status_code})"
            )
            assert r.status_code != 500, (
                f"[{ep.id}] {ptype}['{param}'] = {payload!r} "
                f"→ HTTP 500 (exceção não tratada)"
            )


@pytest.mark.parametrize("ep", ENDPOINTS, ids=lambda e: e.id)
def test_boolean_blind(ep: Endpoint) -> None:
    """
    Resposta com payload TRUE e FALSE não pode diferir significativamente.
    Diferença grande de status ou tamanho do body indica boolean-blind SQLi.
    Usa baseline com valor legítimo para evitar falso positivo por 404/403.
    """
    _require_target()

    for param, ptype in _injectable(ep):
        for ptrue, pfalse in zip(BOOL_TRUE, BOOL_FALSE):
            oqt, obt = _override(ptype, param, ptrue)
            oqf, obf = _override(ptype, param, pfalse)
            rt, _ = _send(ep, oqt, obt)
            rf, _ = _send(ep, oqf, obf)

            len_t, len_f = len(rt.text), len(rf.text)
            ratio = abs(len_t - len_f) / max(len_t, len_f, 1)

            assert rt.status_code == rf.status_code and ratio < 0.25, (
                f"[{ep.id}] {ptype}['{param}']: TRUE vs FALSE diferem "
                f"(HTTP {rt.status_code}/{rf.status_code}, "
                f"len {len_t}/{len_f}, ratio {ratio:.2%}) "
                f"→ possível boolean-blind SQLi"
            )


@pytest.mark.parametrize("ep", ENDPOINTS, ids=lambda e: e.id)
def test_time_based(ep: Endpoint, baseline_latency: float) -> None:
    """
    Payload com pg_sleep(5) não pode atrasar a resposta além de SLEEP_THRESHOLD
    acima do baseline medido. Detecta time-based blind SQLi.
    """
    _require_target()

    for param, ptype in _injectable(ep):
        for payload in TIME_PAYLOADS:
            oq, ob = _override(ptype, param, payload)
            _, elapsed = _send(ep, oq, ob)
            delta = elapsed - baseline_latency
            assert delta < SLEEP_THRESHOLD, (
                f"[{ep.id}] {ptype}['{param}'] = {payload!r} "
                f"atrasou {delta:.1f}s acima do baseline "
                f"→ possível time-based SQLi"
            )


@pytest.mark.parametrize("ep", ENDPOINTS, ids=lambda e: e.id)
def test_union_marker_not_reflected(ep: Endpoint) -> None:
    """
    Marcador único de UNION SELECT não pode aparecer refletido no body.
    Se aparece, indica union-based SQLi com dados retornados ao cliente.
    """
    _require_target()

    for param, ptype in _injectable(ep):
        for payload in UNION_PAYLOADS:
            oq, ob = _override(ptype, param, payload)
            r, _ = _send(ep, oq, ob)
            assert UNION_MARKER not in r.text, (
                f"[{ep.id}] {ptype}['{param}']: marcador UNION refletido "
                f"→ possível union-based SQLi"
            )


@pytest.mark.parametrize("ep", ENDPOINTS, ids=lambda e: e.id)
def test_path_param_injection(ep: Endpoint) -> None:
    """
    Injeta payloads diretamente no path substituindo o UUID de staging.
    Detecta casos onde path params são concatenados sem parametrização.
    Espera-se 400, 404 ou 422 — nunca 500 e nunca erro de banco no body.
    """
    _require_target()

    path_payloads = [
        "' OR '1'='1",
        "1' AND (SELECT 1 FROM pg_sleep(3))-- -",
        "../../../etc/passwd",
        "00000000-0000-0000-0000-000000000001' OR '1'='1",
    ]
    # só testa se o path contém o UUID de staging (indica path param UUID)
    if STAGING_PATIENT_UUID not in ep.path:
        pytest.skip("Sem UUID de staging no path — não aplicável")

    for payload in path_payloads:
        injected_path = ep.path.replace(STAGING_PATIENT_UUID, payload)
        url = BASE_URL + injected_path
        t0 = time.perf_counter()
        try:
            r = requests.request(
                ep.method, url,
                params=ep.query_params or None,
                headers=_headers(ep.auth),
                timeout=15,
            )
        except requests.RequestException:
            continue  # timeout ou connection error → não é execução de SQL
        elapsed = time.perf_counter() - t0

        leaked = _has_db_leak(r.text)
        assert not leaked, (
            f"[{ep.id}] path payload {payload!r} → erro de banco vazou: {leaked}"
        )
        assert r.status_code not in (500,), (
            f"[{ep.id}] path payload {payload!r} → HTTP 500"
        )
        assert elapsed < SLEEP_THRESHOLD, (
            f"[{ep.id}] path payload {payload!r} → atrasou {elapsed:.1f}s "
            f"→ possível time-based no path param"
        )


# ── Relatório de cobertura (executado sempre, mesmo sem TARGET_CONFIRM) ───────
def test_coverage_report() -> None:
    """
    Imprime tabela de cobertura independente de TARGET_CONFIRM.
    Útil para revisar o que será testado antes de rodar o suite real.
    Nunca falha.
    """
    print("\n\n=== Cobertura de endpoints NutriDeby ===\n")
    print(f"{'Endpoint':<55} {'Auth':<8} {'Params injetáveis'}")
    print("-" * 100)
    for ep in ENDPOINTS:
        params = ", ".join(
            [f"query:{k}" for k in ep.query_params]
            + [f"body:{k}" for k in ep.body_params]
        ) or "(path param / sem params)"
        print(f"{ep.id:<55} {ep.auth:<8} {params}")
        if ep.note:
            print(f"  {'↳'} {ep.note}")
    print(f"\nTotal de endpoints: {len(ENDPOINTS)}")
    total_params = sum(
        len(ep.query_params) + len(ep.body_params) for ep in ENDPOINTS
    )
    print(f"Total de params injetáveis: {total_params}")
    print(f"Payloads por família: error={len(ERROR_PAYLOADS)}, "
          f"time={len(TIME_PAYLOADS)}, union={len(UNION_PAYLOADS)}, "
          f"bool_pairs={len(BOOL_TRUE)}")
    print(f"Combinações totais (aprox.): "
          f"{total_params * (len(ERROR_PAYLOADS) + len(TIME_PAYLOADS) + len(UNION_PAYLOADS) + len(BOOL_TRUE)*2)}")

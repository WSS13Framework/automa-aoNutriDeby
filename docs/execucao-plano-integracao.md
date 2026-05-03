# Execução do plano: DO GenAI + OpenClaw + pipeline Datebox

O código referido abaixo está **aplicado no repositório** (`clients/genai_agent.py`, `rag/patient_retrieve.py`, `workers/rag_demo.py`, `persist/crm_persist.py`, `config.py`, `crm_extract.py`, `.env.example`). Este doc mantém o **checklist operacional** e o `curl` de diagnóstico.

**Importação Postgres:** `python3 -m nutrideby.workers.crm_extract --import-json data/exemplo_import.json` ou `--import-csv` (ver README).

## 1. Operação (sem código)

1. **OpenClaw:** revogar o token exposto no chat; criar novo; guardar só em secrets do painel.
2. **OpenClaw → Modelo:** configurar DeepSeek (OpenRouter slug DeepSeek ou `https://api.deepseek.com` + `DEEPSEEK_API_KEY` se o produto permitir base OpenAI-compatible).
3. **Ponte RAG (NutriDeby → OpenClaw):** configurar tool HTTP para `POST /v1/patients/{uuid}/retrieve` na API NutriDeby (ver §3.1). O agente DO GenAI (`GENAI_AGENT_*`) continua acessível com Bearer próprio para *completions*; são canais complementares.

## 2. Variáveis de ambiente

Acrescentar a [.env.example](../.env.example) e ao teu `.env`:

```env
GENAI_AGENT_URL=https://SEU_SUBDOMINIO.agents.do-ai.run
GENAI_AGENT_ACCESS_KEY=
```

## 3. Teste manual do agente (curl)

Substitui os placeholders; não commits o access key.

```bash
curl -sS -X POST \
  -H "Authorization: Bearer $GENAI_AGENT_ACCESS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"ignored","messages":[{"role":"user","content":"Olá"}],"max_tokens":80}' \
  "$GENAI_AGENT_URL/api/v1/chat/completions?agent=true"
```

Se devolver `404`, tenta também `$GENAI_AGENT_URL/v1/chat/completions?agent=true`. O código do worker tenta `/api/v1/` primeiro.

### 3.1 Retrieval NutriDeby (tool HTTP para OpenClaw)

A API expõe `POST /v1/patients/{uuid}/retrieve` com header `X-API-Key` e corpo `{"query":"…","k":5}`. Na tool do OpenClaw (ou proxy), injeta o UUID interno do paciente da sessão e a pergunta do utilizador em `query`.

```bash
curl -sS -X POST "https://SEU_HOST/v1/patients/UUID_PACIENTE/retrieve" \
  -H "X-API-Key: $NUTRIDEBY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"Pergunta alinhada ao prontuário","k":5}'
```

**Demo (Postgres + embeddings + opcional agente):** ``--patient-id`` tem de ser um **UUID hexadecimal válido**; não uses marcadores tipo ``UUID`` ou ``SEU_UUID`` (o ``argparse`` rejeita).

No servidor com Docker (recomendado):

```bash
PID=$(docker compose exec -T postgres psql -U nutrideby -d nutrideby -t -A -c "SELECT id::text FROM patients LIMIT 1;" | tr -d ' \n')
docker compose --profile tools run --rm worker python -m nutrideby.workers.rag_demo --patient-id "$PID" --query "Pergunta"
docker compose --profile tools run --rm worker python -m nutrideby.workers.rag_demo --patient-id "$PID" --query "Pergunta" --with-agent
# Prompts clínicos (``src/nutrideby/rag/clinical_analyst_prompts.py``):
docker compose --profile tools run --rm worker python -m nutrideby.workers.rag_demo --patient-id "$PID" --query "Analise os exames" --with-agent --persona clinical
docker compose --profile tools run --rm worker python -m nutrideby.workers.rag_demo --patient-id "$PID" --query "Resumo para o prontuário" --with-agent --persona motor
```

Em máquina local com ``DATABASE_URL`` apontando ao Postgres: ``python3 -m nutrideby.workers.rag_demo --patient-id "$PID" ...`` com o mesmo ``PID`` obtido via ``psql``.

**Nota DO GenAI Agent:** se aparecer HTTP 400 *«system and developer messages are not allowed»*, o ``rag_demo`` já envia instruções + pergunta numa única mensagem ``user`` (sem ``role=system``). Actualiza o código no servidor com ``git pull``.

**Pré-resumo de exames (regex opcional):** ficheiro JSON de metas + ``--exam-metas-json /caminho/metas.json`` (só com ``--with-agent``). Formato: ``{"Hemoglobina":{"min":12,"max":16},"Glicemia":{"min":null,"max":100}}``. Detecta linhas ``Nome: valor unidade`` e datas ISO ou DD/MM/AAAA nas linhas anteriores; ver ``nutrideby.rag.exam_hit_preprocess``.

## 4. `src/nutrideby/config.py`

Dentro da classe `Settings`, após os campos DeepSeek:

```python
    genai_agent_url: str | None = None
    genai_agent_access_key: str | None = None
```

## 5. Novo ficheiro `src/nutrideby/clients/genai_agent.py`

```python
from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_COMPLETION_PATHS = (
    "/v1/chat/completions?agent=true",
    "/api/v1/chat/completions?agent=true",
)


def _post_json(url: str, body: dict[str, Any], access_key: str, timeout: int) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {access_key}")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, raw


def check_agent_inference(
    agent_base_url: str,
    access_key: str,
    *,
    timeout: int = 60,
) -> bool:
    """
    Envia um pedido mínimo estilo OpenAI ao agente DO (RAG).
    Tenta /v1 e /api/v1 até um responder sem 404.
    """
    base = agent_base_url.rstrip("/")
    body: dict[str, Any] = {
        "model": "ignored",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 32,
    }
    last_err: str | None = None
    for path in _COMPLETION_PATHS:
        url = f"{base}{path}"
        try:
            status, text = _post_json(url, body, access_key, timeout)
            logger.info("GenAI agent respondeu HTTP %s (path %s)", status, path)
            if 200 <= status < 300:
                logger.debug("Corpo (truncado): %s", text[:500])
                return True
            last_err = f"HTTP {status}: {text[:300]}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTPError {e.code}: {e.read()[:300]!r}"
        except Exception as e:
            last_err = str(e)
            logger.exception("Falha ao contactar %s", url)
    logger.error("Agente GenAI inacessível após tentar paths: %s", last_err)
    return False
```

Criar `src/nutrideby/clients/__init__.py` vazio ou com `__all__ = []`.

## 6. Novo ficheiro `src/nutrideby/persist/crm_persist.py`

```python
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

import psycopg

logger = logging.getLogger(__name__)


def upsert_patient(
    conn: psycopg.Connection,
    *,
    source_system: str,
    external_id: str,
    display_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID:
    meta = json.dumps(metadata or {})
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patients (source_system, external_id, display_name, metadata)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (source_system, external_id) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, patients.display_name),
                metadata = COALESCE(patients.metadata, '{}'::jsonb)
                    || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
                updated_at = now()
            RETURNING id
            """,
            (source_system, external_id, display_name, meta),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def insert_document_if_new(
    conn: psycopg.Connection,
    *,
    patient_id: uuid.UUID,
    doc_type: str,
    content_text: str,
    source_ref: str | None = None,
) -> uuid.UUID | None:
    h = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (patient_id, doc_type, content_text, content_sha256, source_ref)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (patient_id, doc_type, content_sha256) DO NOTHING
            RETURNING id
            """,
            (patient_id, doc_type, content_text, h, source_ref),
        )
        row = cur.fetchone()
        if row is None:
            logger.info(
                "Documento duplicado ignorado (patient=%s doc_type=%s sha=%s…)",
                patient_id,
                doc_type,
                h[:12],
            )
            return None
        return row[0]
```

Criar `src/nutrideby/persist/__init__.py` vazio.

## 7. Alterações a `src/nutrideby/workers/crm_extract.py`

1. Importar `check_agent_inference` de `nutrideby.clients.genai_agent`.
2. Adicionar argumento `--check-agent` ao `ArgumentParser`.
3. Depois de `settings = Settings()` e antes do `dry_run`, se `args.check_agent`:

```python
    if getattr(args, "check_agent", False):
        if not settings.genai_agent_url or not settings.genai_agent_access_key:
            logger.error("Defina GENAI_AGENT_URL e GENAI_AGENT_ACCESS_KEY para --check-agent")
            return 2
        ok = check_agent_inference(
            settings.genai_agent_url,
            settings.genai_agent_access_key,
        )
        return 0 if ok else 1
```

4. No `parser.add_argument`, incluir:

```python
    parser.add_argument(
        "--check-agent",
        action="store_true",
        help="Testa POST ao agente DigitalOcean GenAI (GENAI_AGENT_URL + ACCESS_KEY)",
    )
```

## 8. Docker

O target `worker` já instala o pacote; não são necessárias dependências novas (só `urllib` da biblioteca padrão).

## 9. Prontuário Datebox

Reutilizar a lógica de separadores em [src/scraper/extract_patients.py](../src/scraper/extract_patients.py) (`extract_tab_content` para «Prontuários») como referência de UX ao mapear seletores no worker Playwright; persistir com `insert_document_if_new` + `upsert_patient`.

## 10. Sincronizar KB na DigitalOcean

Depende da API de ingestão do produto GenAI (upload de ficheiros / texto). Fora do âmbito deste repo até haver endpoint estável; o job pode ler `documents` do Postgres e chamar a API a partir do Droplet ou de um Worker.

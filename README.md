# NutriDeby — MVP (demo cliente)

Pipeline: **ingestão** (Dietbox API v2 ou ficheiros) → **Postgres** (`patients`, `documents`) → (futuro) RAG / GenAI.

## Pré-requisitos

- Python 3.10+
- PostgreSQL com schema aplicado: `infra/sql/001_initial.sql` (+ `002_*`, `003_*` se usares webhooks; **`004_pgvector_chunks_embedding.sql`** para RAG / `pgvector`)
- Docker: serviço `postgres` usa imagem **`pgvector/pgvector:pg16`** (extensão `vector`). Bases **já** criadas com outra imagem: migrar ou aplicar `004` manualmente após instalar pgvector no servidor.
- Ficheiro `.env` (usa `.env.example` como modelo)

**Servidor Ubuntu (shell no host, fora do Docker):** muitas imagens mínimas só têm o binário `python3`. Usa `python3 -m nutrideby...` no host, ou (recomendado em produção) **`docker compose --profile tools run --rm worker python -m ...`** — dentro do container o comando `python` existe. Opcional no host: `sudo apt install python-is-python3`.

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Testes rápidos para segunda-feira (MVP)

### 1) Base de dados

Garante `DATABASE_URL` no `.env` e aplica o SQL inicial na base (`infra/sql/001_initial.sql`). Bases já criadas: aplica também `002_external_snapshots.sql` para subscription persistida; **`004_pgvector_chunks_embedding.sql`** para vectores (ver **`docs/decisao-embeddings-vector-store.md`**).

### 2) Importação offline (sem Dietbox)

```bash
python3 -m nutrideby.workers.data_import --json data/exemplo_import.json
```

### 3) Sincronização Dietbox (API)

No `.env`: `DIETBOX_BEARER_TOKEN` (JWT depois de `Bearer `) e opcionalmente `DIETBOX_API_BASE`.

```bash
# Conectividade + prontuário (204 sem corpo é OK)
python3 -m nutrideby.workers.dietbox_sync --probe ID_PACIENTE

# Prontuário de um paciente → documents (+ paciente mínimo)
python3 -m nutrideby.workers.dietbox_sync --sync-one ID_PACIENTE

# Só ficha do paciente (GET /v2/paciente/{id} → patients, sem prontuário)
python3 -m nutrideby.workers.dietbox_sync --sync-patient ID_PACIENTE

# Lista de pacientes → Postgres (source_system=dietbox)
python3 -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 1

# Mesmo filtro que o browser com IsActive=false (só inactivos)
python3 -m nutrideby.workers.dietbox_sync --sync-list --inactive-only --take 10 --max-pages 1

# SituacaoIMC em lote (pacientes já em Postgres; GET paciente + fórmula por defeito)
python3 -m nutrideby.workers.dietbox_sync --sync-formula-imc-all --formula-workers 2

# Subscription → tabela external_snapshots (aplica antes infra/sql/002_external_snapshots.sql se a base já existia)
python3 -m nutrideby.workers.dietbox_sync --sync-subscription

# Prontuário em massa (sequencial; extraction_runs para auditoria / retomada)
python3 -m nutrideby.workers.dietbox_sync --sync-prontuario-all --prontuario-limit 50 --prontuario-sleep-ms 300
python3 -m nutrideby.workers.dietbox_sync --sync-prontuario-all --prontuario-resume-run-id UUID_DA_LINHA_extraction_runs

# Smoke para cron (JWT): exit 0=OK, 3=HTTP 401; opcional NUTRIDEBY_SMOKE_ALERT_WEBHOOK_URL
python3 -m nutrideby.workers.dietbox_sync --smoke

# Linha do tempo /v2/meta → documents (JSON agregado; --meta-max-pages limita paginação)
python3 -m nutrideby.workers.dietbox_sync --sync-meta-patient ID_PACIENTE --meta-take 50 --meta-max-pages 30
python3 -m nutrideby.workers.dietbox_sync --sync-meta-all --meta-all-limit 10 --meta-all-sleep-ms 400
```

Cron e webhook: **`docs/monitorizacao-smoke-cron.md`**; exemplo de script: **`scripts/smoke-dietbox.example.sh`**.

### Chunks (texto → Postgres, sem embeddings)

Depois de teres `documents` (prontuário, meta, etc.):

```bash
python3 -m nutrideby.workers.chunk_documents --limit 30
python3 -m nutrideby.workers.chunk_documents --doc-type dietbox_prontuario --limit 50 --max-chars 1200
docker compose --profile tools run --rm worker python -m nutrideby.workers.chunk_documents --limit 20
```

API: `GET /v1/patients/{uuid}/chunks` (mesmo `X-API-Key`). Embeddings / FAISS ficam para uma fase seguinte.

Se no servidor der `unrecognized arguments: --sync-list`, o código está desactualizado: actualiza o repo e corre `docker compose build worker`.

Aumenta `--max-pages` para sincronizar mais páginas. Por omissão envia `IsActive=true`. `--include-inactive` omite o parâmetro (todos). `--inactive-only` envia `IsActive=false` (como no DevTools quando a lista são inactivos).

## Docker (servidor)

Serviço `worker` deve incluir `env_file: .env` (ou `docker-compose.override.yml`) para ver `DIETBOX_*`.

Exemplo:

```bash
docker compose --profile tools run --rm worker python -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 2
```

### API leitura (Sprint 2)

Serviço opcional `api` (FastAPI) em `http://127.0.0.1:8080` — lê `patients` / `documents` do Postgres.

No `.env`: `NUTRIDEBY_API_KEY` (valor opaco); pedidos a `/v1/*` levam header `X-API-Key: <valor>`. Se a chave estiver vazia, `/v1/*` fica **sem** autenticação (só para desenvolvimento).

```bash
pip install -e .   # instala fastapi + uvicorn
docker compose --profile api up -d api
curl -sS http://127.0.0.1:8080/health
curl -sS -H "X-API-Key: $NUTRIDEBY_API_KEY" "http://127.0.0.1:8080/v1/patients?limit=5&source_system=dietbox"
curl -sS -H "X-API-Key: $NUTRIDEBY_API_KEY" http://127.0.0.1:8080/v1/dietbox/subscription
# Webhook Kiwify (MVP): POST JSON; path = mesmo valor que KIWIFY_WEBHOOK_PATH_SECRET no .env
# curl -sS -X POST http://127.0.0.1:8080/hooks/kiwify/SEU_SEGREDO -H 'Content-Type: application/json' -d '{"test":true}'
```

Ver **`docs/sprint-user-stories.md`** (US-01) e aplicar **`infra/sql/003_integration_webhook_inbox.sql`** na base.

## Documentação

- **`docs/operacao-git-docker-servidor.md`** — Git *untracked*, `git pull`, volume Docker, erro `--sync-list`, `psql` (leitura obrigatória para deploy)
- **`docs/higiene-git-e-repositorio.md`** — o que **não** commitar; checklist antes do `push`; limpar ficheiros já enviados por engano
- **`docs/checklist-mvp-e-endpoints.md`** — mapa da lista Network vs código + **checklist de testes** para a demo
- **`docs/regras-negocio-jornada-telemetria.md`** — regras de negócio: vendas (Cloudfy) vs. telemetria (VPS), Kiwify, jornada do paciente e backlog de alto nível
- **`docs/sprint-user-stories.md`** — *user stories* da sprint (incl. webhook Kiwify MVP)
- `docs/execucao-plano-integracao.md` — plano GenAI / persistência
- `docs/estrategia-dietbox-e-api-propria.md` — estratégia Dietbox + API própria

## Nota

Se `GET /v2/paciente` devolver JSON com chaves diferentes das esperadas, os logs mostram as chaves no topo; ajusta `extract_list_payload` / `patient_record_from_item` em `src/nutrideby/clients/dietbox_api.py`.

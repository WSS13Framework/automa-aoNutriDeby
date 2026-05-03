# NutriDeby — MVP (demo cliente)

Pipeline: **ingestão** (Dietbox API v2 ou ficheiros) → **Postgres** (`patients`, `documents`) → (futuro) RAG / GenAI.

## Pré-requisitos

- Python 3.10+
- PostgreSQL com schema aplicado: `infra/sql/001_initial.sql`
- Ficheiro `.env` (usa `.env.example` como modelo)

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Testes rápidos para segunda-feira (MVP)

### 1) Base de dados

Garante `DATABASE_URL` no `.env` e aplica o SQL inicial na base.

### 2) Importação offline (sem Dietbox)

```bash
python -m nutrideby.workers.data_import --json data/exemplo_import.json
```

### 3) Sincronização Dietbox (API)

No `.env`: `DIETBOX_BEARER_TOKEN` (JWT depois de `Bearer `) e opcionalmente `DIETBOX_API_BASE`.

```bash
# Conectividade + prontuário (204 sem corpo é OK)
python -m nutrideby.workers.dietbox_sync --probe ID_PACIENTE

# Prontuário de um paciente → documents (+ paciente mínimo)
python -m nutrideby.workers.dietbox_sync --sync-one ID_PACIENTE

# Só ficha do paciente (GET /v2/paciente/{id} → patients, sem prontuário)
python -m nutrideby.workers.dietbox_sync --sync-patient ID_PACIENTE

# Lista de pacientes → Postgres (source_system=dietbox)
python -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 1

# Mesmo filtro que o browser com IsActive=false (só inactivos)
python -m nutrideby.workers.dietbox_sync --sync-list --inactive-only --take 10 --max-pages 1

# SituacaoIMC em lote (pacientes já em Postgres; GET paciente + fórmula por defeito)
python -m nutrideby.workers.dietbox_sync --sync-formula-imc-all --formula-workers 2
```

Se no servidor der `unrecognized arguments: --sync-list`, o código está desactualizado: actualiza o repo e corre `docker compose build worker`.

Aumenta `--max-pages` para sincronizar mais páginas. Por omissão envia `IsActive=true`. `--include-inactive` omite o parâmetro (todos). `--inactive-only` envia `IsActive=false` (como no DevTools quando a lista são inactivos).

## Docker (servidor)

Serviço `worker` deve incluir `env_file: .env` (ou `docker-compose.override.yml`) para ver `DIETBOX_*`.

Exemplo:

```bash
docker compose --profile tools run --rm worker python -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 2
```

## Documentação

- **`docs/operacao-git-docker-servidor.md`** — Git *untracked*, `git pull`, volume Docker, erro `--sync-list`, `psql` (leitura obrigatória para deploy)
- **`docs/higiene-git-e-repositorio.md`** — o que **não** commitar; checklist antes do `push`; limpar ficheiros já enviados por engano
- **`docs/checklist-mvp-e-endpoints.md`** — mapa da lista Network vs código + **checklist de testes** para a demo
- `docs/execucao-plano-integracao.md` — plano GenAI / persistência
- `docs/estrategia-dietbox-e-api-propria.md` — estratégia Dietbox + API própria

## Nota

Se `GET /v2/paciente` devolver JSON com chaves diferentes das esperadas, os logs mostram as chaves no topo; ajusta `extract_list_payload` / `patient_record_from_item` em `src/nutrideby/clients/dietbox_api.py`.

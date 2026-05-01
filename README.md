# automa-aoNutriDeby

Pipeline para extração automatizada do CRM (Datebox, sem API pública), armazenamento estruturado, indexação vetorial (FAISS — próximos passos) e geração de campanhas com DeepSeek.

## Requisitos

- Docker e Docker Compose
- Python 3.10+ (desenvolvimento local sem Docker; a imagem Docker Playwright `jammy` usa 3.10)

## Início rápido (Docker)

1. Copie variáveis de ambiente:

   ```bash
   cp .env.example .env
   ```

2. Suba PostgreSQL e Redis:

   ```bash
   docker compose up -d postgres redis
   ```

3. O schema em `infra/sql/001_initial.sql` é aplicado automaticamente na **primeira** inicialização do volume `pgdata`. Se precisar recriar o banco:

   ```bash
   docker compose down -v
   docker compose up -d postgres redis
   ```

4. Build e execução do worker (stub Playwright):

   ```bash
   docker compose --profile tools build worker
   docker compose --profile tools run --rm worker python -m nutrideby.workers.crm_extract --dry-run
   ```

5. Testar conexão com o banco a partir do container:

   ```bash
   docker compose --profile tools run --rm worker python -m nutrideby.workers.crm_extract --check-db
   ```

6. Com `GENAI_AGENT_URL` e `GENAI_AGENT_ACCESS_KEY` no `.env`, testar o agente DigitalOcean GenAI (ver também [docs/execucao-plano-integracao.md](docs/execucao-plano-integracao.md)):

   ```bash
   docker compose --profile tools run --rm worker python -m nutrideby.workers.crm_extract --check-agent
   ```

## Importar dados para Postgres (CSV ou JSON)

Com PostgreSQL a correr (`docker compose up -d postgres`) e o schema aplicado:

```bash
# JSON de exemplo (dados fictícios)
python -m nutrideby.workers.crm_extract --import-json data/exemplo_import.json

# CSV no formato do template data/pacientes_export_template.csv
python -m nutrideby.workers.crm_extract --import-csv data/o_teu_export.csv
```

No Docker (monta `./data` em `/app/data`):

```bash
docker compose --profile tools build worker
docker compose --profile tools run --rm worker \
  python -m nutrideby.workers.crm_extract --import-json /app/data/exemplo_import.json
```

Após `git pull`, volta a fazer **`build worker`**. A imagem **não** instala o pacote `nutrideby` em `site-packages`: só dependências; o código vem sempre de **`./src` → `/app/src`** (`PYTHONPATH`). Se `--import-json` não for reconhecido, o host ainda tem `src/` antigo — confirma `git log -1 --oneline` e `grep import-json src/nutrideby/workers/crm_extract.py`.

## Login Datebox (Playwright, opcional)

Se definires no `.env` as variáveis `CRM_USERNAME`, `CRM_PASSWORD` e os três seletores CSS `CRM_LOGIN_USER_SELECTOR`, `CRM_LOGIN_PASSWORD_SELECTOR`, `CRM_LOGIN_SUBMIT_SELECTOR`, o comando sem flags (`CRM_BASE_URL` definido) tenta preencher o login após abrir a URL base. Ajusta os seletores ao HTML real do Datebox.

## Integração DO GenAI, RAG e OpenClaw

Objetivo de negócio: extração **Datebox** (sem API) → **Postgres** (`patients`, `documents`) → base de conhecimento / **RAG** na DigitalOcean → **OpenClaw** (GARRA) com **DeepSeek** como interface. Passos operacionais, `curl` e patches de código listados em **[docs/execucao-plano-integracao.md](docs/execucao-plano-integracao.md)**.

## Desenvolvimento local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
python -m nutrideby.workers.crm_extract --dry-run
python -m nutrideby.workers.crm_extract --check-db
python -m nutrideby.workers.crm_extract --check-agent
```

Com PostgreSQL só no host, use `DATABASE_URL=postgresql://nutrideby:nutrideby_dev@localhost:5432/nutrideby` no `.env`.

## Git: enviar código e atualizar no servidor

No computador onde editas o projeto:

```bash
git status
git add -A
git commit -m "Descreva a alteração."
git push origin main
```

No servidor (já tens o repositório em `/opt/automa-aoNutriDeby`):

```bash
cd /opt/automa-aoNutriDeby
git pull origin main
```

Clone de raiz (substitui a pasta antiga; apaga alterações locais não commitadas):

```bash
cd /opt
rm -rf automa-aoNutriDeby
git clone https://github.com/WSS13Framework/automa-aoNutriDeby.git
cd automa-aoNutriDeby
```

`data/pacientes.csv` com dados reais **não** é versionado (`.gitignore`, LGPD). Usa `data/pacientes_export_template.csv` como modelo e gera `data/pacientes.csv` no servidor (por exemplo a partir de `/opt/nutri-campaign/`).

## Estrutura

| Caminho | Descrição |
|--------|-----------|
| `infra/sql/001_initial.sql` | Tabelas `patients`, `documents`, `chunks`, `extraction_runs`, `campaign_drafts` |
| `src/nutrideby/config.py` | Configuração via `.env` |
| `src/nutrideby/workers/crm_extract.py` | Stub Playwright (`--dry-run`, `--check-db`, `--check-agent`) |
| `src/nutrideby/clients/genai_agent.py` | Cliente HTTP mínimo para agente DO GenAI (RAG) |
| `src/nutrideby/persist/crm_persist.py` | Upsert `patients` / insert idempotente `documents` |
| `src/nutrideby/workers/data_import.py` | `--import-csv` / `--import-json` → Postgres |
| `data/exemplo_import.json` | Exemplo mínimo de importação JSON |
| `docs/execucao-plano-integracao.md` | Checklist operacional DO GenAI / OpenClaw + `curl` |
| `docker-compose.yml` | `postgres`, `redis`, `worker` (perfil `tools`) |
| `Dockerfile` | Imagem base Playwright oficial + pacote instalado |

## Próximos passos sugeridos

- Mapear seletores reais do Datebox e persistir em `patients` / `documents`.
- Worker de chunking + embeddings e índice FAISS (arquivo + `chunks.faiss_id`).
- Cliente DeepSeek e gravação em `campaign_drafts`.
- Fila assíncrona (Celery/RQ) consumindo Redis já definido no Compose.

## LGPD

Dados de saúde exigem base legal, minimização, DPA com subprocessadores (ex.: LLM) e revisão humana antes de disparo de campanhas. Não commitar `.env` nem dumps com PII.

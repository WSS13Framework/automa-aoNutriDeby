# automa-aoNutriDeby

Pipeline para extração automatizada do CRM (Datebox, sem API pública), armazenamento estruturado, indexação vetorial (FAISS — próximos passos) e geração de campanhas com DeepSeek.

## Requisitos

- Docker e Docker Compose
- Python 3.11+ (desenvolvimento local sem Docker)

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

## Desenvolvimento local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
python -m nutrideby.workers.crm_extract --dry-run
python -m nutrideby.workers.crm_extract --check-db
```

Com PostgreSQL só no host, use `DATABASE_URL=postgresql://nutrideby:nutrideby_dev@localhost:5432/nutrideby` no `.env`.

## Estrutura

| Caminho | Descrição |
|--------|-----------|
| `infra/sql/001_initial.sql` | Tabelas `patients`, `documents`, `chunks`, `extraction_runs`, `campaign_drafts` |
| `src/nutrideby/config.py` | Configuração via `.env` |
| `src/nutrideby/workers/crm_extract.py` | Stub Playwright (`--dry-run`, `--check-db`) |
| `docker-compose.yml` | `postgres`, `redis`, `worker` (perfil `tools`) |
| `Dockerfile` | Imagem base Playwright oficial + pacote instalado |

## Próximos passos sugeridos

- Mapear seletores reais do Datebox e persistir em `patients` / `documents`.
- Worker de chunking + embeddings e índice FAISS (arquivo + `chunks.faiss_id`).
- Cliente DeepSeek e gravação em `campaign_drafts`.
- Fila assíncrona (Celery/RQ) consumindo Redis já definido no Compose.

## LGPD

Dados de saúde exigem base legal, minimização, DPA com subprocessadores (ex.: LLM) e revisão humana antes de disparo de campanhas. Não commitar `.env` nem dumps com PII.

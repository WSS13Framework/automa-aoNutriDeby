# Checklist MVP + mapa do que ainda falta

Este documento alinha a **lista de pedidos** que descobriste > Network com o **código no repositório** e dá **testes verificáveis** para a demo.

## 1. Lista de endpoints / hosts (o que enviaste)

| # | URL / host | Método | Notas |
|---|------------|--------|--------|
| A | `https://dietbox.me/.../Nutritionist/Get` → 301 → `/pt-BR/...` | GET | Site IIS; **não** é o caminho principal da automação. |
| B | `https://api.dietbox.me/v2/nutritionist/subscription` | GET | Subscrição da nutricionista (JSON). Path correcto: **um** `/` entre `v2` e `nutritionist` (evitar `v2//`). |
| C | `https://api.dietbox.me/v2/paciente?skip=&take=&order=name` (+ `IsActive`) | GET | **Lista de clientes/pacientes** — base do MVP. |
| D | `https://api.dietbox.me/v2/paciente/{id}/prontuario` | GET | Prontuário; pode devolver **204** sem corpo. |

**Configuração** usada pelo worker: `.env` → `DATABASE_URL`, `DIETBOX_API_BASE`, `DIETBOX_BEARER_TOKEN`; Docker → `env_file: .env` no serviço `worker` (ou `docker-compose.override.yml`).

---

## 2. Estado de implementação (honesto)

| Item | Estado | Onde / notas |
|------|--------|----------------|
| Lista pacientes (C) → Postgres `patients` | **Feito** | `dietbox_sync --sync-list`; envelope `Data`; `--include-inactive` / `--inactive-only`; piloto com centenas de upserts. |
| API leitura Sprint 2 (FastAPI) | **Feito** (mínimo) | `nutrideby.api.main:app` — `GET /health`, `/v1/patients`, `/v1/patients/{uuid}`, `/v1/patients/by-external/...`, `/v1/patients/{uuid}/documents`; `docker compose --profile api up`; `NUTRIDEBY_API_KEY` + header `X-API-Key`. |
| Probe prontuário (D) | **Feito** (mínimo) | `--probe`; loga HTTP; **não** grava `documents`. |
| Prontuário 200 com corpo → `documents` | **Feito** | `--sync-one`: JSON em `documents` (`doc_type=dietbox_prontuario`, `insert_document_if_new`). |
| Prontuário 204 → marcador / política | **Feito** | `--sync-one`: texto `[Prontuário: API 204 sem corpo]` + mesmo `doc_type` (idempotente por hash). |
| Detalhe paciente → `patients` | **Feito** | `--sync-patient` (GET `/v2/paciente/{id}`). |
| Subscription (B) | **Parcial** | `--subscription` (probe HTTP + log); **persistir** JSON na base (metadata global / tabela): ainda não. |
| Site MVC (fórmulas / feed) | **Parcial** | `SituacaoIMC` (`--formula-*`, `--sync-formula-imc-all`), `--feed-list`; IIS; mesmo Bearer; frágil vs API v2. |
| `/v2/meta` paciente | **Parcial** | `--meta` (probe); ingestão em massa para `documents`: não. |
| Site legacy (A) | **Não feito** (não prioritário) | Preferir API; Playwright só se a doc §9 exigir. |
| `extraction_runs` (cursor, retomada) | **Não feito** | Tabela existe no SQL; worker não regista ainda. |
| GenAI / `--check-agent` | **Feito** (mínimo) | `src/nutrideby/clients/genai_agent.py`; `python -m nutrideby.workers.crm_extract --check-agent` (requer `GENAI_*` no `.env`). |
| Chunks / embeddings / FAISS | **Não feito** | Fora do sync actual. |
| API própria da nutricionista | **Não feito** | Produto à parte (Sprint 2 no plano). |
| Jobs periódicos (cron/Celery) | **Não feito** | Hoje: correr comandos à mão ou `cron` no servidor; monitor JWT: planeado. |

---

## 3. Checklist de testes (para hoje / antes da segunda)

Marca ✅ quando passar. **Não** colar tokens nos relatórios.

### Configuração

- [ ] `df -h` — disco com espaço livre suficiente.
- [ ] `.env` com `DATABASE_URL` apontando à base certa.
- [ ] `.env` com `DIETBOX_BEARER_TOKEN` (JWT completo após `=`); `grep '^DIETBOX_BEARER_TOKEN=' .env | wc -c` ≫ 22.
- [ ] `DIETBOX_API_BASE=https://api.dietbox.me` (ou omitir — default igual).
- [ ] Docker: `docker compose ... run worker env | grep '^DIETBOX_'` mostra as duas variáveis (mascaradas).

### Base de dados

- [ ] `psql` (ou cliente): schema aplicado (`infra/sql/001_initial.sql`).
- [ ] `SELECT count(*) FROM patients;` — executa antes e depois dos testes para ver diferença.

### Teste A — Importação offline (sem Dietbox)

```bash
python -m nutrideby.workers.data_import --json data/exemplo_import.json
```

- [ ] Exit code `0`.
- [ ] Log com contagem de pacientes/documentos.
- [ ] Na base: pelo menos um `patient` com `external_id = demo-exemplo-001`.

### Teste B — Conectividade API + prontuário

```bash
python -m nutrideby.workers.dietbox_sync --probe SUBSTITUIR_ID_PACIENTE
```

- [ ] Exit code `0` se HTTP for `200` ou `204`.
- [ ] Se `401`: token expirado ou inválido — renovar JWT.
- [ ] Se `404`: ID inexistente ou path errado.

### Teste C — Lista de clientes → base

**Nota:** no servidor, o ficheiro `dietbox_sync.py` tem de estar **actualizado** (com `--sync-list`). Se aparecer `unrecognized arguments: --sync-list`, faz `git pull` / copia o código do repositório e **rebuild** da imagem: `docker compose build worker`.

**Prontuário de um paciente** (grava `documents` + paciente; 204 vira marcador):

```bash
python -m nutrideby.workers.dietbox_sync --sync-one SUBSTITUIR_ID_PACIENTE
```

**Só metadados do paciente** (GET `/v2/paciente/{id}` → `patients`, sem prontuário):

```bash
python -m nutrideby.workers.dietbox_sync --sync-patient SUBSTITUIR_ID_PACIENTE
```

Lista paginada:

```bash
python -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 1
```

- [ ] Exit code `0`.
- [ ] Log `sync-list concluído: upserts=N` com **N > 0** (se a conta tiver pacientes e o JSON for reconhecido).
- [ ] Se `upserts=0`: ver log **“Chaves no topo do JSON”** — enviar essas chaves (sem dados sensíveis) para ajustar o parser.
- [ ] Na base: contagem por `source_system` (ver **SQL na shell** abaixo) — aparece `dietbox`.

**SQL na shell (não colar `SELECT` directamente no bash):**

```bash
docker compose exec postgres psql -U nutrideby -d nutrideby -c "SELECT source_system, count(*) FROM patients GROUP BY 1;"
```

(Se o utilizador da base for outro, ajusta `-U` e `-d`.)

### Teste D — Docker (igual ao servidor)

```bash
docker compose --profile tools run --rm worker python -m nutrideby.workers.dietbox_sync --sync-list --take 10 --max-pages 1
```

- [ ] Mesmo resultado que em local, se o `.env` e a rede forem os mesmos.

### Teste E — Lista completa (quando C estiver OK)

```bash
python -m nutrideby.workers.dietbox_sync --sync-list --take 50 --max-pages 20
```

- [ ] Contagem na base cresce de forma coerente; sem erros HTTP `429` (rate limit).

---

## 4. Próximas implementações (ordem sugerida pós-MVP)

1. Prontuário **em massa** (job: iterar `patients` → `--sync-one` ou batch) + rate limit / retomada.
2. Persistir resposta de `GET /v2/nutritionist/subscription` (hoje só `--subscription` probe).
3. `extraction_runs` + cursor `skip` para retomada idempotente.
4. Smoke agendado (cron) + alerta se JWT expirar (**401**); ver plano de monitorização.
5. Playwright só para o que a API **não** cobrir (prontuário na UI).

---

## 5. Referências

- Estratégia produto: [estrategia-dietbox-e-api-propria.md](./estrategia-dietbox-e-api-propria.md)
- Plano técnico GenAI / persistência: [execucao-plano-integracao.md](./execucao-plano-integracao.md)
- Comandos rápidos: [README.md](../README.md)

**Última actualização:** 2026-05-03

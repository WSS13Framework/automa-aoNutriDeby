# Replicação: Dietbox como origem temporária → API NutriDeby

**Objectivo:** profissionais que **ainda** usam Dietbox como suporte conseguem **replicar** o mesmo caminho que o piloto; **novos** clientes tendem a entrar pela **API / jornada própria** (Kiwify, WhatsApp, etc.) sem depender do directório Dietbox.

**Contexto:** a Dietbox **não** expõe documentação pública estável de autenticação servidor-a-servidor. O fluxo actual usa o **mesmo JWT Bearer** que o browser envia a `api.dietbox.me` (DevTools → Network → cabeçalho `Authorization`).

---

## 1. Fase A — Bootstrap (espelho na vossa infra)

| Passo | Acção |
|--------|--------|
| 1 | `.env` com `DIETBOX_API_BASE=https://api.dietbox.me` e `DIETBOX_BEARER_TOKEN=` **só o JWT** (valor depois de `Bearer `, **sem** repetir a palavra `Bearer`). |
| 2 | Postgres + migrações (`001`…`004` se RAG). |
| 3 | `docker compose --profile tools run --rm worker python -m nutrideby.workers.dietbox_sync --sync-list --take N --max-pages M` → `patients`. |
| 4 | Prontuário / meta conforme README: `--sync-one`, `--sync-meta-patient`, etc. → `documents`. |
| 5 | RAG: `chunk_documents` → `embed_chunks` (requer `OPENAI_API_KEY`). |

**401 na lista:** token expirado ou inválido — renovar no browser e actualizar `DIETBOX_BEARER_TOKEN` (ver secção 3).

---

## 2. Fase B — API própria como destino (novos clientes)

- **Novos** entram por fluxos vossos (ex.: webhook Kiwify `compra_aprovada`, formulário, WhatsApp com consentimento) e gravam em **`patients` / `documents`** via **API NutriDeby** (já há leitura `GET /v1/...`; ingestão escrita pode evoluir por user stories).
- Dietbox passa a **opcional**: histórico importado fica na vossa base; **não** sois obrigados a manter o ciclo de vida de dados só dentro do ecossistema Dietbox.

---

## 3. Operação sem documentação oficial — token semanal (proposta)

Enquanto não existir refresh token ou credencial de serviço acordada com a Dietbox:

1. **Rotina** (ex. 1× por semana, ou após alerta de smoke): responsável renova sessão no browser, copia novo JWT, actualiza **secret manager** ou `.env` no servidor.
2. **Smoke / alerta** (`dietbox_sync --smoke`, `NUTRIDEBY_SMOKE_ALERT_WEBHOOK_URL`): falha **401** → notificação em vez de falha silenciosa.
3. **Nunca** commitar tokens; preferir **secrets** do fornecedor cloud em produção.

**Melhoria futura:** se a Dietbox (ou B2C por trás) disponibilizar **refresh token** ou **client credentials**, substituir esta rotina por renovação automática no worker — documentar nesse caso neste ficheiro.

---

## 4. Endpoints já conhecidos (lista mínima)

| Uso | Método | URL (exemplo) |
|-----|--------|----------------|
| Lista pacientes | GET | `https://api.dietbox.me/v2/paciente?skip=&take=&order=name` (+ `IsActive` conforme necessidade) |
| Detalhe paciente | GET | `/v2/paciente/{id}` |
| Prontuário | GET | `/v2/paciente/{id}/prontuario` (204 possível) |

Evitar `v2//` (dois slashes). O worker usa `DIETBOX_API_BASE` + paths em `nutrideby.clients.dietbox_api`.

---

## 5. Checklist “replicar noutro profissional”

- [ ] Conta Dietbox + JWT obtido como acima.
- [ ] `.env` / secrets com `DATABASE_URL`, `DIETBOX_*`, chaves API internas (`NUTRIDEBY_API_KEY`, `OPENAI_*` se RAG).
- [ ] `docker compose` com Postgres pgvector se embeddings.
- [ ] Primeiro `sync-list` com `take` pequeno; validar `SELECT count(*) FROM patients;`.
- [ ] Documentar **contacto Dietbox** para pedir integração oficial (quando fizer sentido comercial).

---

## 6. Relação com outros docs

- Checklist técnico: `docs/checklist-mvp-e-endpoints.md`
- Plano negócio / sprints: `docs/PLANO-NEGOCIO-E-SPRINTS.md`
- Estratégia API própria: `docs/estrategia-dietbox-e-api-propria.md`

**Última actualização:** 2026-05-03

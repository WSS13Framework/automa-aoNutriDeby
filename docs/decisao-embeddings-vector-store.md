# Decisão: embeddings e vector store (NutriDeby)

**Estado:** proposta aprovada para execução técnica até **revisão em 2026-08-01** (ou quando o modelo de embedding mudar).

**Contexto:** fechar o **gate Plano A → B** em `docs/sequencia-planos-abc-mvp.md` — “onde correm embeddings e o índice vectorial”.

---

## 1. Objectivos

- Recuperação **por paciente** (multi-tenant lógico): filtros SQL + semântica sobre `chunks` ligados a `patient_id`.
- **Uma** base operacional em MVP: menos peças móveis que Ficheiro FAISS + Postgres desincronizados.
- Compatível com **testes repetíveis** (query + top-k + `chunk_id` citável).

---

## 2. Decisão (MVP)

| Camada | Escolha | Motivo |
|--------|---------|--------|
| **Armazenamento de vectores** | **PostgreSQL + extensão `pgvector`** | Já usamos Postgres; backups e ACL iguais ao resto; suporta índice HNSW / IVFFlat; `chunks` já existe. |
| **Dimensão do vector** | **`1536`** na coluna `chunks.embedding` | Alinhada a modelos **OpenAI-compatíveis** frequentes (`text-embedding-3-small` com dimensão por omissão, `text-embedding-ada-002`). Se mudares de modelo, **nova migração** ou coluna `embedding_v2` com outra dimensão. |
| **Geração de embeddings** | **Serviço externo via API** (OpenAI ou outro com vector compatível) num **worker** dedicado | Mantém o Postgres só como store; escala de CPU de embedding fora da BD; chaves só no `.env` / secret manager. |
| **RAG “orquestrado” (GenAI Agent / OpenClaw)** | **Paralelo**, não substitui o store local | O agente DigitalOcean (`GENAI_AGENT_*`) pode ter KB própria; aqui definimos a **fonte de verdade NutriDeby** para “o que está na nossa base por paciente”. O agente pode chamar a API de retrieval quando existir. |

**Não escolhido para o MVP inicial:** índice FAISS em disco (já previsto no schema como `faiss_id` legado — **não** priorizar até haver necessidade de benchmark extremo).

---

## 3. Infraestrutura

- **Docker local / CI:** imagem **`pgvector/pgvector:pg16`** (substitui `postgres:16-alpine` para ter a extensão disponível).
- **Servidor já com Postgres “stock”:** instalar `pgvector` ao nível do cluster **ou** migrar para imagem/OS com suporte; só depois aplicar `infra/sql/004_pgvector_chunks_embedding.sql`.
- **Aplicação da migração:** bases novas montam `infra/sql` no `docker-entrypoint-initdb.d` na **primeira** subida; bases existentes: `psql "$DATABASE_URL" -f infra/sql/004_pgvector_chunks_embedding.sql` com utilizador que consiga `CREATE EXTENSION vector` (uma vez).

---

## 4. Próximos passos técnicos (Plano B)

1. ~~Worker `embed_chunks`~~ **Feito:** `python -m nutrideby.workers.embed_chunks` preenche `embedding` + `embedding_model`.
2. Índice **HNSW** — já criado na migração `004` (reavaliar parâmetros após carga real).
3. ~~Endpoint `patient_id` + texto → top-k~~ **Feito:** `POST /v1/patients/{uuid}/retrieve` (distância coseno `<=>`).
4. Script de demo documentado no `checklist-mvp-e-endpoints.md` (pergunta → passagens citadas).

---

## 5. Alternativas consideradas

- **Só FAISS em ficheiro:** simples em demo, frágil em HA e em filtrar por `patient_id` sem hacks.
- **Vector DB SaaS (Pinecone, etc.):** bom em escala; para MVP aumenta custo e sincronização de IDs.
- **Embeddings só dentro do agente cloud:** útil para protótipo, menos auditável para “trecho veio deste `chunk_id` na nossa BD”.

---

## 6. Referências no repositório

- Schema inicial `chunks`: `infra/sql/001_initial.sql`
- Migração pgvector: `infra/sql/004_pgvector_chunks_embedding.sql`
- Cliente + worker: `src/nutrideby/clients/openai_embeddings.py`, `src/nutrideby/workers/embed_chunks.py`
- API retrieval: `POST /v1/patients/{uuid}/retrieve` em `nutrideby.api.main`
- Sequência de produto: `docs/sequencia-planos-abc-mvp.md`

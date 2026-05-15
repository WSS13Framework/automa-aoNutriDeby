# 2. Arquitetura e Infraestrutura

## Diagrama de Serviços

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose Network                     │
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────────┐   │
│  │ PostgreSQL│    │  Redis   │    │     Nginx (proxy)    │   │
│  │  :5432   │    │  :6379   │    │   :80 / :443         │   │
│  └────┬─────┘    └────┬─────┘    └──────────┬───────────┘   │
│       │               │                     │                │
│       ├───────────────┼─────────────────────┤                │
│       │               │                     │                │
│  ┌────▼─────┐    ┌────▼─────┐    ┌─────────▼────────────┐   │
│  │   API    │    │  Worker  │    │     Dashboard        │   │
│  │ FastAPI  │    │ (tools)  │    │     Next.js          │   │
│  │  :8080   │    │          │    │      :3000           │   │
│  └──────────┘    └──────────┘    └──────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Serviços Docker

| Serviço | Imagem | Porta Host | Profile | Descrição |
| :--- | :--- | :--- | :--- | :--- |
| `postgres` | pgvector/pgvector:pg16 | 5432 | (sempre) | Banco principal com suporte a vetores |
| `redis` | redis:7-alpine | 127.0.0.1:6379 | (sempre) | Cache e fila de jobs |
| `api` | Build local (Dockerfile) | 127.0.0.1:8081 | `api` | API REST FastAPI |
| `dashboard` | Build local (dashboard/Dockerfile) | 0.0.0.0:3000 | `api` | Painel Next.js |
| `worker` | Build local (Dockerfile) | — | `tools` | Workers de extração/embedding |
| `nginx` | nginx:alpine | 80, 443 | — | Reverse proxy (opcional) |

## Profiles Docker Compose

O projeto usa profiles para controlar quais serviços sobem:
- **Sem profile:** Apenas `postgres` e `redis` (banco e cache).
- **`--profile api`:** Sobe `postgres`, `redis`, `api` e `dashboard`.
- **`--profile tools`:** Sobe `postgres`, `redis` e `worker` (para rodar scripts de extração/embedding).

## Banco de Dados (PostgreSQL)

### Tabelas Principais

| Tabela | Propósito |
| :--- | :--- |
| `patients` | Cadastro de pacientes (source_system, external_id, display_name) |
| `documents` | Documentos clínicos vinculados a pacientes |
| `chunks` | Fragmentos de texto com embeddings vetoriais (pgvector) |
| `extraction_runs` | Log de execuções de extração de dados |
| `taco_items` | Tabela TACO (composição de alimentos) |
| `campaign_drafts` | Rascunhos de campanhas de comunicação |
| `onboarding_jobs` | Jobs de onboarding de novos pacientes |
| `onboarding_credentials` | Credenciais de integração (Dietbox, etc.) |
| `onboarding_audit_log` | Auditoria de onboarding |
| `genai_analysis_exports` | Exportações de análises geradas por IA |

### Extensão pgvector

O banco usa a extensão `pgvector` para armazenar e buscar embeddings vetoriais na coluna `chunks.embedding`. Isso permite busca semântica (RAG) nos prontuários dos pacientes.

## Rede e Segurança

- **Redis:** Bind apenas em `127.0.0.1` (não exposto à internet).
- **API:** Bind apenas em `127.0.0.1:8081` (acessível apenas via rede Docker interna ou localhost).
- **Dashboard:** Exposto em `0.0.0.0:3000` (acessível externamente).
- **PostgreSQL:** Exposto em `0.0.0.0:5432` (considerar restringir em produção).
- **Autenticação API:** Header `X-API-Key` obrigatório em todas as rotas.

# Plano de negócio e roadmap por sprints — NutriDeby / piloto Dra. Débora

Documento vivo: ajustar após cada retro. Objetivo — **piloto comprovado** → **replicação**.

## 1. Visão em uma página

| | |
|--|--|
| **Problema** | Profissionais no Dietbox pagam o plano mas não têm API pública, automação nem canal único (ex. WhatsApp) para campanhas e segmentação ativo/inativo com IA. |
| **Solução** | Conector (espelho na base) + API própria + agentes (OpenClaw) + vetores (RAG) + WhatsApp (fase 1) + dashboard do paciente (fase 2). |
| **Piloto** | Dra. Débora — tempo, campanhas, retorno. |
| **Diferencial** | Credenciais e autorização do titular; sem intrusão; LGPD/ToS com advogado. |

## 2. O que já existe

- Git, Docker (Postgres, Redis), worker Playwright.
- Schema 001 + migração 002 (`documents.metadata`, índices).
- `.env`; garantir `env_file: .env` no serviço **worker** para `CRM_*`.
- API interna Dietbox: `api.dietbox.me/v2/...` + Bearer JWT (B2C).
- OpenClaw com `workspace` → `/opt/automa-aoNutriDeby`.

## 3. Correções imediatas

- `env_file` no worker; rotação de tokens expostos; sync Dietbox→Postgres (hoje counts = 0); LGPD para campanhas a inativos.

## 4. Fases macro

A. Espelho → B. API interna → C. WhatsApp + campanhas → D. RAG → E. UAT piloto → F. Dashboard paciente.

## 5. Sprints (2 semanas — sugestão)

**Sprint 1 — Conector MVP**  
Lista/detalhe/prontuário → `patients` (+ `documents`/`metadata` ativo, score). Job agendado.  
*Pronto:* `COUNT(patients) > 0` no piloto.

**Sprint 2 — API leitura**  
FastAPI: lista paciente, contexto agregado para IA; API key/JWT interno.  
*Pronto:* OpenClaw ou `curl` consome.

**Sprint 3 — WhatsApp**  
Webhook, opt-in, templates; gravar interações ligadas ao paciente; MCQ mínimo.  
*Pronto:* 1 fluxo teste com consentimento.

**Sprint 4 — OpenClaw + campanhas**  
Tools na API; `campaign_drafts`; revisão humana; segmentação inativos.  
*Pronto:* 1 campanha teste aprovada pela Débora.

**Sprint 5 — RAG**  
Chunking, embeddings, índice (FAISS/pgvector); busca por paciente.  
*Pronto:* resposta com trecho dos dados (sem alucinar fora da base).

**Sprint 6 — Endurecimento**  
Backups, métricas, runbook, checklist LGPD, doc 1 página para a profissional.  
*Pronto:* UAT + P0 zerados.

**Sprint 7 (fase 2) — Dashboard paciente**  
Hash/código, timeline, fotos com consentimento e retenção; gráficos.  
*Pronto:* 1 paciente em staging.

## 6. Critérios “piloto concluído”

- [ ] Sync N dias sem falha crítica  
- [ ] N pacientes espelhados corretos  
- [ ] 1 campanha inativos com aprovação prévia  
- [ ] 1 fluxo WhatsApp ligado ao paciente  
- [ ] 1 demo RAG  
- [ ] Nota jurídica mínima (ToS + LGPD + imagens)

## 7. Métricas

Horas/semana em tarefas manuais (antes/depois); resposta a campanhas; NPS interno.

## 8. Riscos top

Mudança de API; ToS; vazamento de token; bloqueio WhatsApp; scope creep — usar este roadmap.

## 9. Próximo passo hoje

1. `env_file` no worker  
2. Lista de endpoints Sprint 1  
3. Data kickoff Sprint 1 + donos (conector / API / WhatsApp)

# Sequência Planos A → B → C → MVP (metodologia)

Documento **fonte de ordem** para lançar um MVP **o mais viável possível**, sem misturar prioridades.  
Complementa (não substitui) **`docs/regras-negocio-jornada-telemetria.md`**, **`docs/PLANO-NEGOCIO-E-SPRINTS.md`** e **`docs/checklist-mvp-e-endpoints.md`**.

## Metodologia (como seguir)

1. **Uma fase de cada vez** — só avançar de A→B ou B→C quando os **critérios de saída** da fase actual estiverem verificados (checklist ou demo gravada).
2. **Backlog separado** — itens fora da fase actual ficam em “depois”; não bloqueiam a fase (ex.: US-02 Kiwify pode existir no código/doc mas **não** é gate do Plano A).
3. **Prova objectiva** — cada plano termina com **testes** ou **comandos** repetíveis (ver `checklist-mvp-e-endpoints.md` e smoke).
4. **Revisão** — após cada plano, actualizar este ficheiro ou o plano de sprints com **1–3 linhas** do que mudou.

---

## Plano A — Ligações e infra mínima definida

**Objectivo:** O sistema “respira” em ambiente controlado: dados, API, segredos, rede e observabilidade mínima.

| Entrega | Notas |
|--------|--------|
| Ambiente documentado | Onde corre API, worker, Postgres, Redis; `.env` / Docker; `docs/operacao-git-docker-servidor.md`. |
| Base e espelho Dietbox | `DATABASE_URL`; sync lista/prontuário/meta conforme checklist; `COUNT(patients) > 0` no piloto quando aplicável. |
| API e autenticação interna | Health + rotas `v1` com `X-API-Key`; smoke (`--smoke`, cron) conforme `monitorizacao-smoke-cron.md`. |
| Regras de negócio legíveis | Jornada e telemetria em `regras-negocio-jornada-telemetria.md` — **referência**, não implementação total nesta fase. |

**Critérios de saída (gate A→B)**

- [ ] Checklist de configuração e smoke verdes no ambiente alvo (staging ou VPS).
- [ ] Decisão escrita: **onde** embeddings e vector store vão correr (ex.: só Postgres/pgvector vs. serviço externo) — pode ser “proposta + data de revisão”.

---

## Plano B — RAG (fundação técnica)

**Objectivo:** Recuperação aumentada **testável**: texto → chunks → embeddings → busca → resposta com **trechos da base** (sem depender de WhatsApp nem Kiwify).

| Entrega | Notas |
|--------|--------|
| Chunks de qualidade | Política de chunking alinhada a `documents` / prontuário; idempotência e metadados. |
| Embeddings + vector store | Escolha fixa (dimensão, modelo); persistência (ex.: `pgvector` ou índice documentado). |
| API ou tool de retrieval | Contrato estável: `patient_id` + query → top-k passagens + scores. |
| Integração agente (OpenClaw / GenAI) | `GENAI_*` / `--check-agent` evoluído para **fluxo RAG** com fixture ou paciente de teste. |
| Checkpoints técnicos | Onde o fluxo pára/retoma (run id, cursor, estado); “cruzamento” entre passos **dentro** do pipeline RAG (ingestão → indexar → consultar). |

**Critérios de saída (gate B→C)**

- [ ] Demo repetível: pergunta → resposta com **citação** a chunk(s) existentes na BD.
- [ ] Teste documentado contra o vosso stack RAG (não só “código existe”).

---

## Plano C — Pontes de produto e regras de negócio

**Objectivo:** Ligar **jornada** e **automação**: eventos externos, consentimento, e gates de negócio sem rebentar o RAG.

| Entrega | Notas |
|--------|--------|
| Webhook Kiwify (já parcial) | Inbox (US-01); **US-02** quando for prioridade — mapeamento + idempotência (`sprint-user-stories.md`). |
| WhatsApp (quando prioridade) | Webhook, opt-in, templates; alinhar a `PLANO-NEGOCIO-E-SPRINTS` fase C. |
| “Cruzamento” de checkpoints de negócio | Ex.: só sugerir receita após plano activo; LGPD; estados explícitos na BD ou máquina de estados documentada. |
| Ferramentas para IA | Tools que chamam a API RAG + regras (nunca só LLM solto). |

**Critérios de saída (gate C→MVP)**

- [ ] Pelo menos **um** fluxo ponta-a-ponta escolhido (ex.: paciente piloto + consulta RAG + opcional mensagem ou evento).
- [ ] Runbook curto: o que fazer em falha (401 Dietbox, webhook duplicado, índice vazio).

---

## MVP (definição fechada para lançamento)

**MVP = Plano A + B completos**, com **um subconjunto** do Plano C **explicitamente** incluído na release (o resto fica backlog).

Sugestão de **MVP mínimo viável** (ajustar com a Dra. Débora):

| Incluído no MVP | Excluído por defeito (até próxima release) |
|-----------------|---------------------------------------------|
| Dados replicados + API + RAG com prova | WhatsApp massivo, dashboard paciente completo |
| Smoke / backups mínimos do runbook | US-02 Kiwify completa **se** ainda não for necessária para o piloto |
| 1 fluxo demo com paciente consentido | Vector store “nice to have” duplicado em vários sítios |

**Critério final “MVP lançado”**

- [ ] Piloto consegue **ver** valor em 1 sessão (dados + resposta fundamentada + responsável identificado).
- [ ] Checklist LGPD mínimo acordado (mesmo que “processo em papel” na primeira volta).

---

## Mapa rápido A / B / C / MVP

```
Plano A — ligações + infra + decisões escritas
    ↓
Plano B — RAG (chunks, vectors, retrieval, testes com agente)
    ↓
Plano C — Kiwify, WhatsApp, checkpoints de negócio, tools
    ↓
MVP    — A + B + recorte acordado de C + critério piloto
```

---

## Relação com outros documentos

| Documento | Papel |
|-----------|--------|
| `regras-negocio-jornada-telemetria.md` | **O quê** e **porquê** (jornada, telemetria). |
| `sprint-user-stories.md` | User stories técnicas (US-01…); ordem pode diferir da **prioridade** A/B/C. |
| `checklist-mvp-e-endpoints.md` | Verificação concreta (comandos, endpoints). |
| `PLANO-NEGOCIO-E-SPRINTS.md` | Sprints por semanas; usar este ABC para **desempatar** quando o plano linear e a realidade divergirem (ex.: RAG antes de WhatsApp no piloto técnico). |

**Regra prática:** Se houver conflito entre “sprint 5 = RAG” no plano longo e a necessidade actual de **validar RAG já**, este documento prevalece para **ordem de execução** até a próxima retro.

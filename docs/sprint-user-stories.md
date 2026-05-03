# User stories — sprint (pós regras de negócio)

Origem: **`docs/regras-negocio-jornada-telemetria.md`**. Critérios de aceitação em formato testável.

---

## US-01 — Receptor HTTP Kiwify (MVP)

**Como** sistema NutriDeby  
**Quero** receber POSTs da Kiwify num URL estável  
**Para** guardar o payload bruto e auditar eventos antes da lógica de negócio.

**Critérios de aceitação**

1. `POST /hooks/kiwify/{secret}` com `secret` igual a `KIWIFY_WEBHOOK_PATH_SECRET` no `.env` → **200** e corpo `{"received": true, "id": "<uuid>"}`.
2. Secret incorrecto ou em falta quando a env está definida → **401**.
3. Se `KIWIFY_WEBHOOK_PATH_SECRET` **não** estiver definido → **503** com mensagem clara (webhook desactivado).
4. Cada pedido válido insere linha em **`integration_webhook_inbox`** com `source='kiwify'`, `payload` JSON, `status='pending'`.
5. Content-Type `application/json`; corpo não-JSON → **400** (log sem dados sensíveis completos em produção).

**Estado:** implementado neste sprint (ver `infra/sql/003_integration_webhook_inbox.sql` e `nutrideby.api.main`).

**URL na Kiwify (exemplo):** `https://SEU_DOMINIO/hooks/kiwify/SEU_SEGREDO_LONGO` — o segmento final **deve** coincidir com o valor de `KIWIFY_WEBHOOK_PATH_SECRET` (sem o colar em chats públicos).

---

## US-02 — Processar `compra_aprovada` (próximo sprint)

**Como** operação pós-venda  
**Quero** interpretar o payload Kiwify quando o evento for compra aprovada  
**Para** criar ou associar `patient`, plano, e disparar onboarding (WhatsApp telemetria — a definir).

**Critérios de aceitação (rascunho)**

1. Mapeamento documentado dos campos Kiwify → `patients` / metadata (email, nome, product_id, etc.).
2. Idempotência por `order_id` ou equivalente (não duplicar paciente em reenvio de webhook).
3. `integration_webhook_inbox.status` passa a `processed` ou `error` + mensagem.
4. Teste manual com payload de exemplo (fixture JSON sem PII real).

**Depende de:** US-01 + decisão de campos exactos na resposta Kiwify.

---

## US-03 — Documento “foto de refeição” (MVP técnico)

**Como** pipeline de telemetria  
**Quero** anexar uma imagem ou metadados a um `patient` existente  
**Para** preparar visão computer vision / descrição textual numa sprint seguinte.

**Critérios de aceitação (rascunho)**

1. API ou worker aceita upload (multipart) **ou** URL + `patient_id` interno, com `X-API-Key`.
2. Grava `documents` com `doc_type` estável (ex. `telemetry_meal_photo`) e `source_ref` único.
3. LGPD: só com paciente identificado e consentimento registado (processo a fechar com dono de produto).

---

## US-04 — Motor mínimo de receitas (conteúdo)

**Como** paciente em telemetria  
**Quero** sugestões de receitas alinhadas ao meu perfil  
**Para** variar a alimentação sem sair do plano.

**Critérios de aceitação (rascunho)**

1. Entrada: tags ou restrições a partir de `patients.metadata` / plano.
2. Saída: lista de 3–5 receitas (texto estruturado ou JSON) gravada em `documents` ou tabela dedicada.
3. Versão de “motor” identificável (`recipe_engine_v1` no metadata).

**Depende de:** definição de fonte de receitas (KB interna vs. LLM com guardrails).

---

## US-05 — Lista de compras semanal (geração)

**Como** paciente  
**Quero** uma lista de compras coerente com as receitas / plano da semana  
**Para** facilitar adesão.

**Critérios de aceitação (rascunho)**

1. Geração semanal (cron ou on-demand) por `patient_id`.
2. Saída em `documents` com `doc_type=telemetry_shopping_list` e hash idempotente por semana.

---

## Ordem sugerida

1. **US-01** (feito)  
2. **US-02** (negócio + contrato Kiwify)  
3. **US-03** (base para fotos)  
4. **US-04 / US-05** (conteúdo; podem paralelizar com GenAI se aprovado)

---

**Última actualização:** 2026-05-03

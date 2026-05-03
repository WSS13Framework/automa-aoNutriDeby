# Regras de negócio e jornada do paciente — telemetria NutriDeby

Documento de **alinhamento produto + técnica** para sprints seguintes. Resume a lógica acordada: **dois WhatsApps**, **handoff na venda (Kiwify)**, e **acompanhamento contínuo** com cruzamento de dados clínicos e alimentares.

---

## 1. Objectivo

- Oferecer **acompanhamento nutricional contínuo** (telemetria no telemóvel), **cruzando** o que o paciente envia (fotos, exames, questionários, treino, etc.) com o **perfil clínico** e as **regras do plano**.
- Manter **vendas** e **telemetria** em **canais distintos** para não confundir o paciente nem misturar objectivos (comercial vs. cuidado).
- Garantir que a **inteligência** tenha margem para **nuances nutricionais** (macros, restrições, histórico, exames ao longo do tempo).

---

## 2. Dois WhatsApps (regra fixa)

| Canal | Finalidade | Onde vive hoje (referência) |
|-------|------------|-----------------------------|
| **WhatsApp de vendas** | Captação, explicação de pacotes, envio de **link de pagamento**, fecho de vendas, entrada no ecossistema | Plataforma **Cloudfy** (OpenClaw alojado), já ligado ao WhatsApp comercial da Nutri |
| **WhatsApp de telemetria / acompanhamento** | Após pagamento: fotos de refeições, exames, questionários, cruzamento com scores e plano, relatórios, suporte ao dia a dia | **Sistema próprio** (servidor + NutriDeby + inteligência) — **a configurar**; não confundir com o número de vendas |

**Regra:** não misturar os dois até haver um **desenho explícito** de migração ou ponte. Configuração no **servidor** não implica WhatsApp ligado aí; o WhatsApp de vendas continua onde foi feito o *pairing*.

---

## 3. Handoff comercial → paciente activo (Kiwify)

1. O paciente interage pelo **WhatsApp de vendas** e recebe o **link Kiwify** para pagar o pacote.
2. **Após pagamento confirmado** (evento Kiwify — webhook / automação), dispara-se a lógica de **onboarding**: acesso ao **WhatsApp de telemetria** (ou deep link / instruções), criação ou associação do registo do paciente no sistema, permissões alinhadas ao **plano contratado**.
3. Este gancho é o **limite** entre “prospecto” e “cliente com telemetria”: tudo o que é **dado clínico-alimentar sensível** no dia a dia deve preferir o **canal e a infraestrutura** do programa (telemetria), não o thread de vendas.

*(Kiwify = checkout / produtos digitais; a integração técnica típica será **webhook** + endpoint seguro + idempotência.)*

**Implementação MVP do receptor:** ver **`docs/sprint-user-stories.md`** (US-01) — `POST /hooks/kiwify/{secret}` e tabela `integration_webhook_inbox` (`infra/sql/003_integration_webhook_inbox.sql`).

---

## 4. O que é a telemetria (definição de produto)

- **Monitorização contínua** no telemóvel: o paciente envia **fotos de comida**, **resultados de análises ao sangue** (e outros exames conforme o plano), respostas a **questionários**, e — conforme roadmap — **treino**, **fitoterapia**, e outros eixos acordados no plano (incl. abordagens mais técnicas / moleculares quando fizer parte do desenho clínico).
- A inteligência **lê macros**, **compara** com o que faz sentido para **aquele** paciente (restrições, scores, histórico) e **guarda** conclusões e inputs no **histórico** (auditoria + evolução no tempo).
- O acompanhamento é **ancorado no que o plano cobre**: não é um chat genérico; as perguntas, lembretes e análises respeitam o **âmbito contratado** (ex.: tipos de exames incluídos, frequência de check-ins, módulos activos).

**Nota:** qualquer menção anterior a **“AXIS”** foi **erro de digitação** — não corresponde a produto nem a eixo técnico nomeado neste projecto.

### 4.1 Variedade e alimentação prática (24×7, sem monotonia)

- **Receitas** sugeridas ao longo do tempo, **variadas**, para o paciente **não cair na monotonia**, sempre **alinhadas ao perfil clínico e nutricional** da pessoa (restrições, objectivos, “ponto alto” / preferências e tolerâncias que o plano e o histórico justificam).
- **Lista de compras semanal** (e ajustes conforme fase do plano), com **alimentos específicos** para ela.
- Para esses alimentos: orientação sobre **como usar**, **como confeccionar**, **como digerir melhor** (contexto clínico), **como sanitizar / tratar em segurança** (higiene, manipulação), sempre **fundamentada nas questões clínicas** do paciente.

### 4.2 Treino, potenciação alimentar e suplementação

- **Dicas de treino** coerentes com o estado e o plano (sem substituir educador físico quando aplicável).
- **Como potenciar** o efeito de cada alimento (combinações, timing, hidratação, etc.) dentro do que o histórico clínico permite.
- **Suplementação** discutida **em conjunto com** o **histórico clínico** e avaliação (exames, medicação, contraindicações) — nunca genérica; cruzamento explícito com **avaliação** e regras do plano.

### 4.3 Segmento de avaliação por fotos e dados objectivos (ex.: bioimpedância)

- **Avaliações por fotos** (refeições, pratos, contexto) como **segmento próprio** do fluxo: **procedimento** claro (o que fotografar, como enviar, prazos), **critérios** de feedback, e decisão de produto sobre **o que é viável 100% online** vs. o que exige **presencial** ou **terceiros** (ex.: equipamento do ginásio).
- **Bioimpedância / composição corporal** (BIA): avaliar **se e como** integrar — por exemplo, se o **ginásio** do paciente dispõe de equipamento e **pode enviar** (ficheiro, PDF, export) para a **inteligência** analisar e **ajustar planos** com base nessa informação **cruzada** com o restante do dossiê. O desenho exacto (formato, validade clínica, responsabilidade profissional) fica para **validação** com a nutricionista e para **backlog técnico** (ingestão, parsers, anti-fraude mínimo).

### 4.4 Ecossistema de bem-estar

- Visão de **ecossistema completo** voltado ao **bem-estar** do paciente — alimentação, cuidado, treino, fitoterapia, linhas mais técnicas quando previstas no plano — **sempre** com **lastro nas questões clínicas** e no **histórico**; a inteligência **fecha** leituras e sugestões com **rastreio** (de onde vieram os dados e porquê aquela conclusão), para suportar **acompanhamento 24×7** no telemóvel sem perder o fio clínico.

---

## 5. Inteligência e “nuances” nutricionais

A inteligência deve suportar, entre outros:

- Cruzamento **paciente ↔ alimento** (foto → estimativa de macros / tipo de prato → confronto com tolerâncias e metas).
- Integração de **marcadores laboratoriais** ao longo do tempo (vários envios de análises).
- Uso de **questionários estruturados** (sinais, sintomas, adesão, contexto social — ex.: “festa”).
- **Relatórios** periódicos ou sob pedido, **fundamentados no histórico clínico-alimentar** acumulado, para reduzir ansiedade (“sei o que estou a fazer com os meus dados”).
- **Base de conhecimento** alinhada a nutrição clínica e boas práticas (sem substituir julgamento da nutricionista onde a lei ou deontologia o exigirem).
- Tudo o descrito em **4.1–4.4** (receitas, listas, treino, suplementação, fotos, BIA, bem-estar) como **camadas** sobre o mesmo **núcleo**: dados do paciente + plano + evidência.

---

## 6. Ritmo humano vs. disponibilidade 24×7

| Aspecto | Regra |
|---------|--------|
| **Telemetria / suporte digital** | Disponível **24×7** no sentido de **registar, processar e responder** com base em dados e políticas — incluindo **receitas**, **listas de compras**, **dicas** e **avaliações por fotos** (ver §4), sem ser monótono (dentro dos limites técnicos e legais). |
| **Contacto humano presencial (nutricionista)** | **Avaliação presencial** alinhada ao **fecho do pacote** (ex.: ciclo de **três meses**), em data acordada — não substituída pela telemetria, mas **complementada** por ela. |

Mensagem-chave para o paciente: **acompanhamento contínuo no telemóvel** + **ponto de contacto humano** no fecho do ciclo / renovação.

---

## 7. Implicações técnicas (alto nível — backlog sprint)

Estes itens **não** são implementação neste ficheiro; servem para **priorizar** trabalho no repo e integrações.

1. **Modelo de dados e ingestão:** `patients`, `documents`, `chunks` (e futuros tipos) para exames, fotos (metadata + texto extraído), questionários, notas de treino/fitoterapia, etc.
2. **Evento pós-pagamento Kiwify:** endpoint de webhook, validação, mapeamento `compra → paciente/plano`, acção de **provisioning** do canal de telemetria.
3. **Segregação de canais:** configuração clara de qual instância OpenClaw / qual número WhatsApp é **vendas** vs. **telemetria** (evitar mistura de segredos `.env`).
4. **LGPD e minimização:** consentimentos, retenção, acesso; dados clínicos concentrados na infra da **telemetria**.
5. **Relatórios e “scores”:** definição formal de **métricas** (o que é “score”, de onde vem, como actualiza).
6. **Módulos de conteúdo:** motor de **receitas** personalizáveis; gerador de **lista de compras** semanal; templates de **dicas** (digestão, sanitização, treino) com variantes por perfil clínico.
7. **Fluxo “avaliação por fotos”:** estados (enviado → em análise → feedback), limites do que é **online** vs. **presencial**; eventual pipeline de **bioimpedância** / export do ginásio (formato, validação).
8. **Observabilidade:** jobs, falhas de webhook, falhas de API Dietbox (já há smoke JWT no worker).

---

## 8. Glossário rápido

| Termo | Significado neste projecto |
|--------|----------------------------|
| **Cloudfy** | Plataforma onde está o OpenClaw de **vendas** + WhatsApp comercial (fora do VPS). |
| **VPS / servidor** | Máquina com NutriDeby, Docker, Postgres, workers — onde se constrói a **telemetria** e integrações (ex. Dietbox). |
| **Kiwify** | Checkout / link de pagamento; evento de compra dispara automação de **onboarding**. |
| **NutriDeby** | Pipeline e API interna (ingestão, documentos, chunks, leitura) que suporta a inteligência e o histórico. |

---

## 9. Revisão deste documento

- **Dono de produto:** validar prazos (ex.: 3 meses), exactidão dos módulos (receitas, lista de compras, fotos, treino, suplementação, bioimpedância / ginásio, fitoterapia, etc.) e mensagens ao paciente.
- **Equipa técnica:** derivar *user stories* e critérios de aceitação a partir das secções 2–7 e **4.1–4.4**.

**Última actualização:** 2026-05-03 — duplo WhatsApp, Kiwify, Cloudfy vs. VPS; telemetria 24×7 (receitas, compras, fotos, treino, suplementação, BIA); “AXIS” corrigido como erro de digitação; ecossistema bem-estar ancorado no clínico.

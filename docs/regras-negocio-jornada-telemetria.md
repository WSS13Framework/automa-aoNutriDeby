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

---

## 4. O que é a telemetria (definição de produto)

- **Monitorização contínua** no telemóvel: o paciente envia **fotos de comida**, **resultados de análises ao sangue** (e outros exames conforme o plano), respostas a **questionários**, e — conforme roadmap — **treino**, **fitoterapia**, e outros eixos acordados no plano (incl. abordagens mais técnicas / moleculares quando fizer parte do desenho clínico).
- A inteligência **lê macros**, **compara** com o que faz sentido para **aquele** paciente (restrições, scores, histórico) e **guarda** conclusões e inputs no **histórico** (auditoria + evolução no tempo).
- O acompanhamento é **ancorado no que o plano cobre**: não é um chat genérico; as perguntas, lembretes e análises respeitam o **âmbito contratado** (ex.: tipos de exames incluídos, frequência de check-ins, módulos activos).

---

## 5. Inteligência e “nuances” nutricionais

A inteligência deve suportar, entre outros:

- Cruzamento **paciente ↔ alimento** (foto → estimativa de macros / tipo de prato → confronto com tolerâncias e metas).
- Integração de **marcadores laboratoriais** ao longo do tempo (vários envios de análises).
- Uso de **questionários estruturados** (sinais, sintomas, adesão, contexto social — ex.: “festa”).
- **Relatórios** periódicos ou sob pedido, **fundamentados no histórico clínico-alimentar** acumulado, para reduzir ansiedade (“sei o que estou a fazer com os meus dados”).
- **Base de conhecimento** alinhada a nutrição clínica e boas práticas (sem substituir julgamento da nutricionista onde a lei ou deontologia o exigirem).

---

## 6. Ritmo humano vs. disponibilidade 24×7

| Aspecto | Regra |
|---------|--------|
| **Telemetria / suporte digital** | Disponível **24×7** no sentido de **registar, processar e responder** com base em dados e políticas (dentro dos limites técnicos e legais). |
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
6. **Observabilidade:** jobs, falhas de webhook, falhas de API Dietbox (já há smoke JWT no worker).

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

- **Dono de produto:** validar prazos (ex.: 3 meses), exactidão dos módulos (treino, fitoterapia, etc.) e mensagens ao paciente.
- **Equipa técnica:** derivar *user stories* e critérios de aceitação a partir das secções 2–7.

**Última actualização:** 2026-05-03 — alinhado com conversa sobre duplo WhatsApp, Kiwify, Cloudfy vs. VPS, e telemetria 24×7 com fecho humano no ciclo do pacote.

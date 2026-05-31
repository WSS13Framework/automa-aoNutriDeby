# Twilio Content Templates — NutriDeby
## Prontos para o Content Template Builder (aguardar aprovação do bundle)

---

### TEMPLATE 1 — Reativação Simples
**Friendly Name:** nutrideby_reativacao_simples
**Category:** UTILITY
**Language:** pt-BR

**Body:**
Olá, {{1}}! 😊 Aqui é a assistente da Dra. Débora Oliver.
Faz um tempo que não nos falamos e sentimos sua falta!
A Dra. Débora tem acompanhado seu histórico e gostaria de saber: como você está se sentindo hoje?

---

### TEMPLATE 2 — Reativação com Contexto Clínico
**Friendly Name:** nutrideby_reativacao_clinica
**Category:** UTILITY
**Language:** pt-BR

**Body:**
Oi, {{1}}! 🥗 Assistente da Dra. Débora aqui.
Sua última consulta foi em {{2}} e a Dra. Débora lembra do seu objetivo de {{3}}.
Que tal retomarmos juntos? Como está sua alimentação esta semana?

---

### TEMPLATE 3 — Boas-vindas Novo Paciente
**Friendly Name:** nutrideby_boas_vindas
**Category:** UTILITY
**Language:** pt-BR

**Body:**
Olá, {{1}}! Seja bem-vindo(a) ao acompanhamento da Dra. Débora Oliver. 🌱
Estou aqui para te apoiar entre as consultas.
Você pode me enviar fotos dos seus exames ou das suas refeições e eu farei uma análise personalizada para você.
Vamos começar?

---

### TEMPLATE 4 — Confirmação de Análise Recebida
**Friendly Name:** nutrideby_analise_recebida
**Category:** UTILITY
**Language:** pt-BR

**Body:**
Recebi sua {{1}}, {{2}}! 📋
Estou analisando com base no seu histórico clínico.
Em instantes você recebe o retorno da Dra. Débora. 🥗

---

### TEMPLATE 5 — Alerta Exame Fora do Padrão
**Friendly Name:** nutrideby_alerta_exame
**Category:** UTILITY
**Language:** pt-BR

**Body:**
{{1}}, identifiquei algo importante nos seus exames. 🔍
O valor de {{2}} está {{3}} (meta: {{4}}).
A Dra. Débora será notificada. Enquanto isso, evite {{5}} e prefira {{6}}.
Dúvidas? É só me perguntar! 🥗

---

### TEMPLATE 6 — Lembrete Consulta
**Friendly Name:** nutrideby_lembrete_consulta
**Category:** UTILITY
**Language:** pt-BR

**Body:**
Oi, {{1}}! 📅 Lembrete: sua consulta com a Dra. Débora é {{2}}.
Antes da consulta, tente anotar:
✅ Como foi sua alimentação esta semana
✅ Dúvidas que quer tirar
✅ Exames recentes (pode me enviar foto!)
Até lá! 🥗

---

## Como cadastrar no Twilio Content Template Builder

1. Acesse: console.twilio.com → Messaging → Content Template Builder
2. Clique em "Create new template"
3. Selecione "WhatsApp" como canal
4. Preencha:
   - Template Name: (friendly name acima)
   - Language: Portuguese (Brazil)
   - Category: Utility
   - Body: (texto acima — substitua {{N}} pelos campos)
5. Submit for approval
6. Aguardar aprovação Meta (normalmente 24-48h após bundle aprovado)

## Variáveis por template

| Template | {{1}} | {{2}} | {{3}} | {{4}} | {{5}} | {{6}} |
|---|---|---|---|---|---|---|
| reativacao_simples | nome_paciente | — | — | — | — | — |
| reativacao_clinica | nome_paciente | data_ultima_consulta | objetivo | — | — | — |
| boas_vindas | nome_paciente | — | — | — | — | — |
| analise_recebida | tipo (foto/exame) | nome_paciente | — | — | — | — |
| alerta_exame | nome_paciente | nome_exame | status(alto/baixo) | valor_meta | alimento_evitar | alimento_preferir |
| lembrete_consulta | nome_paciente | data_hora | — | — | — | — |

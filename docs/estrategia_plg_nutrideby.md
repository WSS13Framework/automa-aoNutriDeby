# Estratégia Product-Led Growth (PLG) para o NutriDeby

## 1. O que é Product-Led Growth (PLG)?

O **Product-Led Growth (PLG)** é uma estratégia de Go-To-Market (GTM) onde o próprio produto é o principal motor de aquisição, ativação, retenção e expansão de clientes [1]. Em vez de depender de uma equipe de vendas (Sales-Led) para fazer demonstrações, negociar contratos e fechar negócios, o PLG permite que o usuário experimente o valor do produto por conta própria antes de pagar.

Para um SaaS B2B focado em profissionais independentes e pequenas clínicas (como nutricionistas), o PLG não é apenas uma opção, é uma necessidade de sobrevivência. Modelos dependentes de vendas (Sales-Led) possuem um Custo de Aquisição de Clientes (CAC) muito alto, o que inviabiliza a venda de assinaturas de baixo ticket (ex: R$ 97 a R$ 297/mês).

### Por que PLG para o NutriDeby?

De acordo com o relatório *State of B2B SaaS 2025* da ProductLed (análise de 446 empresas), a transição para uma receita *self-serve* (onde o cliente compra sozinho) é a alavanca de performance mais forte para um SaaS [2]. Empresas que implementam o modelo *self-serve* relatam:
- Aumento de 14.5% na performance geral.
- Melhoria de 25.9% na conversão de usuários gratuitos para pagos.
- Redução de 18.3% no *Time-to-Value* (tempo até o usuário perceber o valor).
- Margens de lucro quase dobradas (68% vs 36.4% em modelos tradicionais) [2].

## 2. O Funil PLG do NutriDeby

No modelo PLG, o funil tradicional de marketing e vendas é substituído por um funil focado no comportamento do usuário dentro do produto. O objetivo é levar o nutricionista do "cadastro" ao "momento Aha!" o mais rápido possível.

### Etapa 1: Aquisição (Self-Serve Onboarding)
O nutricionista descobre o NutriDeby (via tráfego orgânico, indicação ou anúncio) e clica em "Começar Gratuitamente".
- **Ação:** Cadastro rápido (apenas e-mail e senha ou Google OAuth).
- **Fricção Zero:** Não pedimos cartão de crédito neste momento. Não exigimos agendamento de demonstração.

### Etapa 2: Ativação (Time-to-Value)
Esta é a métrica mais crítica do PLG. O *Time-to-Value* (TTV) mede quão rápido o usuário experimenta o valor central do produto [2].
- **O "Momento Aha!" do NutriDeby:** Ocorre quando o nutricionista conecta seu WhatsApp via QR Code e a IA processa a primeira foto de refeição de um paciente teste.
- **Estratégia:** O painel deve guiar o nutricionista imediatamente para a tela de conexão do WhatsApp (Evolution API). Devemos fornecer um "paciente de teste" pré-configurado para que ele veja a IA funcionando em menos de 3 minutos após o cadastro.

### Etapa 3: Retenção e Engajamento
O produto deve se tornar um hábito.
- **Ação:** O nutricionista começa a convidar seus pacientes reais para interagir com o bot no WhatsApp.
- **Métrica:** *Product Qualified Leads* (PQLs). Um PQL é um usuário que atingiu um marco de engajamento que indica alta probabilidade de compra. No NutriDeby, um PQL pode ser definido como: "Nutricionista que conectou o WhatsApp e tem pelo menos 3 pacientes ativos interagindo com a IA na última semana".

### Etapa 4: Monetização (Conversão)
A cobrança ocorre de forma natural quando o usuário atinge um limite de uso (Paywall).
- **Ação:** O nutricionista atinge o limite do plano gratuito (ex: máximo de 5 pacientes ou 100 mensagens de IA) e é convidado a assinar o plano Pro via Stripe.

## 3. Freemium vs. Free Trial: Qual Escolher?

A escolha do modelo de entrada define a velocidade de adoção. Os dados de mercado de 2025/2026 mostram um cenário claro:

| Modelo | Taxa de Conversão (Visitante para Cadastro) | Taxa de Conversão (Cadastro para Pago) | Recomendação para NutriDeby |
| :--- | :--- | :--- | :--- |
| **Freemium** | 13% a 16% [3] | ~5% [4] | **Ideal para o MVP.** Reduz a barreira psicológica a zero. O nutricionista pode usar com 2 ou 3 pacientes para sempre. A monetização ocorre quando ele decide escalar para toda a clínica. |
| **Free Trial (Sem Cartão)** | 7% a 8% | 10% a 15% [4] | Cria urgência (ex: 14 dias grátis), mas gera ansiedade. Muitos profissionais abandonam se não tiverem tempo de testar naquelas duas semanas. |
| **Free Trial (Com Cartão)** | Baixíssima | ~60% [4] | Alta fricção na entrada. Destrói a aquisição orgânica em mercados de profissionais independentes. |

**Recomendação Estratégica:** O NutriDeby deve adotar um modelo **Freemium Intencional**. O relatório da ProductLed destaca que empresas com modelos gratuitos "intencionais" (onde as limitações de valor criam caminhos orgânicos de upgrade) têm taxas de conversão 57% melhores [2]. O plano gratuito do NutriDeby deve ser excelente para um número muito pequeno de pacientes, forçando o upgrade apenas quando o nutricionista já estiver dependente da automação para gerenciar seu volume de trabalho.

## 4. Implementação Técnica do PLG no NutriDeby

Para que o PLG funcione, a arquitetura técnica (que discutimos na pesquisa anterior) deve suportar o modelo *self-serve*:

1. **Multi-Tenancy Automático:** Quando o nutricionista se cadastra, o backend (FastAPI/PostgreSQL) deve criar automaticamente um novo `tenant_id` e isolar seus dados via Row-Level Security (RLS). Nenhuma intervenção manual (admin) deve ser necessária.
2. **Integração Stripe Billing:** O painel Next.js deve ter uma aba de "Assinatura" integrada ao Stripe Customer Portal. O nutricionista faz o upgrade, insere o cartão e o webhook do Stripe atualiza o status do `tenant` no banco de dados instantaneamente.
3. **Métricas de Produto (Analytics):** Precisamos rastrear eventos-chave (ex: `whatsapp_connected`, `first_patient_added`, `ai_message_processed`) usando ferramentas como PostHog ou Mixpanel para identificar onde os usuários estão travando no funil de ativação.

## 5. Resumo Executivo

O PLG transforma o NutriDeby de um "software vendido" para um "software comprado". Ao focar em um *Time-to-Value* extremamente curto (conectar o WhatsApp e ver a IA funcionar em 3 minutos) e adotar um modelo Freemium com limites de uso claros, eliminamos a necessidade de uma equipe de vendas. O produto se vende sozinho pela eficiência que entrega na rotina do nutricionista.

---

## Referências

[1] RevenueML. "Product-Led Growth vs Sales-Led Growth: What Executives Need to Know". Disponível em: https://revenueml.com/insights/articles/product-led-growth-vs-sales-led-growth
[2] ProductLed. "State of B2B SaaS in 2025 (Analysis of 446 Companies)". Disponível em: https://productled.com/blog/state-of-b2b-saas-2025-report
[3] SaaS Factor. "Freemium vs Trial Models in SaaS: What Really Boosts Conversions". Disponível em: https://www.saasfactor.co/blogs/freemium-vs-trial-models-in-saas-what-really-boosts-conversions
[4] Elena Verna. "Dirty dozen of PLG B2B SaaS health metrics". Disponível em: https://www.elenaverna.com/p/dirty-dozen-of-plg-b2b-saas-health

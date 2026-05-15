# 6. Roadmap: Migração para SaaS Multi-Tenant

## Contexto

O NutriDeby está sendo remodelado de uma ferramenta single-tenant (uma clínica) para um **SaaS B2B2C Multi-Tenant** com modelo de negócio **Product-Led Growth (PLG)**. Este documento descreve a arquitetura-alvo e os passos de migração.

## Modelo de Negócio

### Público-Alvo

- **B2B (Pagante):** Nutricionistas e clínicas de nutrição.
- **B2C (Usuário Final):** Pacientes que interagem via WhatsApp.

### Monetização (Freemium)

| Plano | Limite | Preço |
| :--- | :--- | :--- |
| Free | 3 pacientes ativos, 50 mensagens IA/mês | R$ 0 |
| Pro | 50 pacientes, 2.000 mensagens IA/mês | R$ 97/mês |
| Clínica | Ilimitado, múltiplos profissionais | R$ 297/mês |

### Funil PLG

1. **Aquisição:** Nutricionista se cadastra sozinha (self-service).
2. **Ativação:** Conecta WhatsApp via QR Code e vê a IA funcionar em menos de 3 minutos.
3. **Retenção:** Pacientes interagem diariamente com o bot.
4. **Monetização:** Atinge limite do plano Free e faz upgrade via Stripe.

## Arquitetura-Alvo

### Banco de Dados (Multi-Tenancy com RLS)

```sql
-- Tabela de tenants (clínicas/consultórios)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Tabela de usuários (nutricionistas)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'nutritionist',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Adicionar tenant_id nas tabelas existentes
ALTER TABLE patients ADD COLUMN tenant_id UUID REFERENCES tenants(id);

-- Row-Level Security
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON patients
    USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

### Autenticação (Migração NextAuth → PostgreSQL)

O `auth.ts` será alterado para consultar a tabela `users` no banco:

```typescript
async authorize(credentials) {
  const user = await db.query(
    "SELECT * FROM users WHERE email = $1", [credentials.email]
  );
  if (user && await bcrypt.compare(credentials.password, user.password_hash)) {
    return { id: user.id, tenant_id: user.tenant_id, ... };
  }
  return null;
}
```

### Integração WhatsApp (Evolution API)

Cada tenant terá sua própria instância de conexão WhatsApp:

```
Paciente (WhatsApp) → Evolution API → Webhook → API FastAPI → PostgreSQL
                                                      ↓
                                              OpenAI (processamento)
                                                      ↓
                                              Resposta via WhatsApp
```

### Billing (Stripe)

- Stripe Checkout para upgrade de plano.
- Stripe Webhooks para atualizar status do tenant no banco.
- Stripe Customer Portal para o nutricionista gerenciar assinatura.

## Fases de Implementação

### Fase 1: Fundação Multi-Tenant
- [ ] Criar tabelas `tenants` e `users`.
- [ ] Migrar `auth.ts` para consultar banco.
- [ ] Adicionar `tenant_id` em `patients` e `chunks`.
- [ ] Implementar RLS no PostgreSQL.
- [ ] Criar endpoint de cadastro (self-service).

### Fase 2: Integração WhatsApp
- [ ] Deploy da Evolution API.
- [ ] Tela de conexão WhatsApp (QR Code) no dashboard.
- [ ] Webhook de recebimento de mensagens.
- [ ] Pipeline de processamento (foto de refeição → classificação IA).

### Fase 3: Billing e Limites
- [ ] Integração Stripe (checkout + webhooks).
- [ ] Middleware de verificação de limites por plano.
- [ ] Tela de assinatura no dashboard.

### Fase 4: Onboarding e Growth
- [ ] Paciente de teste pré-configurado (Time-to-Value < 3 min).
- [ ] Analytics de produto (PostHog/Mixpanel).
- [ ] Landing page com CTA "Começar Gratuitamente".

## Referências

- [Pesquisa: Modelo Chinês de SaaS em Saúde](../docs/pesquisa_modelo_chines_saas_saude.md)
- [Estratégia PLG para o NutriDeby](../docs/estrategia_plg_nutrideby.md)

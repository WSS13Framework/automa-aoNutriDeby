# NutriDeby Dashboard

Dashboard de IA para acompanhamento nutricional. Plataforma completa para nutricionistas gerenciarem pacientes, gerarem condutas com IA (DeepSeek/Groq + Tabela TACO) e se comunicarem via WhatsApp e videochamada.

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Frontend | Next.js 14 + React 18 + TypeScript + Tailwind CSS |
| Gráficos | Recharts |
| Backend | Next.js API Routes |
| Banco | PostgreSQL 16 + pgvector |
| IA | DeepSeek V3 (ativo) / Groq Llama 3.1 (preparado) |
| WhatsApp | Evolution API |
| Videochamada | Google Meet / Zoom |
| Infra | Docker + docker-compose |

## Funcionalidades

- Login com email/senha (JWT + bcrypt, HttpOnly cookie)
- Sidebar com busca de pacientes em tempo real
- Perfil consolidado (nome, idade, altura, peso, IMC, foto)
- Metas nutricionais com barra de progresso
- Gráfico de engajamento (Recharts, últimos 7 dias)
- Alertas clínicos (sem resposta >48h, exames alterados)
- Sugestões de conduta geradas pela IA (com edição)
- Envio via WhatsApp com um clique (Evolution API)
- Videochamada integrada (Google Meet/Zoom) com envio automático do link
- Tema claro/escuro
- Mobile-first (sidebar drawer, touch-friendly)
- Skeleton loading e tratamento de erros
- LGPD compliant

## Provider Layer (Abstrato)

```typescript
interface LLMProvider {
  name: string;
  analyze(patientData: PatientData, query: string): Promise<LLMResponse>;
}
```

- **DeepSeekProvider**: implementação ativa, modelo `deepseek-chat` (V3)
- **GroqProvider**: implementação preparada, modelo `llama-3.1-70b-versatile`
- Seleção via `LLM_PROVIDER=deepseek|groq` no `.env`

## Estrutura

```
dashboard/
├── Dockerfile (multi-stage)
├── docker-compose.yml
├── init.sql (schema + seed)
├── .env.example
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── login/page.tsx
│   │   ├── page.tsx (dashboard)
│   │   ├── pacientes/[id]/page.tsx
│   │   └── api/
│   │       ├── auth/login/route.ts
│   │       ├── pacientes/route.ts
│   │       ├── consulta/iniciar/route.ts
│   │       └── analyze/route.ts
│   ├── components/
│   │   ├── Sidebar.tsx
│   │   ├── LoginForm.tsx
│   │   ├── PatientProfile.tsx
│   │   ├── GoalsCard.tsx
│   │   ├── EngagementChart.tsx
│   │   ├── AlertsPanel.tsx
│   │   ├── ConductSuggestions.tsx
│   │   ├── VideoCall.tsx
│   │   ├── SendViaWhatsApp.tsx
│   │   └── ThemeToggle.tsx
│   ├── lib/
│   │   ├── db.ts
│   │   ├── auth.ts
│   │   ├── tacodb.ts
│   │   ├── whatsapp.ts
│   │   └── llm/
│   │       ├── provider.ts
│   │       ├── deepseek.ts
│   │       └── groq.ts
│   ├── types/
│   │   └── patient.ts
│   └── middleware.ts
└── public/
```

## Setup Rápido

```bash
# 1. Copiar variáveis de ambiente
cp .env.example .env
# Editar .env com suas credenciais

# 2. Subir com Docker
docker compose up -d

# 3. Acessar
# http://localhost:3000
# Login: admin@nutrideby.com.br / nutrideby2024
```

## Desenvolvimento Local

```bash
# Instalar dependências
pnpm install

# Rodar em dev (precisa do PostgreSQL rodando)
pnpm dev
```

## Variáveis de Ambiente

| Variável | Descrição | Obrigatória |
|----------|-----------|-------------|
| `DATABASE_URL` | Connection string PostgreSQL | Sim |
| `JWT_SECRET` | Segredo para assinar tokens JWT | Sim |
| `LLM_PROVIDER` | Provider de IA: `deepseek` ou `groq` | Sim |
| `DEEPSEEK_API_KEY` | Chave da API DeepSeek | Se provider=deepseek |
| `GROQ_API_KEY` | Chave da API Groq | Se provider=groq |
| `EVOLUTION_API_URL` | URL da Evolution API (WhatsApp) | Para envio WhatsApp |
| `EVOLUTION_API_KEY` | Chave da Evolution API | Para envio WhatsApp |

## Fluxo de Operação

1. Nutricionista faz login no painel
2. Abre o paciente na sidebar (busca por nome)
3. Visualiza prontuário completo, metas e histórico
4. Clica em "Gerar Sugestão com IA" — DeepSeek analisa dados + TACO
5. Revisa/edita a sugestão
6. Um clique para enviar a conduta via WhatsApp
7. Inicia videochamada — link enviado automaticamente ao paciente
8. Paciente responde no WhatsApp → dados voltam ao banco → IA gera novas sugestões

## Segurança

- Senhas com bcrypt (12 rounds)
- JWT com expiração de 8h em HttpOnly cookie
- Middleware protege todas as rotas (exceto /login)
- Credenciais apenas via variáveis de ambiente
- LGPD: dados sensíveis no PostgreSQL com acesso controlado

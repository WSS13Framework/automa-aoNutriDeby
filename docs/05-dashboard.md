# 5. Dashboard (Painel do Profissional)

## Acesso

- **URL:** `http://IP_DO_SERVIDOR:3000`
- **Login:** Credenciais definidas nas variáveis `ADMIN_EMAIL` e `ADMIN_PASSWORD` do arquivo `dashboard/.env`

## Funcionalidades

### Alertas Clínicos

O painel exibe alertas automáticos baseados nos dados do banco:

- **IA Indisponível:** Pacientes sem embeddings indexados. A busca inteligente (RAG) não funciona para eles.
- **Sem Atualização +7 dias:** Pacientes sem atualização nos últimos 7 dias.
- **Prontuário Incompleto:** Pacientes com apenas o marcador 204 (API Dietbox retornou vazio).

### Busca Inteligente (RAG)

Permite buscar informações nos prontuários dos pacientes usando linguagem natural. Exemplo: "Quais são as restrições alimentares da Maria?" — a IA busca nos chunks embedados e retorna os trechos mais relevantes.

### Lista de Pacientes

Visualização dos pacientes cadastrados com informações de cobertura de dados (chunks totais, embedados, pendentes).

## Arquitetura Técnica

O dashboard é um aplicativo Next.js 14 com App Router, compilado em modo `standalone` (otimizado para containers Docker).

### Fluxo de Dados

```
Navegador → Dashboard (Next.js :3000)
                 │
                 │ Server-side fetch
                 ▼
            API FastAPI (:8080 via rede Docker)
                 │
                 ▼
            PostgreSQL + pgvector
```

### Variáveis de Ambiente (Build Time vs Runtime)

O Next.js standalone compila variáveis de ambiente no momento do build. Isso significa que:
- Variáveis definidas no Dockerfile (como ARG/ENV no estágio `builder`) são "inlined" no `server.js` compilado.
- Variáveis definidas apenas no `env_file` do docker-compose são disponibilizadas no runtime do container.
- Para variáveis que precisam estar disponíveis no código server-side (como `NUTRIDEBY_API_URL`), elas devem estar presentes **tanto no build quanto no runtime**.

### Rebuild do Dashboard

Quando qualquer código TypeScript do dashboard mudar:

```bash
docker compose --profile api build --no-cache dashboard
docker compose --profile api up -d dashboard
```

Quando apenas variáveis de ambiente mudarem (e o código não mudou):

```bash
# Editar dashboard/.env
docker compose --profile api restart dashboard
```

## Autenticação

O dashboard usa NextAuth.js com CredentialsProvider. No MVP atual, a autenticação é feita contra variáveis de ambiente (single admin). Na versão SaaS, será migrada para consulta ao banco PostgreSQL com tabela `users`.

### Fluxo de Login

1. Usuário envia email + senha no formulário.
2. NextAuth chama a função `authorize()` em `src/lib/auth.ts`.
3. A função compara com `ADMIN_EMAIL` e `ADMIN_PASSWORD`.
4. Se válido, gera um JWT e redireciona para `/dashboard`.
5. Todas as rotas protegidas verificam o JWT via middleware.

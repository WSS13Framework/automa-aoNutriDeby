# 3. Guia de Deploy e Manutenção

## Pré-requisitos

- Servidor Ubuntu 22.04+ com Docker e Docker Compose instalados.
- Git configurado com acesso ao repositório GitHub.
- Mínimo 2 GB RAM, 2 vCPUs, 50 GB disco.

## Deploy Inicial

### 1. Clonar o repositório

```bash
cd /opt
git clone https://github.com/WSS13Framework/automa-aoNutriDeby.git
cd automa-aoNutriDeby
git checkout feat/dashboard-rebuild
```

### 2. Configurar variáveis de ambiente

```bash
# API/Backend (.env na raiz)
cp .env.example .env
# Editar .env com as credenciais reais (OPENAI_API_KEY, DATABASE_URL, etc.)

# Dashboard (dashboard/.env)
cat > dashboard/.env << 'EOF'
NEXTAUTH_URL=http://SEU_IP:3000
NEXTAUTH_SECRET=gere-uma-string-aleatoria-com-openssl-rand-base64-32
ADMIN_EMAIL=admin@nutrideby.com.br
ADMIN_PASSWORD=SENHA_SEGURA_AQUI
NUTRIDEBY_API_URL=http://api:8080
NUTRIDEBY_API_KEY=SUA_API_KEY_AQUI
EOF
```

**IMPORTANTE:** Nunca commitar arquivos `.env` no repositório. Eles contêm credenciais sensíveis.

### 3. Subir os serviços

```bash
# Sobe banco + cache + API + dashboard
docker compose --profile api up -d

# Verifica se tudo está saudável
docker compose --profile api ps
docker compose logs --tail 10
```

### 4. Verificar funcionamento

```bash
# Health check da API
curl -s http://localhost:8081/health

# Testar rota de pacientes
curl -s "http://localhost:8081/v1/patients?limit=3" -H "X-API-Key: SUA_KEY"
```

## Manutenção Rotineira

### Atualizar código (deploy de novas versões)

```bash
cd /opt/automa-aoNutriDeby
git pull origin feat/dashboard-rebuild

# Se mudou código Python (API):
docker compose --profile api restart api

# Se mudou código Next.js (Dashboard):
docker compose --profile api build --no-cache dashboard
docker compose --profile api up -d dashboard

# Se mudou docker-compose.yml:
docker compose --profile api up -d
```

### Verificar logs

```bash
# Todos os serviços
docker compose logs --tail 50

# Serviço específico
docker compose logs api --tail 30
docker compose logs dashboard --tail 30
docker compose logs postgres --tail 30
```

### Backup do banco de dados

```bash
# Dump completo
docker compose exec postgres pg_dump -U nutrideby nutrideby > backup_$(date +%Y%m%d).sql

# Restore
cat backup_YYYYMMDD.sql | docker compose exec -T postgres psql -U nutrideby nutrideby
```

### Limpar imagens Docker antigas

```bash
docker image prune -f
docker builder prune -f
```

### Restart completo (em caso de problemas)

```bash
docker compose --profile api down
docker compose --profile api up -d
```

## Troubleshooting

### Erro "API 500" no Dashboard

1. Verificar logs da API: `docker compose logs api --tail 30`
2. Testar API diretamente: `curl -s http://localhost:8081/health`
3. Verificar se as variáveis de ambiente estão no container do dashboard: `docker compose exec dashboard printenv | grep NUTRI`

### Dashboard não faz login (Credenciais inválidas)

1. Verificar se `ADMIN_EMAIL` e `ADMIN_PASSWORD` estão no container: `docker compose exec dashboard printenv | grep ADMIN`
2. Se as variáveis não aparecem, o dashboard precisa de rebuild: `docker compose --profile api build --no-cache dashboard && docker compose --profile api up -d dashboard`

### Build do Dashboard usa cache antigo

Forçar rebuild sem cache:
```bash
docker rmi automa-aonutrideby-dashboard -f
docker builder prune -f
docker compose --profile api build --no-cache dashboard
```

### PostgreSQL não inicia

Verificar se o volume `pgdata` não está corrompido:
```bash
docker compose logs postgres --tail 20
# Se necessário, remover volume e recriar (PERDA DE DADOS):
# docker compose down -v  # CUIDADO: apaga todos os dados
```

## Variáveis de Ambiente

### API (.env na raiz)

| Variável | Descrição | Exemplo |
| :--- | :--- | :--- |
| `DATABASE_URL` | Connection string PostgreSQL | `postgresql://nutrideby:PASS@localhost:5432/nutrideby` |
| `REDIS_URL` | Connection string Redis | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | Chave da API OpenAI (embeddings) | `sk-...` |
| `API_KEY` | Chave de autenticação da API REST | `dev-test-2026` |

### Dashboard (dashboard/.env)

| Variável | Descrição | Exemplo |
| :--- | :--- | :--- |
| `NEXTAUTH_URL` | URL pública do dashboard | `http://143.198.95.64:3000` |
| `NEXTAUTH_SECRET` | Secret para JWT do NextAuth | `openssl rand -base64 32` |
| `ADMIN_EMAIL` | Email do admin | `admin@nutrideby.com.br` |
| `ADMIN_PASSWORD` | Senha do admin (texto plano) | `senhaSegura123` |
| `NUTRIDEBY_API_URL` | URL interna da API (rede Docker) | `http://api:8080` |
| `NUTRIDEBY_API_KEY` | Chave de autenticação da API | `dev-test-2026` |

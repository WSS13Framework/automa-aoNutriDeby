# Guia de Deploy - NutriDeby (Servidor de Produção)

Este guia descreve os passos exatos para subir toda a infraestrutura (API, Dashboard, PostgreSQL, Redis) no seu servidor Linux, utilizando Docker Compose.

## 1. Pré-requisitos no Servidor

Certifique-se de que o servidor possui:
- **Git** instalado (`sudo apt install git`)
- **Docker** e **Docker Compose** instalados e rodando.

## 2. Clonar o Repositório

No seu servidor, acesse o diretório onde deseja hospedar o projeto e faça o pull da branch mais recente:

```bash
cd /caminho/para/seu/diretorio
git clone -b feat/dashboard-nextjs https://github.com/WSS13Framework/automa-aoNutriDeby.git
cd automa-aoNutriDeby
```

*(Se já tiver clonado, basta fazer `git pull origin feat/dashboard-nextjs`)*

## 3. Configurar Variáveis de Ambiente

Você precisa configurar dois arquivos `.env`: um na raiz (para a API e Workers) e outro na pasta `dashboard`.

### 3.1. Arquivo `.env` (Raiz)

Copie o template e edite com suas credenciais reais:

```bash
cp .env.example .env
nano .env
```

**Variáveis Críticas a preencher no `.env`:**
- `OPENAI_API_KEY`: Sua chave da OpenAI (sk-proj-...)
- `OPENSEARCH_URL`, `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD`: Credenciais do seu cluster OpenSearch na DigitalOcean.
- `NUTRIDEBY_API_KEY`: Uma chave segura que você inventar (ex: `minha-chave-secreta-123`).

### 3.2. Arquivo `dashboard/.env` (Dashboard)

Copie o template e edite:

```bash
cd dashboard
cp .env.example .env
nano .env
```

**Variáveis Críticas a preencher no `dashboard/.env`:**
- `NEXTAUTH_SECRET`: Gere uma string aleatória (ex: rode `openssl rand -base64 32` no terminal e cole o resultado aqui).
- `NUTRIDEBY_API_KEY`: A **mesma** chave que você colocou no `.env` da raiz.
- `ADMIN_EMAIL`: O email que você usará para logar no painel.
- `ADMIN_PASSWORD_HASH`: O hash bcrypt da sua senha. Para gerar um hash rápido para a senha "123456", você pode usar um gerador online de bcrypt ou rodar um script Node rápido. (Exemplo de hash para "123456": `$2a$12$R9h/cIPz0gi.URNNX3cam2OsQsqTfzxG0Wpriv6ASZ.`)

Volte para a raiz do projeto:
```bash
cd ..
```

## 4. Subir a Infraestrutura (Docker Compose)

Com os `.env` configurados, suba todos os serviços:

```bash
docker compose --profile api up -d --build
```

Isso irá iniciar:
1. **postgres**: Banco de dados com pgvector na porta 5432.
2. **redis**: Fila/Cache na porta 6379.
3. **api**: FastAPI rodando na porta 8081.
4. **dashboard**: Painel Next.js rodando na porta 3000.

Para verificar se tudo subiu corretamente:
```bash
docker compose ps
```

## 5. Acessar o Sistema

- **Dashboard:** Acesse `http://IP_DO_SEU_SERVIDOR:3000` no navegador. Faça login com o email e senha configurados.
- **API:** A API estará respondendo em `http://IP_DO_SEU_SERVIDOR:8081`.

---

## 6. Integração com n8n / OpenClaw (A "Vendedora")

Para que a sua IA (via n8n ou OpenClaw) consiga buscar os dados dos pacientes, você deve configurar uma **Tool (Ferramenta)** no seu orquestrador apontando para a sua API.

### Configuração da Tool (HTTP Request)

- **Método:** `POST`
- **URL:** `http://IP_DO_SEU_SERVIDOR:8081/v1/patients/{patient_id}/retrieve`
  *(Nota: O `{patient_id}` deve ser o UUID do paciente que a IA está atendendo)*
- **Headers:**
  - `Content-Type`: `application/json`
  - `X-API-Key`: `[A_CHAVE_QUE_VOCE_COLOCOU_NO_ENV]`
- **Body (JSON):**
  ```json
  {
    "query": "A pergunta que a IA quer fazer sobre o paciente",
    "k": 5
  }
  ```

### Prompt Sugerido para a IA (Vendedora)

Configure o System Prompt do seu agente com as seguintes diretrizes:

```text
Você é a assistente virtual inteligente da NutriDeby. Seu objetivo é atuar como uma "vendedora" e consultora de saúde, oferecendo um atendimento humanizado, empático e focado em resultados via WhatsApp.

DIRETRIZES DE ATENDIMENTO:
1. Você tem acesso ao histórico clínico, metas e plano alimentar do paciente através da ferramenta 'Buscar Histórico' (patient_retrieve).
2. SEMPRE consulte o histórico do paciente antes de responder perguntas específicas sobre a dieta ou progresso dele.
3. Use um tom encorajador. Se o paciente relatar dificuldades, ofereça soluções práticas baseadas no plano dele e sugira agendar uma nova consulta se necessário (foco em retenção/venda).
4. Nunca invente dados médicos. Se a informação não estiver no histórico retornado pela ferramenta, diga que precisa confirmar com a nutricionista responsável.
```

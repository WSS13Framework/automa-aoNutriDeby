# 1. Visão Geral do Projeto

## O que é o NutriDeby

O NutriDeby não é uma ferramenta de consulta; é um **Agente de Execução**. O nutricionista é o "Diretor" e a IA é o "Gerente de Operações" que cuida de cada paciente proativamente.

É uma plataforma de automação para nutricionistas que combina inteligência artificial com dados clínicos para otimizar o acompanhamento de pacientes. O sistema opera em três camadas:

1. **Motor de IA (Backend Python/FastAPI):** Processa dados de pacientes, gera embeddings vetoriais para busca semântica (RAG) e fornece insights clínicos automatizados.
2. **Dashboard (Next.js):** Painel web para o profissional visualizar alertas, buscar informações nos prontuários via IA e gerenciar pacientes.
3. **Integração WhatsApp (Evolution API):** Interface de comunicação com o paciente via bot inteligente (em desenvolvimento).

## Stack Tecnológica

| Camada | Tecnologia | Propósito |
| :--- | :--- | :--- |
| Banco de Dados | PostgreSQL 16 + pgvector | Armazenamento de pacientes, documentos, chunks e embeddings vetoriais |
| Cache | Redis 7 | Fila de jobs, cache de embeddings |
| API Backend | Python 3.10 + FastAPI + Uvicorn | Endpoints REST, processamento de dados, RAG |
| Dashboard | Next.js 14 + TypeScript + TailwindCSS | Painel do profissional |
| Autenticação | NextAuth.js (JWT) | Login do profissional no dashboard |
| Containerização | Docker Compose | Orquestração de todos os serviços |
| Servidor | DigitalOcean Droplet (Ubuntu) | Hospedagem |

## Estrutura do Repositório

```
automa-aoNutriDeby/
├── src/nutrideby/          # Backend Python (API + Workers)
│   ├── api/main.py         # FastAPI - endpoints REST
│   ├── extraction/         # Scripts de extração de dados (Dietbox, etc.)
│   └── embeddings/         # Geração de embeddings vetoriais
├── dashboard/              # Frontend Next.js
│   ├── src/app/            # App Router (páginas e API routes)
│   ├── src/components/     # Componentes React
│   ├── src/lib/            # Utilitários (auth, api client)
│   └── Dockerfile          # Build standalone do Next.js
├── infra/sql/              # Scripts SQL de inicialização do banco
├── docs/                   # Documentação do projeto (você está aqui)
├── docker-compose.yml      # Orquestração dos serviços
├── Dockerfile              # Imagem Python (API + Workers)
└── .env.example            # Template de variáveis de ambiente
```

## Status Atual (Maio/2026)

O projeto está na fase de **MVP funcional** com os seguintes componentes operacionais:
- 430 pacientes importados (dados reais da clínica).
- API REST funcional com busca semântica (RAG) nos prontuários.
- Dashboard com login, alertas clínicos e busca inteligente.
- Infraestrutura Docker Compose rodando em produção (DigitalOcean).

## Próximos Passos

O projeto será remodelado para um **SaaS B2B2C Multi-Tenant** com modelo de negócio Product-Led Growth (PLG). Detalhes no documento [06-roadmap-saas.md](./06-roadmap-saas.md).

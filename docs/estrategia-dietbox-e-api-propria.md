# Estratégia: Dietbox (ingestão) + API própria + RAG

Ver [README.md](../README.md) para comandos MVP. Este ficheiro resume o modelo de dependência.

## Dois mundos

- **dietbox.me** — site (IIS); frágil para automação.
- **api.dietbox.me** — API v2 JSON; usar **Bearer** no worker.

## Fonte da verdade

- Ingestão Dietbox → Postgres (`patients`, `documents`).
- Inteligência e API da nutricionista como camada seguinte (fora deste doc).

## Operações periódicas

- Token expira; novos pacientes no Dietbox; possíveis mudanças de API → jobs agendados.

## Monitorização

- Preferir smoke tests agendados a um agente 24×7 sem requisitos claros.

**Actualização:** 2026-05-02

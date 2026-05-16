# 4. API Reference

## Informações Gerais

- **Base URL:** `http://localhost:8081` (host) ou `http://api:8080` (rede Docker interna)
- **Autenticação:** Header `X-API-Key` obrigatório em todas as rotas `/v1/*`
- **Documentação interativa:** `http://localhost:8081/docs` (Swagger UI)
- **Formato:** JSON

## Endpoints

### Health Check

| Método | Rota | Auth | Descrição |
| :--- | :--- | :--- | :--- |
| GET | `/health` | Não | Verifica se a API está operacional |

**Resposta:** `{"status": "ok"}`

---

### Pacientes

| Método | Rota | Auth | Descrição |
| :--- | :--- | :--- | :--- |
| GET | `/v1/patients` | Sim | Lista pacientes com paginação |
| GET | `/v1/patients/{patient_id}` | Sim | Detalhes de um paciente |
| GET | `/v1/patients/by-external/{source_system}/{external_id}` | Sim | Busca paciente por ID externo |
| GET | `/v1/patients/rag-coverage` | Sim | Cobertura de embeddings (RAG) por paciente |

**GET /v1/patients** — Parâmetros query:
- `limit` (int, default 50): Número máximo de resultados.
- `offset` (int, default 0): Offset para paginação.

**GET /v1/patients/rag-coverage** — Parâmetros query:
- `limit` (int, default 200): Número máximo de resultados.
- `offset` (int, default 0): Offset para paginação.
- `source_system` (string, opcional): Filtrar por sistema de origem (ex: `dietbox`).
- `min_usable_embedded` (int, default 0): Mínimo de chunks úteis com embedding.

---

### Documentos

| Método | Rota | Auth | Descrição |
| :--- | :--- | :--- | :--- |
| GET | `/v1/patients/{patient_id}/documents` | Sim | Lista documentos de um paciente |

---

### Chunks e RAG (Busca Semântica)

| Método | Rota | Auth | Descrição |
| :--- | :--- | :--- | :--- |
| GET | `/v1/patients/{patient_id}/chunks` | Sim | Lista chunks de texto de um paciente |
| POST | `/v1/patients/{patient_id}/retrieve` | Sim | Busca semântica (RAG) nos prontuários |

**POST /v1/patients/{patient_id}/retrieve** — Body JSON:
```json
{
  "query": "Quais são as alergias alimentares?",
  "k": 5
}
```

**Resposta:**
```json
{
  "query": "Quais são as alergias alimentares?",
  "embedding_model": "text-embedding-3-small",
  "hits": [
    {
      "chunk_id": "uuid",
      "document_id": "uuid",
      "chunk_index": 0,
      "distance": 0.23,
      "score": 0.77,
      "text": "Paciente relata alergia a amendoim..."
    }
  ],
  "embedding_cache_hit": false
}
```

---

### Dietbox

| Método | Rota | Auth | Descrição |
| :--- | :--- | :--- | :--- |
| GET | `/v1/dietbox/subscription` | Sim | Status da assinatura Dietbox do nutricionista |

---

### Webhooks

| Método | Rota | Auth | Descrição |
| :--- | :--- | :--- | :--- |
| POST | `/hooks/kiwify/{secret}` | Via URL secret | Webhook de pagamentos Kiwify |

---

## Exemplo de Uso (curl)

```bash
# Listar pacientes
curl -s "http://localhost:8081/v1/patients?limit=10" \
  -H "X-API-Key: SUA_CHAVE"

# Busca semântica no prontuário de um paciente
curl -s "http://localhost:8081/v1/patients/UUID_DO_PACIENTE/retrieve" \
  -X POST \
  -H "X-API-Key: SUA_CHAVE" \
  -H "Content-Type: application/json" \
  -d '{"query": "histórico de peso", "k": 5}'
```

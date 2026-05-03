# O que é cada coisa na tabela `documents` (objectivo + analogia)

## Analogia (1 frase)

Cada linha em **`documents`** é **uma “pasta”** sobre o paciente: o campo **`doc_type`** é o **rótulo da pasta** (ex.: “prontuário Dietbox”, “export meta”); o campo **`content_text`** é o **papel lá dentro** — o texto (ou JSON em texto) que o RAG **parte em chunks** e embedda.  
Se tens **6 documentos**, tens **6 pastas** com **6 rótulos** possivelmente repetidos em pacientes diferentes, mas o conteúdo é por linha (`id` único).

---

## Colunas que interessam para “o que está guardado”

| Coluna | Significado |
|--------|-------------|
| `id` | UUID desta linha (identificador único do documento). |
| `patient_id` | A que paciente interno (`patients.id`) pertence. |
| **`doc_type`** | **Nome estável** da origem / semântica (string livre, mas nós usamos valores fixos no código). |
| **`content_text`** | **Corpo** do documento: texto corrido ou JSON **serializado em texto** (é isto que o `chunk_documents` lê). |
| `content_sha256` | Hash do `content_text` — idempotência (mesmo texto = não duplica). |
| `source_ref` | URL ou referência humana de onde veio (ex. path API). |
| `metadata` | JSON extra na linha (migração `002`); muitos inserts antigos deixam `{}`; metadados de sync podem estar em **`patients.metadata`**. |
| `collected_at` | Quando foi gravado. |

**RAG:** `chunk_documents` lê `documents.content_text` → cria linhas em **`chunks`** → `embed_chunks` preenche **`chunks.embedding`**.

---

## Catálogo de `doc_type` usados no código (NutriDeby)

Valores **exactos** como aparecem na base (copiar/colar para filtros).

| `doc_type` | Origem no código | O que é o `content_text` (o “interior”) |
|------------|------------------|----------------------------------------|
| **`dietbox_prontuario`** | `dietbox_sync` → `GET /v2/paciente/{id}/prontuario` | Se **200**: JSON do prontuário **pretty-printed** em texto. Se **204**: texto fixo `[Prontuário: API 204 sem corpo]`. |
| **`dietbox_meta_export`** | `dietbox_sync` → paginação `GET /v2/meta` | Um **único** JSON agregado (`schema: dietbox_meta_export_v1`, lista `items` com a linha do tempo / eventos da API). |
| **`dietbox_situacao_imc`** | `dietbox_sync` → fórmula MVC `SituacaoIMC` no site | Resposta (HTML ou texto) da fórmula no **site** `dietbox.me` — frágil; útil como registo do que a API MVC devolveu. |
| **`datebox_historico`** | `data_import` CSV | Coluna CSV `historico`. |
| **`datebox_prontuarios`** | `data_import` CSV | Coluna CSV `prontuarios`. |
| **`datebox_mensagens`** | `data_import` CSV | Coluna CSV `mensagens`. |
| **Qualquer string** | `data_import` JSON (`exemplo_import.json`) | O que vier no campo `doc_type` do JSON (ex.: `datebox_prontuarios` no exemplo). |

**Não são `documents`:** `external_snapshots` (ex. subscrição nutricionista), `integration_webhook_inbox` (Kiwify), etc. — outras tabelas.

---

## Consultas SQL para ver “o quê” tens (sem abrir Nano linha a linha)

**Contagem por tipo (toda a base):**

```sql
SELECT doc_type, count(*) AS n
FROM documents
GROUP BY doc_type
ORDER BY n DESC;
```

**Os teus 6 documentos — tipo + início do texto (sem despejar tudo):**

```sql
SELECT id, patient_id, doc_type, left(content_text, 200) AS inicio, length(content_text) AS chars, collected_at
FROM documents
ORDER BY collected_at DESC
LIMIT 20;
```

**Um paciente só:**

```sql
SELECT doc_type, length(content_text) AS chars, left(content_text, 120) AS inicio
FROM documents
WHERE patient_id = 'UUID-AQUI'
ORDER BY doc_type;
```

**Ligação ao RAG (há chunks deste documento?):**

```sql
SELECT d.doc_type, count(c.id) AS num_chunks
FROM documents d
LEFT JOIN chunks c ON c.document_id = d.id
GROUP BY d.doc_type
ORDER BY num_chunks DESC;
```

---

## Procedimento objectivo quando “não sabemos o que foi mapeado”

1. Correr a **primeira query** (contagem por `doc_type`) — vês **rótulos**.  
2. Correr a **segunda** com `LIMIT` — vês **início** do `content_text` e tamanho.  
3. Cruzar com a **tabela deste doc** acima — sabes **origem API** e **formato**.  
4. Se aparecer um `doc_type` **fora** da tabela — foi import manual/JSON ou código novo: tratar como **“tipo custom”** até documentares aqui.

---

## Manutenção deste ficheiro

Ao acrescentar um novo `doc_type` no código:

1. Inserir linha na tabela “Catálogo”.  
2. Referenciar ficheiro e função (ex. `dietbox_sync.py` → `sync_foo`).  

**Última actualização:** 2026-05-03

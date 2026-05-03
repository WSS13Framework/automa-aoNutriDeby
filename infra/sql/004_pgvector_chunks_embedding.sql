-- Plano B (fundação): extensão pgvector + coluna de embedding em chunks.
-- Requer Postgres compilado com pgvector (ex.: imagem pgvector/pgvector:pg16).
-- Dimensão 1536: alinhada a modelos OpenAI-compatíveis frequentes; ver docs/decisao-embeddings-vector-store.md

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

COMMENT ON COLUMN chunks.embedding IS 'Vector de embedding; dimensão fixa 1536 (ver docs/decisao-embeddings-vector-store.md).';

-- Índice para busca semântica quando houver linhas indexadas (parcial: ignora NULL).
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE embedding IS NOT NULL;

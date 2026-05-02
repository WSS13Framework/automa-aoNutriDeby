ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_documents_metadata_discipline
    ON documents ((metadata ->> 'discipline'))
    WHERE (metadata ->> 'discipline') IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_documents_metadata_gin
    ON documents USING gin (metadata jsonb_path_ops);

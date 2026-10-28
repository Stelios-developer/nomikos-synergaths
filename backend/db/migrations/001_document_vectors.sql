-- Applied by an operator/migrator role, never the API role.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS dmc;
CREATE TABLE dmc.vector_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    dimensions integer NOT NULL CHECK (dimensions BETWEEN 1 AND 16000),
    model text NOT NULL CHECK (length(model) > 0)
);
CREATE TABLE dmc.document_chunks (
    workspace_id text NOT NULL CHECK (length(workspace_id) BETWEEN 1 AND 128),
    chunk_id text NOT NULL CHECK (length(chunk_id) BETWEEN 1 AND 512),
    filename text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
    document text NOT NULL CHECK (length(document) > 0),
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata)='object'
        AND metadata ? 'session_id' AND metadata->>'session_id'=workspace_id
        AND metadata ? 'filename' AND metadata->>'filename'=filename),
    embedding public.vector NOT NULL,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (workspace_id, chunk_id),
    CHECK (vector_norm(embedding) > 0)
);
CREATE INDEX document_chunks_workspace_filename ON dmc.document_chunks(workspace_id, filename);
CREATE FUNCTION dmc.check_embedding_dimensions() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF vector_dims(NEW.embedding) IS DISTINCT FROM (SELECT dimensions FROM dmc.vector_config WHERE singleton) THEN
        RAISE EXCEPTION 'Embedding dimension does not match the configured model';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER document_chunks_dimensions BEFORE INSERT OR UPDATE ON dmc.document_chunks
    FOR EACH ROW EXECUTE FUNCTION dmc.check_embedding_dimensions();
ALTER TABLE dmc.document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE dmc.document_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY document_workspace ON dmc.document_chunks
    USING (workspace_id = current_setting('dmc.workspace_id', true))
    WITH CHECK (workspace_id = current_setting('dmc.workspace_id', true));
REVOKE ALL ON SCHEMA dmc FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA dmc FROM PUBLIC;
REVOKE ALL ON FUNCTION dmc.check_embedding_dimensions() FROM PUBLIC;

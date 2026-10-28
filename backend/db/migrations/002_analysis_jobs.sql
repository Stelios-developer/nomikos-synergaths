CREATE TABLE dmc.analysis_jobs (
    workspace_id text NOT NULL,
    job_id text NOT NULL CHECK (job_id ~ '^[0-9a-f]{32}$'),
    filename text NOT NULL,
    generation text NOT NULL CHECK (generation ~ '^[0-9a-f]{64}$'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('accepted','dispatching','complete','failed','uncertain')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    created_at timestamptz NOT NULL DEFAULT now(),
    deadline timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id,job_id),
    UNIQUE (workspace_id,fingerprint)
);
CREATE INDEX analysis_jobs_active ON dmc.analysis_jobs(workspace_id,filename,state);
ALTER TABLE dmc.analysis_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE dmc.analysis_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY analysis_job_workspace ON dmc.analysis_jobs
    USING (workspace_id=current_setting('dmc.workspace_id',true))
    WITH CHECK (workspace_id=current_setting('dmc.workspace_id',true));
REVOKE ALL ON dmc.analysis_jobs FROM PUBLIC;

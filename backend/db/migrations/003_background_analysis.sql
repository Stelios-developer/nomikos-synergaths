-- Additive queue metadata. Runtime APIs retain forced tenant RLS.
ALTER TABLE dmc.analysis_jobs DROP CONSTRAINT analysis_jobs_state_check;
ALTER TABLE dmc.analysis_jobs ADD CONSTRAINT analysis_jobs_state_check
    CHECK (state IN ('accepted','dispatching','complete','failed','uncertain','cancel_requested','cancelled'));
ALTER TABLE dmc.analysis_jobs DROP CONSTRAINT analysis_jobs_workspace_id_fingerprint_key;
CREATE UNIQUE INDEX analysis_jobs_live_intent ON dmc.analysis_jobs(workspace_id,fingerprint)
    WHERE state <> 'cancelled';
ALTER TABLE dmc.analysis_jobs
    ADD COLUMN pipeline_sha text CHECK (pipeline_sha IS NULL OR pipeline_sha ~ '^[0-9a-f]{64}$'),
    ADD COLUMN budget_seconds double precision NOT NULL DEFAULT 900 CHECK (budget_seconds > 0 AND budget_seconds <= 900),
    ADD COLUMN worker_id text CHECK (worker_id IS NULL OR worker_id ~ '^[0-9a-f]{32}$'),
    ADD COLUMN heartbeat_at timestamptz,
    ADD COLUMN observed_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN reason text NOT NULL DEFAULT '' CHECK (reason ~ '^[a-z_]{0,64}$');

CREATE TABLE dmc.analysis_job_events (
    workspace_id text NOT NULL,
    job_id text NOT NULL,
    event_id bigint GENERATED ALWAYS AS IDENTITY,
    event text NOT NULL CHECK (event ~ '^[a-z_]{1,64}$'),
    actor text NOT NULL CHECK (actor IN ('user','dispatcher','reconciler')),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id,job_id,event_id),
    FOREIGN KEY (workspace_id,job_id) REFERENCES dmc.analysis_jobs ON DELETE CASCADE
);
ALTER TABLE dmc.analysis_job_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE dmc.analysis_job_events FORCE ROW LEVEL SECURITY;
CREATE POLICY analysis_events_workspace ON dmc.analysis_job_events
    USING (workspace_id=current_setting('dmc.workspace_id',true))
    WITH CHECK (workspace_id=current_setting('dmc.workspace_id',true));
REVOKE ALL ON dmc.analysis_job_events FROM PUBLIC;

CREATE TABLE dmc.analysis_stages (
    workspace_id text NOT NULL,
    job_id text NOT NULL,
    stage text NOT NULL CHECK (stage ~ '^[a-z0-9_-]{1,80}$'),
    state text NOT NULL CHECK (state IN ('running','complete','uncertain')),
    token text NOT NULL CHECK (token ~ '^[0-9a-f]{32}$'),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY (workspace_id,job_id,stage),
    FOREIGN KEY (workspace_id,job_id) REFERENCES dmc.analysis_jobs ON DELETE CASCADE
);
ALTER TABLE dmc.analysis_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE dmc.analysis_stages FORCE ROW LEVEL SECURITY;
CREATE POLICY analysis_stages_workspace ON dmc.analysis_stages
    USING (workspace_id=current_setting('dmc.workspace_id',true))
    WITH CHECK (workspace_id=current_setting('dmc.workspace_id',true));
REVOKE ALL ON dmc.analysis_stages FROM PUBLIC;

-- These fixed, schema-qualified functions are the ONLY global capabilities
-- granted to a separate dispatcher login. The browser API role cannot execute
-- them. Neither a vector, PDF excerpt nor a case payload is returned.
CREATE FUNCTION dmc.dispatch_claim(p_worker text,p_pipeline text)
RETURNS TABLE(workspace_id text,job_id text,filename text,deadline timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE target record;
BEGIN
    IF p_worker !~ '^[0-9a-f]{32}$' OR p_pipeline !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Invalid dispatcher identity';
    END IF;
    PERFORM pg_advisory_xact_lock(728405618);
    IF (SELECT count(*) FROM dmc.analysis_jobs j
        WHERE j.state IN ('dispatching','uncertain','cancel_requested') AND j.deadline>now()) >= 2 THEN
        RETURN;
    END IF;
    SELECT j.* INTO target FROM dmc.analysis_jobs j
        WHERE j.state='accepted' AND j.attempts<3 AND j.pipeline_sha=p_pipeline
        ORDER BY j.created_at,j.job_id FOR UPDATE SKIP LOCKED LIMIT 1;
    IF NOT FOUND THEN RETURN; END IF;
    UPDATE dmc.analysis_jobs j SET state='dispatching',attempts=j.attempts+1,
        worker_id=p_worker,heartbeat_at=now(),updated_at=now(),
        deadline=now()+make_interval(secs=>j.budget_seconds),reason=''
        WHERE j.workspace_id=target.workspace_id AND j.job_id=target.job_id;
    INSERT INTO dmc.analysis_job_events(workspace_id,job_id,event,actor)
        VALUES(target.workspace_id,target.job_id,'claimed','dispatcher');
    RETURN QUERY SELECT j.workspace_id,j.job_id,j.filename,j.deadline FROM dmc.analysis_jobs j
        WHERE j.workspace_id=target.workspace_id AND j.job_id=target.job_id;
END $$;

CREATE FUNCTION dmc.dispatch_heartbeat(p_workspace text,p_job text,p_worker text)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    WITH touched AS (UPDATE dmc.analysis_jobs j SET heartbeat_at=now()
        WHERE j.workspace_id=p_workspace AND j.job_id=p_job AND j.worker_id=p_worker
          AND j.state IN ('dispatching','uncertain','cancel_requested') RETURNING 1)
    SELECT EXISTS(SELECT 1 FROM touched)
$$;

CREATE FUNCTION dmc.dispatch_observe()
RETURNS TABLE(workspace_id text,job_id text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    WITH targets AS (SELECT j.workspace_id,j.job_id FROM dmc.analysis_jobs j
        WHERE j.state IN ('accepted','dispatching','uncertain','cancel_requested')
        ORDER BY j.observed_at,j.job_id FOR UPDATE SKIP LOCKED LIMIT 25),
    touched AS (UPDATE dmc.analysis_jobs j SET observed_at=now() FROM targets t
        WHERE j.workspace_id=t.workspace_id AND j.job_id=t.job_id
        RETURNING j.workspace_id,j.job_id)
    SELECT t.workspace_id,t.job_id FROM touched t
$$;
REVOKE ALL ON FUNCTION dmc.dispatch_claim(text,text),
    dmc.dispatch_heartbeat(text,text,text),dmc.dispatch_observe() FROM PUBLIC;

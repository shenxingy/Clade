-- index idx_evidence_bundles_task_attempt
CREATE INDEX idx_evidence_bundles_task_attempt
                    ON evidence_bundles(task_id, attempt_index, revision);

-- table commits
CREATE TABLE commits (
                        id TEXT PRIMARY KEY,
                        task_id TEXT,
                        hash TEXT,
                        branch TEXT,
                        committed_at REAL,
                        pushed_at REAL,
                        merged_at REAL,
                        FOREIGN KEY (task_id) REFERENCES tasks(id)
                    );

-- table evidence_bundles
CREATE TABLE evidence_bundles (
                        attempt_id TEXT NOT NULL,
                        revision INTEGER NOT NULL CHECK (revision > 0),
                        bundle_id TEXT NOT NULL,
                        schema_version TEXT NOT NULL
                            CHECK (schema_version = 'clade.evidence/v1'),
                        task_id TEXT NOT NULL,
                        attempt_index INTEGER NOT NULL CHECK (attempt_index > 0),
                        lifecycle_state TEXT NOT NULL CHECK (
                            lifecycle_state IN (
                                'created', 'running', 'verifying',
                                'delivery_pending', 'delivered', 'failed',
                                'cancelled', 'reverted'
                            )
                        ),
                        recorded_at REAL NOT NULL CHECK (recorded_at >= 0),
                        evidence_json TEXT NOT NULL,
                        redaction_metadata TEXT NOT NULL,
                        previous_digest TEXT,
                        payload_digest TEXT NOT NULL,
                        PRIMARY KEY (attempt_id, revision),
                        UNIQUE (bundle_id, revision),
                        UNIQUE (task_id, attempt_index, revision),
                        FOREIGN KEY (task_id) REFERENCES tasks(id)
                    );

-- table idea_messages
CREATE TABLE idea_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        idea_id INTEGER NOT NULL REFERENCES ideas(id),
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT DEFAULT (datetime('now'))
                    );

-- table ideas
CREATE TABLE ideas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT NOT NULL,
                        status TEXT DEFAULT 'raw',
                        ai_evaluation TEXT,
                        priority INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'human',
                        project TEXT,
                        promoted_to TEXT,
                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now'))
                    );

-- table interventions
CREATE TABLE interventions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        failure_pattern TEXT NOT NULL,
                        correction TEXT NOT NULL,
                        task_description_hint TEXT,
                        success INTEGER DEFAULT 0,
                        source_task_id TEXT,
                        spawned_task_id TEXT,
                        created_at REAL,
                        redaction_metadata TEXT DEFAULT '{}'
                    );

-- table iteration_loops
CREATE TABLE iteration_loops (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL DEFAULT 'default',
                        artifact_path TEXT NOT NULL DEFAULT '',
                        context_dir TEXT,
                        status TEXT DEFAULT 'idle',
                        iteration INTEGER DEFAULT 0,
                        changes_history TEXT DEFAULT '[]',
                        deferred_items TEXT DEFAULT '[]',
                        convergence_k INTEGER DEFAULT 2,
                        convergence_n INTEGER DEFAULT 3,
                        max_iterations INTEGER DEFAULT 20,
                        supervisor_model TEXT DEFAULT 'sonnet',
                        created_at TEXT,
                        updated_at TEXT,
                        mode TEXT DEFAULT 'review',
                        plan_phase TEXT DEFAULT 'plan',
                        plan_item_reject_streak INTEGER DEFAULT 0
                    );

-- table schedule
CREATE TABLE schedule (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        scheduled_at TEXT,
                        triggered INTEGER DEFAULT 0
                    );

-- table tasks
CREATE TABLE tasks (
                        id TEXT PRIMARY KEY,
                        description TEXT NOT NULL,
                        model TEXT DEFAULT 'sonnet',
                        timeout INTEGER DEFAULT 600,
                        retries INTEGER DEFAULT 2,
                        status TEXT DEFAULT 'pending',
                        worker_id TEXT,
                        started_at REAL,
                        elapsed_s INTEGER DEFAULT 0,
                        last_commit TEXT,
                        log_file TEXT,
                        failed_reason TEXT,
                        redaction_metadata TEXT DEFAULT '{}',
                        created_at REAL,
                        depends_on TEXT DEFAULT '[]',
                        score INTEGER,
                        score_note TEXT,
                        own_files TEXT DEFAULT '[]',
                        forbidden_files TEXT DEFAULT '[]',
                        gh_issue_number INTEGER,
                        is_critical_path INTEGER DEFAULT 0
                    , input_tokens INTEGER, output_tokens INTEGER, estimated_cost REAL, task_type TEXT DEFAULT 'AUTO', source_ref TEXT, parent_task_id TEXT, priority_score REAL DEFAULT 0.0, handoff_type TEXT, handoff_payload TEXT DEFAULT '{}', completion_summary TEXT, token_budget INTEGER DEFAULT 0, context_version INTEGER DEFAULT 0, attempt_count INTEGER DEFAULT 0, phase TEXT DEFAULT 'implement', oracle_result TEXT, oracle_reason TEXT, pgid INTEGER, provider TEXT, agent_runtime TEXT, connection TEXT, execution_profile TEXT, execution_requirements TEXT DEFAULT '{}', execution_envelope TEXT, effort TEXT, route_reason TEXT);

-- table worker_messages
CREATE TABLE worker_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        to_task_id TEXT NOT NULL,
                        from_task_id TEXT,
                        content TEXT NOT NULL,
                        created_at REAL,
                        read INTEGER DEFAULT 0,
                        redaction_metadata TEXT DEFAULT '{}'
                    );

-- trigger evidence_bundles_insert_guard
CREATE TRIGGER evidence_bundles_insert_guard
                    BEFORE INSERT ON evidence_bundles
                    BEGIN
                        SELECT CASE
                            WHEN NEW.revision != COALESCE((
                                SELECT MAX(revision) + 1
                                FROM evidence_bundles
                                WHERE attempt_id = NEW.attempt_id
                            ), 1)
                            THEN RAISE(ABORT, 'evidence revision must append')
                        END;
                        SELECT CASE
                            WHEN EXISTS (
                                SELECT 1 FROM evidence_bundles
                                WHERE task_id = NEW.task_id
                                  AND attempt_index = NEW.attempt_index
                                  AND attempt_id != NEW.attempt_id
                            )
                            THEN RAISE(ABORT, 'evidence attempt identity changed')
                        END;
                        SELECT CASE
                            WHEN NEW.revision = 1 AND (
                                NEW.lifecycle_state != 'created'
                                OR NEW.previous_digest IS NOT NULL
                            )
                            THEN RAISE(ABORT, 'invalid initial evidence revision')
                        END;
                        SELECT CASE
                            WHEN NEW.revision > 1 AND NEW.previous_digest IS NOT (
                                SELECT payload_digest
                                FROM evidence_bundles
                                WHERE attempt_id = NEW.attempt_id
                                ORDER BY revision DESC LIMIT 1
                            )
                            THEN RAISE(ABORT, 'evidence predecessor mismatch')
                        END;
                    END;

-- trigger evidence_bundles_no_delete
CREATE TRIGGER evidence_bundles_no_delete
                    BEFORE DELETE ON evidence_bundles
                    BEGIN
                        SELECT RAISE(ABORT, 'evidence bundles are append-only');
                    END;

-- trigger evidence_bundles_no_update
CREATE TRIGGER evidence_bundles_no_update
                    BEFORE UPDATE ON evidence_bundles
                    BEGIN
                        SELECT RAISE(ABORT, 'evidence bundles are append-only');
                    END;

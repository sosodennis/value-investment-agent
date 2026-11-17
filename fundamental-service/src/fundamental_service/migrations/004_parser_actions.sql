CREATE TABLE IF NOT EXISTS fundamental.parser_action_results (
    action_key CHAR(64) PRIMARY KEY CHECK (action_key ~ '^[0-9a-f]{64}$'),
    artifact_id TEXT NOT NULL REFERENCES fundamental.artifact_references(artifact_id)
);

INSERT INTO fundamental.schema_capabilities(capability_id)
VALUES ('sec-parser-actions-v1')
ON CONFLICT (capability_id) DO NOTHING;

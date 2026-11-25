CREATE TABLE IF NOT EXISTS fundamental.fiscal_history_origin (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    origin_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    system_identifier TEXT NOT NULL,
    timeline_id BIGINT NOT NULL,
    database_oid OID NOT NULL
);

INSERT INTO fundamental.fiscal_history_origin(system_identifier, timeline_id, database_oid)
SELECT system_identifier::text, timeline_id, (SELECT oid FROM pg_database WHERE datname=current_database())
FROM pg_control_system(), pg_control_checkpoint()
ON CONFLICT (singleton) DO NOTHING;

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_origin_id()
RETURNS UUID LANGUAGE plpgsql SET search_path = pg_catalog, fundamental AS $function$
DECLARE
    identity UUID;
BEGIN
    SELECT origin_id INTO identity FROM fundamental.fiscal_history_origin origin,
        pg_control_system() system, pg_control_checkpoint() checkpoint
    WHERE origin.system_identifier = system.system_identifier::text
        AND origin.timeline_id = checkpoint.timeline_id
        AND origin.database_oid = (SELECT oid FROM pg_database WHERE datname=current_database())
        AND NOT pg_is_in_recovery();
    IF identity IS NULL THEN
        RAISE EXCEPTION 'fiscal history origin is unavailable' USING ERRCODE='55000';
    END IF;
    RETURN identity;
END;
$function$;

CREATE TABLE IF NOT EXISTS fundamental.fiscal_history_streams (
    stream_id TEXT PRIMARY KEY,
    stream_kind TEXT NOT NULL CHECK (stream_kind IN ('control', 'evidence')),
    subject_id TEXT NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    event_digest TEXT,
    recorded_at TIMESTAMPTZ,
    UNIQUE (stream_kind, subject_id),
    CHECK ((sequence = 0 AND event_digest IS NULL AND recorded_at IS NULL)
        OR (sequence > 0 AND event_digest ~ '^[0-9a-f]{64}$' AND recorded_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS fundamental.fiscal_history_events (
    stream_id TEXT NOT NULL REFERENCES fundamental.fiscal_history_streams(stream_id),
    sequence BIGINT NOT NULL CHECK (sequence > 0),
    event_digest TEXT NOT NULL CHECK (event_digest ~ '^[0-9a-f]{64}$'),
    payload_bytes BYTEA NOT NULL,
    command_digest TEXT CHECK (command_digest ~ '^[0-9a-f]{64}$'),
    origin_id UUID NOT NULL REFERENCES fundamental.fiscal_history_origin(origin_id),
    writer_xid8 XID8 NOT NULL,
    PRIMARY KEY (stream_id, sequence),
    UNIQUE (stream_id, command_digest)
);

CREATE INDEX IF NOT EXISTS fiscal_history_writer ON fundamental.fiscal_history_events(origin_id, writer_xid8);

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_event_writer_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, fundamental AS $function$
DECLARE
    payload JSONB := convert_from(NEW.payload_bytes, 'UTF8')::jsonb;
BEGIN
    IF current_setting('track_commit_timestamp') <> 'on'
        OR NEW.origin_id <> fundamental.fiscal_history_origin_id()
        OR NEW.writer_xid8 <> pg_current_xact_id()
        OR (payload->>'origin_id')::uuid IS DISTINCT FROM NEW.origin_id
        OR (payload->>'writer_xid8')::xid8 IS DISTINCT FROM NEW.writer_xid8
        OR payload->>'recorded_at' IS NULL
        OR (payload->>'recorded_at')::timestamptz < transaction_timestamp()
        OR (payload->>'recorded_at')::timestamptz > clock_timestamp() THEN
        RAISE EXCEPTION 'fiscal history writer must be the current database transaction' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE TRIGGER fiscal_history_event_writer_guard
BEFORE INSERT ON fundamental.fiscal_history_events
FOR EACH ROW EXECUTE FUNCTION fundamental.fiscal_history_event_writer_guard();

CREATE TABLE IF NOT EXISTS fundamental.fiscal_history_commit_receipts (
    origin_id UUID NOT NULL REFERENCES fundamental.fiscal_history_origin(origin_id),
    writer_xid8 XID8 NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL,
    visible_by TIMESTAMPTZ NOT NULL CHECK (visible_by >= committed_at),
    PRIMARY KEY (origin_id, writer_xid8)
);

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_commit_lower(origin UUID, writer XID8)
RETURNS JSONB LANGUAGE plpgsql SET search_path = pg_catalog, fundamental AS $function$
DECLARE
    horizon NUMERIC;
    writer_number NUMERIC := writer::text::numeric;
    committed TIMESTAMPTZ;
BEGIN
    IF origin <> fundamental.fiscal_history_origin_id() THEN
        RAISE EXCEPTION 'fiscal history origin differs' USING ERRCODE='55000';
    END IF;
    IF current_setting('track_commit_timestamp') <> 'on' THEN
        RETURN jsonb_build_object('kind', 'missing', 'reason', 'tracking_disabled');
    END IF;
    horizon := pg_snapshot_xmax(pg_current_snapshot())::text::numeric;
    IF writer_number < 3 OR horizon - writer_number <= 0
        OR horizon - writer_number >= 2147483648 THEN
        RETURN jsonb_build_object('kind', 'missing', 'reason', 'unsafe_xid');
    END IF;
    IF pg_xact_status(writer) IS DISTINCT FROM 'committed' THEN
        RETURN jsonb_build_object('kind', 'missing', 'reason', 'uncommitted');
    END IF;
    committed := pg_xact_commit_timestamp((mod(writer_number, 4294967296)::bigint::text)::xid);
    IF committed IS NULL THEN
        RETURN jsonb_build_object('kind', 'missing', 'reason', 'commit_log_missing');
    END IF;
    RETURN jsonb_build_object('kind', 'known', 'committed_at', committed);
EXCEPTION WHEN invalid_parameter_value THEN
    RETURN jsonb_build_object('kind', 'missing', 'reason', 'commit_log_missing');
END;
$function$;

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_receipt_derive()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, fundamental AS $function$
DECLARE
    lower_bound JSONB;
    latest_recorded TIMESTAMPTZ;
BEGIN
    IF NEW.committed_at IS NOT NULL OR NEW.visible_by IS NOT NULL THEN
        RAISE EXCEPTION 'receipt timestamps are derived by the metadata owner' USING ERRCODE='55000';
    END IF;
    SELECT max((convert_from(payload_bytes, 'UTF8')::jsonb->>'recorded_at')::timestamptz)
        INTO latest_recorded FROM fundamental.fiscal_history_events
        WHERE origin_id=NEW.origin_id AND writer_xid8=NEW.writer_xid8;
    IF latest_recorded IS NULL THEN
        RAISE EXCEPTION 'receipt requires a visible event' USING ERRCODE='55000';
    END IF;
    lower_bound := fundamental.fiscal_history_commit_lower(NEW.origin_id, NEW.writer_xid8);
    IF lower_bound->>'kind' <> 'known' THEN
        RAISE EXCEPTION 'receipt commit lower bound unavailable: %', lower_bound->>'reason' USING ERRCODE='55000';
    END IF;
    NEW.committed_at := (lower_bound->>'committed_at')::timestamptz;
    NEW.visible_by := clock_timestamp();
    IF NEW.committed_at < latest_recorded OR NEW.visible_by < NEW.committed_at THEN
        RAISE EXCEPTION 'receipt clock reversed' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE TRIGGER fiscal_history_receipt_derive
BEFORE INSERT ON fundamental.fiscal_history_commit_receipts
FOR EACH ROW EXECUTE FUNCTION fundamental.fiscal_history_receipt_derive();

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_seal(origin UUID, writer XID8)
RETURNS VOID LANGUAGE plpgsql SET search_path = pg_catalog, fundamental AS $function$
BEGIN
    IF origin <> fundamental.fiscal_history_origin_id() THEN
        RAISE EXCEPTION 'fiscal history origin differs' USING ERRCODE='55000';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('fiscal-receipt:' || origin::text || ':' || writer::text, 0));
    IF EXISTS (SELECT 1 FROM fundamental.fiscal_history_commit_receipts
        WHERE origin_id=origin AND writer_xid8=writer) THEN
        RETURN;
    END IF;
    INSERT INTO fundamental.fiscal_history_commit_receipts(origin_id, writer_xid8)
        VALUES (origin, writer);
END;
$function$;

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_immutable()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'fiscal history is append only';
END;
$function$;

CREATE OR REPLACE TRIGGER fiscal_history_events_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON fundamental.fiscal_history_events
FOR EACH STATEMENT EXECUTE FUNCTION fundamental.fiscal_history_immutable();

CREATE OR REPLACE TRIGGER fiscal_history_receipts_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON fundamental.fiscal_history_commit_receipts
FOR EACH STATEMENT EXECUTE FUNCTION fundamental.fiscal_history_immutable();

CREATE OR REPLACE TRIGGER fiscal_history_origin_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON fundamental.fiscal_history_origin
FOR EACH STATEMENT EXECUTE FUNCTION fundamental.fiscal_history_immutable();

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_head_guard()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF TG_OP = 'DELETE' OR NEW.stream_id <> OLD.stream_id
        OR NEW.stream_kind <> OLD.stream_kind OR NEW.subject_id <> OLD.subject_id
        OR NEW.sequence <> OLD.sequence + 1 OR NEW.recorded_at < OLD.recorded_at
        OR NOT EXISTS (
            SELECT 1 FROM fundamental.fiscal_history_events
            WHERE stream_id = NEW.stream_id AND sequence = NEW.sequence
                AND event_digest = NEW.event_digest
        ) THEN
        RAISE EXCEPTION 'fiscal history head transition is invalid';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE TRIGGER fiscal_history_head_guard
BEFORE UPDATE OR DELETE ON fundamental.fiscal_history_streams
FOR EACH ROW EXECUTE FUNCTION fundamental.fiscal_history_head_guard();

CREATE OR REPLACE TRIGGER fiscal_history_streams_no_truncate
BEFORE TRUNCATE ON fundamental.fiscal_history_streams
FOR EACH STATEMENT EXECUTE FUNCTION fundamental.fiscal_history_immutable();

CREATE OR REPLACE FUNCTION fundamental.fiscal_history_append(
    identity TEXT, history_kind TEXT, subject TEXT, body JSONB,
    command TEXT DEFAULT NULL
) RETURNS TEXT LANGUAGE plpgsql SET search_path = pg_catalog, fundamental AS $function$
DECLARE
    head fundamental.fiscal_history_streams%ROWTYPE;
    observed_at TIMESTAMPTZ;
    payload BYTEA;
    digest TEXT;
    origin UUID;
    writer XID8;
BEGIN
    IF current_setting('track_commit_timestamp') <> 'on' THEN
        RAISE EXCEPTION 'fiscal history requires track_commit_timestamp=on' USING ERRCODE='55000';
    END IF;
    origin := fundamental.fiscal_history_origin_id();
    writer := pg_current_xact_id();
    PERFORM pg_advisory_xact_lock(hashtextextended(identity, 0));
    INSERT INTO fundamental.fiscal_history_streams
        (stream_id, stream_kind, subject_id, sequence)
        VALUES (identity, history_kind, subject, 0)
        ON CONFLICT (stream_id) DO NOTHING;
    SELECT * INTO STRICT head FROM fundamental.fiscal_history_streams
        WHERE stream_id = identity FOR UPDATE;
    IF head.stream_kind <> history_kind OR head.subject_id <> subject THEN
        RAISE EXCEPTION 'fiscal history stream scope differs';
    END IF;
    observed_at := clock_timestamp();
    IF observed_at < head.recorded_at THEN
        RAISE EXCEPTION 'fiscal history clock reversed' USING ERRCODE='55000';
    END IF;
    payload := convert_to(jsonb_build_object(
        'protocol', 'fundamental.fiscal-history-event.v1',
        'hash_protocol', 'postgres-jsonb-text-sha256-v1',
        'stream_id', identity,
        'stream_kind', history_kind,
        'subject_id', subject,
        'sequence', head.sequence + 1,
        'previous_digest', head.event_digest,
        'origin_id', origin,
        'writer_xid8', writer::text::numeric,
        'recorded_at', to_char(observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'body', body
    )::text, 'UTF8');
    digest := encode(sha256(payload), 'hex');
    INSERT INTO fundamental.fiscal_history_events
        (stream_id, sequence, event_digest, payload_bytes, command_digest, origin_id, writer_xid8)
        VALUES (identity, head.sequence + 1, digest, payload, command, origin, writer);
    UPDATE fundamental.fiscal_history_streams
        SET sequence = head.sequence + 1, event_digest = digest, recorded_at = observed_at
        WHERE stream_id = identity;
    RETURN digest;
END;
$function$;

CREATE OR REPLACE FUNCTION fundamental.fiscal_artifact_record(record fundamental.artifact_references)
RETURNS JSONB LANGUAGE sql IMMUTABLE AS $function$
    SELECT jsonb_build_object(
        'artifact_id', record.artifact_id, 'content_hash', record.content_hash,
        'media_type', record.media_type, 'dependency_hashes', record.dependency_hashes,
        'status', record.status, 'retention', record.retention
    );
$function$;

CREATE OR REPLACE FUNCTION fundamental.fiscal_capture_artifact_transition()
RETURNS trigger LANGUAGE plpgsql AS $function$
DECLARE
    identity TEXT;
    old_record JSONB;
    new_record JSONB;
BEGIN
    IF TG_OP = 'INSERT' THEN
        identity := NEW.artifact_id;
    ELSE
        identity := OLD.artifact_id;
    END IF;
    IF EXISTS (SELECT 1 FROM fundamental.fiscal_history_streams
        WHERE stream_id = 'evidence:' || identity AND stream_kind = 'evidence') THEN
        IF TG_OP = 'UPDATE' AND NEW.artifact_id <> OLD.artifact_id THEN
            RAISE EXCEPTION 'registered evidence identity is immutable';
        END IF;
        old_record := CASE WHEN TG_OP = 'INSERT' THEN NULL
            ELSE fundamental.fiscal_artifact_record(OLD) END;
        new_record := CASE WHEN TG_OP = 'DELETE' THEN NULL
            ELSE fundamental.fiscal_artifact_record(NEW) END;
        IF old_record IS DISTINCT FROM new_record THEN
            PERFORM fundamental.fiscal_history_append(
                'evidence:' || identity, 'evidence', identity,
                jsonb_build_object('kind', 'evidence_changed',
                    'previous_record', old_record, 'record', new_record)
            );
        END IF;
    END IF;
    RETURN NULL;
END;
$function$;

CREATE OR REPLACE TRIGGER fiscal_capture_artifact_transition
AFTER INSERT OR UPDATE OR DELETE ON fundamental.artifact_references
FOR EACH ROW EXECUTE FUNCTION fundamental.fiscal_capture_artifact_transition();

CREATE OR REPLACE FUNCTION fundamental.fiscal_registered_artifacts_no_truncate()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF EXISTS (SELECT 1 FROM fundamental.fiscal_history_streams WHERE stream_kind = 'evidence') THEN
        RAISE EXCEPTION 'registered evidence cannot be truncated';
    END IF;
    RETURN NULL;
END;
$function$;

CREATE OR REPLACE TRIGGER fiscal_registered_artifacts_no_truncate
BEFORE TRUNCATE ON fundamental.artifact_references
FOR EACH STATEMENT EXECUTE FUNCTION fundamental.fiscal_registered_artifacts_no_truncate();

INSERT INTO fundamental.schema_capabilities(capability_id)
VALUES ('fiscal-admission-history-v1') ON CONFLICT DO NOTHING;

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .database import Base


class ChatMessage(Base):
    __tablename__ = "chat_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user', 'assistant', 'system', 'tool'
    content = Column(Text, nullable=False)
    message_type = Column(String)  # 'human', 'ai', 'tool'
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    metadata_ = Column(JSON, default={})
    agent_id = Column(String, nullable=True, index=True)

    # Compound index for efficient session retrieval with ordering
    __table_args__ = (
        Index("idx_thread_created", "thread_id", "created_at"),
        Index("idx_thread_agent_created", "thread_id", "agent_id", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "type": self.metadata_.get("type", "text") if self.metadata_ else "text",
            "data": self.metadata_.get("data") if self.metadata_ else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "agentId": (
                self.agent_id
                or (
                    self.metadata_.get("agentId") or self.metadata_.get("agent_id")
                    if self.metadata_
                    else None
                )
            ),
        }


class Artifact(Base):
    """
    Stores large JSON artifacts (e.g., news items, financial statements, price data).
    Supports reference-based state management to avoid duplicating large data in checkpoints.
    """

    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(
        String, nullable=True, index=True
    )  # Optional semantic key for debugging
    thread_id = Column(String, nullable=True, index=True)  # Optional thread association
    type = Column(String, nullable=False)  # e.g., "news_items", "financial_statements"
    data = Column(JSON, nullable=False)  # The actual artifact payload
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "thread_id": self.thread_id,
            "type": self.type,
            "data": self.data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TechnicalPredictionEvent(Base):
    __tablename__ = "technical_prediction_events"

    event_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_source = Column(String, nullable=False, index=True)
    event_time = Column(DateTime, nullable=False, index=True)
    ticker = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)
    horizon = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)
    raw_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    reliability_level = Column(String, nullable=True, index=True)
    logic_version = Column(String, nullable=False, index=True)
    feature_contract_version = Column(String, nullable=False)
    run_type = Column(String, nullable=False, index=True)
    full_report_artifact_id = Column(
        String,
        ForeignKey("artifacts.id"),
        nullable=False,
        index=True,
    )
    source_artifact_refs = Column(JSON, nullable=False, default={})
    context_payload = Column(JSON, nullable=False, default={})
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "idx_technical_prediction_events_lookup",
            "ticker",
            "timeframe",
            "horizon",
            "event_time",
        ),
    )


class TechnicalOutcomePath(Base):
    __tablename__ = "technical_outcome_paths"

    outcome_path_id = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id = Column(
        String,
        ForeignKey("technical_prediction_events.event_id"),
        nullable=False,
        index=True,
    )
    resolved_at = Column(DateTime, nullable=False, index=True)
    forward_return = Column(Float, nullable=True)
    mfe = Column(Float, nullable=True)
    mae = Column(Float, nullable=True)
    realized_volatility = Column(Float, nullable=True)
    labeling_method_version = Column(String, nullable=False)
    data_quality_flags = Column(JSON, nullable=False, default=[])
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "idx_technical_outcome_paths_event_resolved",
            "event_id",
            "resolved_at",
        ),
        UniqueConstraint(
            "event_id",
            "labeling_method_version",
            name="uq_technical_outcome_paths_event_labeling_method",
        ),
    )


class TechnicalApprovedLabelSnapshot(Base):
    __tablename__ = "technical_approved_label_snapshots"

    snapshot_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id = Column(
        String,
        ForeignKey("technical_prediction_events.event_id"),
        nullable=False,
        index=True,
    )
    agent_source = Column(String, nullable=False, index=True)
    label_family = Column(String, nullable=False, index=True)
    label_method_version = Column(String, nullable=False)
    approved_at = Column(DateTime, nullable=False, index=True)
    approved_by = Column(String, nullable=False)
    definition_hash = Column(String, nullable=False, index=True)
    labels_payload = Column(JSON, nullable=False, default={})
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index(
            "idx_technical_approved_labels_event_family",
            "event_id",
            "label_family",
            "approved_at",
        ),
    )


class WorkspaceRuntimeActivityEvent(Base):
    __tablename__ = "workspace_runtime_activity_events"

    event_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, nullable=False, index=True)
    seq_id = Column(Integer, nullable=False)
    run_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=False, index=True)
    node = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    status = Column(String, nullable=True)
    payload = Column(JSON, nullable=False, default={})
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "seq_id",
            name="uq_workspace_runtime_activity_thread_seq",
        ),
        Index(
            "idx_workspace_runtime_activity_thread_seq",
            "thread_id",
            "seq_id",
        ),
        Index(
            "idx_workspace_runtime_activity_thread_created",
            "thread_id",
            "created_at",
        ),
        Index(
            "idx_workspace_runtime_activity_thread_agent_created",
            "thread_id",
            "agent_id",
            "created_at",
        ),
    )


class WorkspaceRuntimeActivitySegment(Base):
    __tablename__ = "workspace_runtime_activity_segments"

    segment_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=False, index=True)
    node = Column(String, nullable=False)
    run_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True)
    last_seq_id = Column(Integer, nullable=False)

    __table_args__ = (
        Index(
            "idx_workspace_runtime_segment_thread_agent_updated",
            "thread_id",
            "agent_id",
            "updated_at",
        ),
        Index(
            "idx_workspace_runtime_segment_thread_agent_run_updated",
            "thread_id",
            "agent_id",
            "run_id",
            "updated_at",
        ),
    )


class WorkspaceRuntimeRunStatus(Base):
    __tablename__ = "workspace_runtime_run_statuses"

    thread_id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True)
    last_seq_id = Column(Integer, nullable=False)

    __table_args__ = (
        Index(
            "idx_workspace_runtime_run_status_updated",
            "status",
            "updated_at",
        ),
    )


class WorkspaceRuntimeCursor(Base):
    __tablename__ = "workspace_runtime_cursors"

    thread_id = Column(String, primary_key=True)
    last_seq_id = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

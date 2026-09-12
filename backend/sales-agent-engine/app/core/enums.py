"""Persisted state vocabularies (mirrored by CHECK constraints in schema ``agent``)."""

from __future__ import annotations

from enum import StrEnum


class SessionStatus(StrEnum):
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DONE = "DONE"
    FAILED = "FAILED"
    HALTED = "HALTED"


class PendingActionStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ToolOutcome(StrEnum):
    """How a gated tool call ended; recorded on every ``agent.audit`` row."""

    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"  # a write gave no answer (timeout, lost connection): it may have happened
    DENIED = "DENIED"  # unknown tool/agent, scope or ACL violation
    INVALID = "INVALID"  # arguments failed validation
    REJECTED = "REJECTED"  # human said no
    EXPIRED = "EXPIRED"  # approval TTL elapsed


class MemoryScope(StrEnum):
    """What a memory is about (implementation-plan §3.5). REP memory is private to its rep;
    ACCOUNT and DEAL memory are shared by the workspace; CONVERSATION belongs to one session."""

    CONVERSATION = "CONVERSATION"  # key: session id (the running summary of older turns)
    REP = "REP"  # key: the rep's user id
    DEAL = "DEAL"  # key: workspace-service deal id
    ACCOUNT = "ACCOUNT"  # key: normalized customer company name


class SagaStatus(StrEnum):
    PENDING = "PENDING"  # recorded before the side effect runs
    DONE = "DONE"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"

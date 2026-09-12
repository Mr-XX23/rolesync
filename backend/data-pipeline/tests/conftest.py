"""Shared pytest configuration for the data-pipeline suite.

Pins the RAG pipeline stores to their in-memory behaviour so unit tests stay
hermetic: they never touch (or pollute) the live Postgres RAG database, and
assertions about counts are not affected by rows left over from earlier runs.

Set RAG_PERSISTENCE=on explicitly to run these against a real database.
"""
import os

os.environ.setdefault("RAG_PERSISTENCE", "off")

# The gatekeeper's semantic scorer makes a live Gemini call per document. Unit
# tests stay offline and deterministic; set GATEKEEPER_SEMANTIC_ENABLED=true to
# exercise it against the real model.
os.environ.setdefault("GATEKEEPER_SEMANTIC_ENABLED", "false")

# The staging queue is Redis-backed in the service. Unit tests must not depend on
# (or write into) a live broker, so they run the in-process fallback; the Redis
# code path is covered by injecting a fake client in test_durable_queue.py.
os.environ.setdefault("INGEST_QUEUE_BACKEND", "memory")

"""Shared pytest configuration for the data-pipeline suite.

Pins the RAG pipeline stores to their in-memory behaviour so unit tests stay
hermetic: they never touch (or pollute) the live Postgres RAG database, and
assertions about counts are not affected by rows left over from earlier runs.

Set RAG_PERSISTENCE=on explicitly to run these against a real database.
"""
import os

os.environ.setdefault("RAG_PERSISTENCE", "off")

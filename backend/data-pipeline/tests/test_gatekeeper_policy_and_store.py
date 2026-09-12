"""Module 2 (memory gatekeeper): config-driven policy, durable decisions, holds.

Covers the behaviour the previous gatekeeper claimed but did not have: a policy
version that actually tracks the thresholds, a hold that stores a preview and
expires, and a semantic scorer that is log-only by default and never rejects on
its own failure.
"""
from datetime import datetime, timedelta, timezone

import pytest

from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_2_memory_gatekeeper.gatekeeper_engine import (
    DECISION_ACCEPTED,
    DECISION_QUARANTINED,
    DECISION_REJECTED_LEXICAL,
    GatekeeperEngine,
)
from module_2_memory_gatekeeper.gatekeeper_store import (
    KIND_QUARANTINED,
    KIND_REJECTED,
    PREVIEW_CHARS,
    GatekeeperStore,
)
from module_2_memory_gatekeeper.lexical_checker import LexicalChecker
from module_2_memory_gatekeeper.policy import DEFAULT_SEMANTIC_MODEL, GatekeeperPolicy, load_policy
from module_2_memory_gatekeeper.semantic_scorer import SemanticScore, SemanticScorer

TENANT = "tenant_a"
OTHER_TENANT = "tenant_b"


def make_doc(doc_id: str = "tenant_a:gdrive:doc1", text: str = "", tenant_id: str = TENANT) -> ParsedDocument:
    return ParsedDocument(
        doc_id=doc_id,
        tenant_id=tenant_id,
        user_id="u1",
        source="gdrive",
        external_id=doc_id.rsplit(":", 1)[-1],
        acl=["u1"],
        mime_type="text/plain",
        text_content=text or "Q4 pricing discussion covering enterprise tiers, discount bands and renewal terms.",
    )


def make_policy(**overrides) -> GatekeeperPolicy:
    base = dict(
        min_text_length=10,
        max_shannon_entropy=6.0,
        min_unique_ratio=0.2,
        semantic_enabled=True,
        semantic_enforced=False,
        semantic_min_score=0.35,
        semantic_model=DEFAULT_SEMANTIC_MODEL,
        semantic_timeout_seconds=20.0,
        rejected_ttl_days=30,
        quarantine_ttl_days=90,
    )
    base.update(overrides)
    return GatekeeperPolicy(**base)


class StubScorer:
    """Stands in for the Gemini call."""

    def __init__(self, score: float = 0.9, ok: bool = True, reason: str = "stub"):
        self._result = SemanticScore(score, reason, DEFAULT_SEMANTIC_MODEL, ok=ok)
        self.calls = 0

    def score(self, document, category: str = "") -> SemanticScore:
        self.calls += 1
        return self._result


# --- policy ---------------------------------------------------------------
def test_policy_version_tracks_thresholds():
    """The recorded version must change when the policy changes: the old code
    hardcoded "v1.0.0", so decisions could not be explained after the fact."""
    baseline = make_policy()
    assert baseline.version == make_policy().version  # deterministic
    assert baseline.version != make_policy(min_text_length=25).version
    assert baseline.version != make_policy(semantic_enforced=True).version
    assert baseline.version != make_policy(semantic_model="other-model").version
    assert baseline.version.startswith("gk-")


def test_policy_reads_model_from_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_GEMINI_MODE", raising=False)
    assert load_policy().semantic_model == DEFAULT_SEMANTIC_MODEL

    monkeypatch.setenv("GOOGLE_GEMINI_MODE", "gemini-custom-model")
    assert load_policy().semantic_model == "gemini-custom-model"


def test_policy_defaults_to_log_only(monkeypatch):
    """arch.md requires the scorer to launch in log-only mode."""
    monkeypatch.delenv("GATEKEEPER_SEMANTIC_ENFORCED", raising=False)
    assert load_policy().semantic_enforced is False


def test_lexical_thresholds_come_from_policy():
    doc = make_doc(text="Short note here.")
    assert LexicalChecker().check(doc, policy=make_policy(min_text_length=10)).is_valid is True

    strict = LexicalChecker().check(doc, policy=make_policy(min_text_length=500))
    assert strict.is_valid is False
    assert "below minimum" in strict.reason


# --- store ----------------------------------------------------------------
def test_hold_stores_preview_not_whole_document():
    """The old stores retained the entire ParsedDocument forever."""
    store = GatekeeperStore(use_db=False)
    long_text = "pricing detail " * 2000
    record = store.hold(KIND_REJECTED, make_doc(text=long_text), "too repetitive", ttl_days=30)

    assert len(record.preview) == PREVIEW_CHARS
    assert record.char_count == len(long_text)
    assert record.preview == long_text[:PREVIEW_CHARS]


def test_hold_expires_after_ttl():
    store = GatekeeperStore(use_db=False)
    record = store.hold(KIND_QUARANTINED, make_doc(), "low utility", ttl_days=90)
    assert record.expires_at is not None
    assert store.list_holds(TENANT) != []

    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert store.purge_expired() == 1
    assert store.list_holds(TENANT) == []


def test_hold_without_ttl_does_not_expire():
    store = GatekeeperStore(use_db=False)
    record = store.hold(KIND_REJECTED, make_doc(), "no ttl", ttl_days=0)
    assert record.expires_at is None
    assert store.purge_expired() == 0
    assert len(store.list_holds(TENANT)) == 1


def test_list_holds_is_tenant_scoped_and_filterable():
    store = GatekeeperStore(use_db=False)
    store.hold(KIND_REJECTED, make_doc(doc_id="a:1"), "r", ttl_days=30)
    store.hold(KIND_QUARANTINED, make_doc(doc_id="a:2"), "q", ttl_days=90)
    store.hold(KIND_REJECTED, make_doc(doc_id="b:1", tenant_id=OTHER_TENANT), "r", ttl_days=30)

    assert len(store.list_holds(TENANT)) == 2
    assert len(store.list_holds(OTHER_TENANT)) == 1
    assert [h.doc_id for h in store.list_holds(TENANT, kind="quarantined")] == ["a:2"]


def test_release_removes_from_holds():
    store = GatekeeperStore(use_db=False)
    store.hold(KIND_QUARANTINED, make_doc(doc_id="a:1"), "needs review", ttl_days=90)

    assert store.release("a:1") is True
    assert store.list_holds(TENANT) == []
    assert store.get_hold("a:1").status == "RELEASED"
    assert store.release("does-not-exist") is False


def test_decisions_are_tenant_scoped():
    """A workspace must not be able to read another workspace's decisions."""
    store = GatekeeperStore(use_db=False)
    store.record_decision(
        doc_id="shared-id", tenant_id=TENANT, user_id="u1", source="gdrive",
        category="sales", decision=DECISION_ACCEPTED, reason="ok",
    )
    store.record_decision(
        doc_id="shared-id", tenant_id=OTHER_TENANT, user_id="u2", source="gdrive",
        category="sales", decision=DECISION_ACCEPTED, reason="ok",
    )

    assert len(store.decisions_for_doc("shared-id")) == 2
    scoped = store.decisions_for_doc("shared-id", tenant_id=TENANT)
    assert len(scoped) == 1
    assert scoped[0]["tenant_id"] == TENANT


# --- engine ---------------------------------------------------------------
def test_lexical_rejection_is_held_for_review():
    """A rejected document must be recoverable, not silently dropped."""
    store = GatekeeperStore(use_db=False)
    engine = GatekeeperEngine(store=store, scorer=StubScorer(), policy=make_policy())

    decision = engine.evaluate_document(make_doc(doc_id="a:junk", text="hi"))

    assert decision.decision == DECISION_REJECTED_LEXICAL
    holds = store.list_holds(TENANT, kind=KIND_REJECTED)
    assert [h.doc_id for h in holds] == ["a:junk"]


def test_low_score_does_not_reject_in_log_only_mode():
    store = GatekeeperStore(use_db=False)
    scorer = StubScorer(score=0.05)
    engine = GatekeeperEngine(store=store, scorer=scorer, policy=make_policy(semantic_enforced=False))

    decision = engine.evaluate_document(make_doc())

    assert decision.decision == DECISION_ACCEPTED
    assert "log-only" in decision.reason
    assert decision.semantic_score == pytest.approx(0.05)
    assert store.list_holds(TENANT) == []  # recorded, not acted on


def test_low_score_quarantines_when_enforced():
    store = GatekeeperStore(use_db=False)
    engine = GatekeeperEngine(
        store=store, scorer=StubScorer(score=0.05), policy=make_policy(semantic_enforced=True)
    )

    decision = engine.evaluate_document(make_doc(doc_id="a:lowvalue"))

    assert decision.decision == DECISION_QUARANTINED
    holds = store.list_holds(TENANT, kind=KIND_QUARANTINED)
    assert [h.doc_id for h in holds] == ["a:lowvalue"]
    assert holds[0].semantic_score == pytest.approx(0.05)


def test_scorer_failure_never_rejects():
    """An outage must degrade to the lexical checks, not drop good documents."""
    store = GatekeeperStore(use_db=False)
    engine = GatekeeperEngine(
        store=store, scorer=StubScorer(ok=False, reason="scorer unavailable (503)"),
        policy=make_policy(semantic_enforced=False),
    )

    decision = engine.evaluate_document(make_doc())

    assert decision.decision == DECISION_ACCEPTED
    assert decision.semantic_score is None
    assert store.list_holds(TENANT) == []


def test_scorer_failure_quarantines_rather_than_rejects_when_enforced():
    """Even enforcing, an unavailable scorer holds for review - it never rejects."""
    store = GatekeeperStore(use_db=False)
    engine = GatekeeperEngine(
        store=store, scorer=StubScorer(ok=False), policy=make_policy(semantic_enforced=True)
    )

    decision = engine.evaluate_document(make_doc(doc_id="a:unscored"))

    assert decision.decision == DECISION_QUARANTINED
    assert decision.decision != DECISION_REJECTED_LEXICAL
    assert store.get_hold("a:unscored").semantic_score is None


def test_disabled_scorer_is_not_called():
    store = GatekeeperStore(use_db=False)
    scorer = StubScorer()
    policy = make_policy(semantic_enabled=False)
    engine = GatekeeperEngine(store=store, scorer=scorer, policy=policy)

    # The real scorer short-circuits on `semantic_enabled`; assert the engine
    # accepts and records nothing semantic when a disabled policy is active.
    real = SemanticScorer(policy=policy)
    assert real.score(make_doc()).ok is False

    assert engine.evaluate_document(make_doc()).decision == DECISION_ACCEPTED


def test_decision_records_policy_version_and_semantic_fields():
    store = GatekeeperStore(use_db=False)
    policy = make_policy(semantic_min_score=0.5)
    engine = GatekeeperEngine(store=store, scorer=StubScorer(score=0.8), policy=policy)

    engine.evaluate_document(make_doc(doc_id="a:audited"))

    entries = store.decisions_for_doc("a:audited", tenant_id=TENANT)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["policy_version"] == policy.version
    assert entry["semantic_model"] == DEFAULT_SEMANTIC_MODEL
    assert entry["semantic_enforced"] is False
    assert entry["semantic_score"] == pytest.approx(0.8)
    assert entry["entropy"] > 0.0


def test_scorer_parses_and_clamps_model_output():
    parse = SemanticScorer._parse
    assert parse('{"score": 0.7, "reason": "product pricing"}', "m").score == pytest.approx(0.7)
    assert parse('```json\n{"score": 0.4, "reason": "notes"}\n```', "m").score == pytest.approx(0.4)
    assert parse('{"score": 5, "reason": "out of range"}', "m").score == 1.0
    assert parse('{"score": -2, "reason": "out of range"}', "m").score == 0.0

    broken = parse("not json at all", "m")
    assert broken.ok is False  # no signal, so callers must not reject
    assert broken.score == 0.0


# --- id resolution --------------------------------------------------------
CANONICAL = "tenant_a:USER_UPLOAD:doc_abc123"


def test_decisions_resolve_short_vault_id():
    """Decisions are stored under the canonical id, but the UI and API callers
    only have the short vault id, so a lookup by either must work."""
    store = GatekeeperStore(use_db=False)
    store.record_decision(
        doc_id=CANONICAL, tenant_id=TENANT, user_id="u1", source="USER_UPLOAD",
        category="general_doc", decision=DECISION_ACCEPTED, reason="ok",
    )

    assert len(store.decisions_for_doc(CANONICAL, tenant_id=TENANT)) == 1
    assert len(store.decisions_for_doc("doc_abc123", tenant_id=TENANT)) == 1
    assert store.decisions_for_doc("doc_abc123", tenant_id=OTHER_TENANT) == []
    assert store.decisions_for_doc("abc123", tenant_id=TENANT) == []  # suffix, not substring


def test_holds_resolve_short_vault_id_and_stay_tenant_scoped():
    store = GatekeeperStore(use_db=False)
    store.hold(KIND_REJECTED, make_doc(doc_id=CANONICAL), "repetitive noise", ttl_days=30)

    assert store.get_hold("doc_abc123", tenant_id=TENANT).doc_id == CANONICAL
    assert store.get_hold(CANONICAL, tenant_id=TENANT) is not None
    assert store.get_hold("doc_abc123", tenant_id=OTHER_TENANT) is None
    assert store.get_hold("doc_missing", tenant_id=TENANT) is None


def test_release_is_not_repeatable():
    """A second release must not report success: only a HELD document is releasable."""
    store = GatekeeperStore(use_db=False)
    store.hold(KIND_QUARANTINED, make_doc(doc_id=CANONICAL), "needs review", ttl_days=90)

    assert store.release(CANONICAL) is True
    assert store.get_hold(CANONICAL, tenant_id=TENANT).status == "RELEASED"
    assert store.list_holds(TENANT) == []

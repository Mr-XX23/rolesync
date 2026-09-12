"""Memory gatekeeper: decides what is allowed into the knowledge base.

Pipeline: category routing -> lexical/entropy checks -> semantic utility scoring.
Every decision is recorded with the policy version that produced it, and anything
kept out is held (with a TTL) so it can be reviewed and replayed rather than
silently discarded.

The semantic scorer runs in LOG-ONLY mode by default, as arch.md specifies: its
score is recorded but does not change the outcome until
GATEKEEPER_SEMANTIC_ENFORCED is turned on. A scorer failure never rejects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_2_memory_gatekeeper.category_router import CategoryRouter, DocumentCategory
from module_2_memory_gatekeeper.gatekeeper_store import (
    KIND_QUARANTINED,
    KIND_REJECTED,
    GatekeeperStore,
    gatekeeper_store,
)
from module_2_memory_gatekeeper.lexical_checker import LexicalChecker, LexicalResult
from module_2_memory_gatekeeper.policy import GatekeeperPolicy, load_policy
from module_2_memory_gatekeeper.semantic_scorer import SemanticScorer, semantic_scorer

DECISION_ACCEPTED = "ACCEPTED"
DECISION_REJECTED_LEXICAL = "REJECTED_LEXICAL"
DECISION_QUARANTINED = "QUARANTINED"


@dataclass
class GatekeeperDecision:
    doc_id: str
    category: DocumentCategory
    decision: str  # ACCEPTED, REJECTED_LEXICAL, QUARANTINED
    reason: str
    document: ParsedDocument
    semantic_score: Optional[float] = None
    policy_version: str = ""


class GatekeeperEngine:
    """Facade managing category routing, filtering, scoring and auditing."""

    def __init__(
        self,
        router: CategoryRouter | None = None,
        lexical_checker: LexicalChecker | None = None,
        store: GatekeeperStore | None = None,
        scorer: SemanticScorer | None = None,
        policy: GatekeeperPolicy | None = None,
    ) -> None:
        self.router = router or CategoryRouter()
        self.lexical_checker = lexical_checker or LexicalChecker()
        self.store = store or gatekeeper_store
        self.scorer = scorer or semantic_scorer
        self._policy = policy

    @property
    def policy(self) -> GatekeeperPolicy:
        return self._policy or load_policy()

    def evaluate_document(self, document: ParsedDocument) -> GatekeeperDecision:
        policy = self.policy
        category = self.router.route_document(document)
        lexical: LexicalResult = self.lexical_checker.check(document, policy=policy)

        if not lexical.is_valid:
            return self._finalize(
                document, category, DECISION_REJECTED_LEXICAL, lexical.reason, lexical, policy,
                hold_kind=KIND_REJECTED, ttl_days=policy.rejected_ttl_days,
            )

        # Semantic utility scoring. `ok=False` means no usable signal, so it must
        # not by itself reject anything.
        score = self.scorer.score(document, category=category.value)
        below_threshold = score.ok and score.score < policy.semantic_min_score

        if policy.semantic_enforced and (below_threshold or (policy.semantic_enabled and not score.ok)):
            reason = (
                f"Semantic utility {round(score.score, 2)} below {policy.semantic_min_score}: {score.reason}"
                if below_threshold
                else f"Semantic scoring unavailable ({score.reason}); held for review"
            )
            return self._finalize(
                document, category, DECISION_QUARANTINED, reason, lexical, policy,
                hold_kind=KIND_QUARANTINED, ttl_days=policy.quarantine_ttl_days,
                score=score.score if score.ok else None, model=score.model,
            )

        if below_threshold:
            # Log-only: recorded, deliberately not acted on.
            reason = (
                f"Passed all gatekeeper checks (log-only: semantic utility "
                f"{round(score.score, 2)} below {policy.semantic_min_score})"
            )
        else:
            reason = "Passed all gatekeeper checks"

        return self._finalize(
            document, category, DECISION_ACCEPTED, reason, lexical, policy,
            score=score.score if score.ok else None, model=score.model,
        )

    # ---- internals -------------------------------------------------------
    def _finalize(
        self,
        document: ParsedDocument,
        category: DocumentCategory,
        decision: str,
        reason: str,
        lexical: LexicalResult,
        policy: GatekeeperPolicy,
        hold_kind: str = "",
        ttl_days: int = 0,
        score: Optional[float] = None,
        model: str = "",
    ) -> GatekeeperDecision:
        if hold_kind:
            self.store.hold(
                kind=hold_kind,
                document=document,
                reason=reason,
                ttl_days=ttl_days,
                category=category.value,
                semantic_score=score,
            )

        self.store.record_decision(
            doc_id=document.doc_id,
            tenant_id=document.tenant_id,
            user_id=document.user_id,
            source=document.source,
            category=category.value,
            decision=decision,
            reason=reason,
            entropy=lexical.entropy,
            unique_ratio=lexical.unique_ratio,
            semantic_score=score,
            semantic_model=model,
            semantic_enforced=policy.semantic_enforced,
            policy_version=policy.version,
        )

        return GatekeeperDecision(
            doc_id=document.doc_id,
            category=category,
            decision=decision,
            reason=reason,
            document=document,
            semantic_score=score,
            policy_version=policy.version,
        )

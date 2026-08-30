from dataclasses import dataclass
from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_2_memory_gatekeeper.category_router import CategoryRouter, DocumentCategory
from module_2_memory_gatekeeper.lexical_checker import LexicalChecker, LexicalResult
from module_2_memory_gatekeeper.audit_logger import GatekeeperAuditLogger
from module_2_memory_gatekeeper.rejected_store import RejectedStore
from module_2_memory_gatekeeper.quarantine_queue import QuarantineQueue

@dataclass
class GatekeeperDecision:
    doc_id: str
    category: DocumentCategory
    decision: str  # ACCEPTED, REJECTED_LEXICAL, QUARANTINED
    reason: str
    document: ParsedDocument

class GatekeeperEngine:
    """Facade Engine managing memory gatekeeping, filtering, category routing, and auditing."""

    def __init__(
        self,
        router: CategoryRouter | None = None,
        lexical_checker: LexicalChecker | None = None,
        audit_logger: GatekeeperAuditLogger | None = None,
        rejected_store: RejectedStore | None = None,
        quarantine_queue: QuarantineQueue | None = None,
    ) -> None:
        self.router = router or CategoryRouter()
        self.lexical_checker = lexical_checker or LexicalChecker()
        self.audit_logger = audit_logger or GatekeeperAuditLogger()
        self.rejected_store = rejected_store or RejectedStore()
        self.quarantine_queue = quarantine_queue or QuarantineQueue()

    def evaluate_document(self, document: ParsedDocument) -> GatekeeperDecision:
        # 1. Category Routing
        category = self.router.route_document(document)

        # 2. Lexical & Entropy Check
        lexical_res: LexicalResult = self.lexical_checker.check(document)

        if not lexical_res.is_valid:
            # Rejection branch
            decision_str = "REJECTED_LEXICAL"
            self.rejected_store.store_rejection(document, lexical_res.reason)
            self.audit_logger.log_decision(
                doc_id=document.doc_id,
                tenant_id=document.tenant_id,
                user_id=document.user_id,
                source=document.source,
                category=category.value,
                decision=decision_str,
                reason=lexical_res.reason,
                entropy=lexical_res.entropy,
            )
            return GatekeeperDecision(
                doc_id=document.doc_id,
                category=category,
                decision=decision_str,
                reason=lexical_res.reason,
                document=document,
            )

        # 3. Acceptance branch
        decision_str = "ACCEPTED"
        self.audit_logger.log_decision(
            doc_id=document.doc_id,
            tenant_id=document.tenant_id,
            user_id=document.user_id,
            source=document.source,
            category=category.value,
            decision=decision_str,
            reason="Passed all gatekeeper checks",
            entropy=lexical_res.entropy,
        )

        return GatekeeperDecision(
            doc_id=document.doc_id,
            category=category,
            decision=decision_str,
            reason="Passed all gatekeeper checks",
            document=document,
        )

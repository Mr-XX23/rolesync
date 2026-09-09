import unittest
from module_1_document_processing.classification.sales_classifier import (
    SalesClassifier,
    VALID_SALES_CATEGORIES,
)
from module_1_document_processing.knowledge_vault_routes import (
    _save_doc_record,
    _find_doc_record,
    _list_doc_records,
    list_documents,
    get_vault_stats,
    update_sales_classification,
    UpdateClassificationRequest,
)

class TestSalesTaxonomyAndClassification(unittest.TestCase):
    def setUp(self):
        self.classifier = SalesClassifier()

    def test_heuristic_battlecard_classification(self):
        res = self.classifier.classify(
            filename="Salesforce_vs_RoleSync_Battlecard.pdf",
            text_content="Why we win against Salesforce. Key differentiators and rebuttal scripts.",
        )
        self.assertEqual(res.category, "BATTLECARD")
        self.assertEqual(res.target_competitor, "Salesforce")
        self.assertIn("vs Salesforce", res.sales_tags)

    def test_heuristic_pricing_classification(self):
        res = self.classifier.classify(
            filename="Enterprise_Pricing_Rate_Card.xlsx",
            text_content="Annual subscription per user per month. Starter tier: $15, Enterprise tier: $45. Maximum discount 15%.",
        )
        self.assertEqual(res.category, "PRICING_PACKAGING")
        self.assertIn("Pricing", res.sales_tags)

    def test_heuristic_security_compliance_classification(self):
        res = self.classifier.classify(
            filename="RoleSync_SOC2_Type_II_Report.pdf",
            text_content="This independent audit attests to SOC 2 Type II, ISO 27001, and GDPR compliance standards.",
        )
        self.assertEqual(res.category, "SECURITY_COMPLIANCE")
        self.assertIn("GDPR", res.sales_tags)

    def test_user_category_override(self):
        res = self.classifier.classify(
            filename="general_notes.txt",
            text_content="some notes",
            user_override_category="PRICING_PACKAGING",
            user_override_competitor="HubSpot",
        )
        self.assertEqual(res.category, "PRICING_PACKAGING")
        self.assertEqual(res.target_competitor, "HubSpot")
        self.assertEqual(res.confidence_score, 1.0)

    def test_route_category_filtering_and_stats(self):
        tenant = "tenant_test_sales"
        user = "usr_sales_rep"

        # Create two test documents
        doc1 = {
            "doc_id": "doc_test_battlecard_1",
            "name": "Zendesk_Battlecard.pdf",
            "type": "PDF",
            "size_bytes": 1024,
            "chunks": 4,
            "status": "Indexed",
            "category": "BATTLECARD",
            "target_competitor": "Zendesk",
            "sales_summary": "Rebuttal against Zendesk",
            "sales_tags": ["vs Zendesk"],
            "created_at": "2026-09-08T10:00:00Z",
            "last_updated": "2026-09-08T10:00:00Z",
            "tenant_id": tenant,
            "user_id": user,
            "source": "USER_UPLOAD",
        }
        doc2 = {
            "doc_id": "doc_test_pricing_1",
            "name": "Q3_Rate_Card.pdf",
            "type": "PDF",
            "size_bytes": 2048,
            "chunks": 2,
            "status": "Indexed",
            "category": "PRICING_PACKAGING",
            "target_competitor": None,
            "sales_summary": "Q3 pricing guide",
            "sales_tags": ["Pricing"],
            "created_at": "2026-09-08T10:00:00Z",
            "last_updated": "2026-09-08T10:00:00Z",
            "tenant_id": tenant,
            "user_id": user,
            "source": "USER_UPLOAD",
        }
        _save_doc_record(doc1)
        _save_doc_record(doc2)

        # 1. Filter by category
        res_bc = list_documents(user_id=user, category="BATTLECARD", x_tenant_id=tenant)
        self.assertEqual(res_bc["count"], 1)
        self.assertEqual(res_bc["documents"][0]["doc_id"], "doc_test_battlecard_1")

        # 2. Check stats category counts
        stats = get_vault_stats(user_id=user, x_tenant_id=tenant)["stats"]
        self.assertIn("category_counts", stats)
        self.assertEqual(stats["category_counts"]["BATTLECARD"], 1)
        self.assertEqual(stats["category_counts"]["PRICING_PACKAGING"], 1)

        # 3. Manual override endpoint
        req = UpdateClassificationRequest(
            category="CASE_STUDY_ROI",
            target_competitor="HubSpot",
            sales_summary="Updated customer proof points",
        )
        update_res = update_sales_classification(doc_id="doc_test_battlecard_1", req=req, x_tenant_id=tenant)
        self.assertEqual(update_res["status"], "success")
        updated_doc = _find_doc_record("doc_test_battlecard_1")
        self.assertEqual(updated_doc["category"], "CASE_STUDY_ROI")
        self.assertEqual(updated_doc["target_competitor"], "HubSpot")

if __name__ == "__main__":
    unittest.main()

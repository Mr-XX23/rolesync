import os
import json
import re
from typing import Any, Optional
from pydantic import BaseModel, Field

# Supported Sales Taxonomy Categories
VALID_SALES_CATEGORIES = {
    "BATTLECARD",
    "PRICING_PACKAGING",
    "CASE_STUDY_ROI",
    "SECURITY_COMPLIANCE",
    "PRODUCT_SPEC",
    "CONTRACT_LEGAL",
    "GENERAL_RESOURCE",
}

class SalesClassificationResult(BaseModel):
    category: str = "GENERAL_RESOURCE"
    target_competitor: Optional[str] = None
    target_industry: Optional[str] = None
    sales_summary: str = ""
    sales_tags: list[str] = Field(default_factory=list)
    confidence_score: float = 0.5
    classifier_used: str = "heuristic_rule_engine"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "target_competitor": self.target_competitor,
            "target_industry": self.target_industry,
            "sales_summary": self.sales_summary,
            "sales_tags": self.sales_tags,
            "confidence_score": self.confidence_score,
            "classifier_used": self.classifier_used,
        }


class SalesClassifier:
    """
    Intelligent Sales Document Classifier for the RoleSync Knowledge Vault.
    Uses OpenRouter API (supporting free models e.g. Llama-3.3-70B, Gemini-2.0-Flash)
    with an immediate, resilient heuristic rule engine fallback.
    """

    KNOWN_COMPETITORS = [
        "Salesforce", "HubSpot", "Zendesk", "ServiceNow", "Workday",
        "Jira", "Asana", "Monday.com", "ClickUp", "Notion",
        "Slack", "Microsoft Teams", "Zoom", "Gong", "Chorus",
        "Outreach", "SalesLoft", "Apollo", "ZoomInfo", "Stripe",
        "Snowflake", "Datadog", "Dynatrace", "Splunk", "AWS", "Google Cloud"
    ]

    KNOWN_INDUSTRIES = [
        "Healthcare", "Fintech", "Financial Services", "Banking", "Insurance",
        "E-commerce", "Retail", "Enterprise SaaS", "Cybersecurity", "Manufacturing",
        "Logistics & Supply Chain", "Education / EdTech", "Real Estate", "Media & Entertainment",
        "Government / Public Sector", "Telecommunications"
    ]

    def __init__(self) -> None:
        self.api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPEN_ROUTER_API")
            or os.environ.get("OPENROUTER_API")
            or ""
        ).strip()
        self.model_name = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it:free").strip()
        self.site_url = os.environ.get("OPENROUTER_SITE_URL", "https://rolesync.ai")
        self.site_name = os.environ.get("OPENROUTER_SITE_NAME", "RoleSync Enterprise AI")

    def classify(
        self,
        filename: str,
        mime_type: str = "text/plain",
        text_content: str = "",
        user_override_category: Optional[str] = None,
        user_override_competitor: Optional[str] = None,
    ) -> SalesClassificationResult:
        """
        Classifies the document into a sales taxonomy category and extracts sales intelligence.
        Applies user overrides if provided.
        """
        # If user explicitly specified category, honor it as highest priority
        if user_override_category and user_override_category.upper() in VALID_SALES_CATEGORIES:
            result = self._classify_with_ai_or_heuristic(filename, mime_type, text_content)
            result.category = user_override_category.upper()
            if user_override_competitor:
                result.target_competitor = user_override_competitor
            result.confidence_score = 1.0
            return result

        # Run AI classification if API key is present, otherwise fallback to heuristics
        result = self._classify_with_ai_or_heuristic(filename, mime_type, text_content)
        if user_override_competitor:
            result.target_competitor = user_override_competitor
        return result

    def _classify_with_ai_or_heuristic(
        self,
        filename: str,
        mime_type: str,
        text_content: str,
    ) -> SalesClassificationResult:
        # Check if OpenRouter key is available
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPEN_ROUTER_API")
            or os.environ.get("OPENROUTER_API")
            or self.api_key
        ).strip()

        if api_key:
            try:
                ai_result = self._call_openrouter_classifier(api_key, filename, mime_type, text_content)
                if ai_result:
                    return ai_result
            except Exception as err:
                print(f"[SalesClassifier] OpenRouter classification failed ({err}). Running heuristic rule fallback.")

        # Fallback to local heuristic rule engine
        return self._heuristic_classification(filename, text_content)

    def _call_openrouter_classifier(
        self,
        api_key: str,
        filename: str,
        mime_type: str,
        text_content: str,
    ) -> Optional[SalesClassificationResult]:
        import requests

        # Extract snippet of up to 3500 chars for classification efficiency
        snippet = (text_content or "").strip()[:3500]
        if not snippet and not filename:
            return None

        system_prompt = (
            "You are an expert Enterprise Sales Intelligence Specialist and Sales Knowledge Librarian. "
            "Analyze the provided business document title and content excerpt, and classify it into exactly ONE sales category.\n\n"
            "Categories available:\n"
            "- BATTLECARD: Competitor comparison, objection handling, win/loss strategies, competitor weaknesses/strengths.\n"
            "- PRICING_PACKAGING: Rate cards, discounting rules, tier packaging, quotes, licensing fees, seat costs.\n"
            "- CASE_STUDY_ROI: Customer success metrics, client logos, case studies, quantified ROI proof, testimonials.\n"
            "- SECURITY_COMPLIANCE: SOC2, ISO27001, GDPR, HIPAA, compliance whitepapers, security architecture, data privacy.\n"
            "- PRODUCT_SPEC: Technical specs, API docs, system architecture, feature deep-dives, developer guides.\n"
            "- CONTRACT_LEGAL: MSAs, SLAs, DPAs, order forms, terms of service, indemnification, liability.\n"
            "- GENERAL_RESOURCE: General company material or miscellaneous not fitting the above categories.\n\n"
            "Respond ONLY with a valid JSON object in this exact schema without any markdown wrapping:\n"
            "{\n"
            '  "category": "BATTLECARD" | "PRICING_PACKAGING" | "CASE_STUDY_ROI" | "SECURITY_COMPLIANCE" | "PRODUCT_SPEC" | "CONTRACT_LEGAL" | "GENERAL_RESOURCE",\n'
            '  "target_competitor": "Name of competitor if relevant or null",\n'
            '  "target_industry": "Industry like Fintech, Healthcare, Enterprise SaaS or null",\n'
            '  "sales_summary": "Concise 1-2 sentence executive summary of what this document gives to a sales rep",\n'
            '  "sales_tags": ["tag1", "tag2", "tag3"],\n'
            '  "confidence_score": 0.95\n'
            "}"
        )

        user_content = (
            f"Filename: {filename}\n"
            f"MIME Type: {mime_type}\n"
            f"Content Excerpt:\n{snippet}"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
            "Content-Type": "application/json",
        }

        candidate_models = [
            self.model_name,
            "nvidia/nemotron-3.5-lightning:free",
            "google/gemma-4-26b-a4b-it:free",
            "liquid/lfm-2.5-2.6b:free",
        ]
        # De-duplicate while preserving order
        unique_models = []
        for m in candidate_models:
            if m and m not in unique_models:
                unique_models.append(m)

        for model in unique_models:
            try:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 400,
                }

                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=8,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    msg = choices[0].get("message", {})
                    raw_text = msg.get("content") or ""
                    if not raw_text.strip():
                        continue

                    # Strip <think>...</think> if present (DeepSeek / Nemotron reasoning)
                    raw_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

                    # Extract JSON block
                    json_match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
                    if not json_match:
                        continue
                    clean_json = json_match.group(0).strip()

                    parsed = json.loads(clean_json)
                    cat = str(parsed.get("category", "GENERAL_RESOURCE")).upper().strip()
                    if cat not in VALID_SALES_CATEGORIES:
                        cat = "GENERAL_RESOURCE"

                    competitor = parsed.get("target_competitor")
                    if competitor and str(competitor).lower() in ("null", "none", ""):
                        competitor = None

                    industry = parsed.get("target_industry")
                    if industry and str(industry).lower() in ("null", "none", ""):
                        industry = None

                    summary = str(parsed.get("sales_summary", "")).strip()
                    raw_tags = parsed.get("sales_tags", [])
                    tags = [str(t).strip() for t in raw_tags if str(t).strip()][:6]

                    confidence = float(parsed.get("confidence_score", 0.9))

                    return SalesClassificationResult(
                        category=cat,
                        target_competitor=competitor,
                        target_industry=industry,
                        sales_summary=summary or f"Sales resource: {filename}",
                        sales_tags=tags,
                        confidence_score=confidence,
                        classifier_used=f"openrouter:{model}",
                    )
                else:
                    print(f"[SalesClassifier] Model '{model}' returned status {resp.status_code} ({resp.text[:120]}), trying next candidate...")
            except Exception as e:
                print(f"[SalesClassifier] Exception with model '{model}': {e}")
                continue

        return None

    def _heuristic_classification(self, filename: str, text_content: str) -> SalesClassificationResult:
        """
        Fast, deterministic heuristic rule engine using keyword patterns, filename analysis,
        and known competitor / industry entity matching.
        """
        lower_fn = filename.lower()
        lower_text = (text_content or "").lower()[:6000]
        combined = f"{lower_fn}\n{lower_text}"

        # 1. Detect Competitor
        detected_competitor = None
        for comp in self.KNOWN_COMPETITORS:
            pattern = rf"\b{re.escape(comp.lower())}\b"
            if re.search(pattern, combined):
                detected_competitor = comp
                break

        # 2. Detect Industry
        detected_industry = None
        for ind in self.KNOWN_INDUSTRIES:
            if ind.lower() in combined:
                detected_industry = ind
                break

        # 3. Score Categories
        scores = {cat: 0 for cat in VALID_SALES_CATEGORIES}

        # BATTLECARD
        battlecard_signals = [
            "battlecard", "battle card", "competitor", "vs ", "versus",
            "differentiator", "kill sheet", "objection handling", "rebuttal",
            "why we win", "where they win", "landmine", "feature shootout",
            "beats ", "outperforms", "pitching against", "alternative to", "comparison"
        ]
        for sig in battlecard_signals:
            if sig in lower_fn:
                scores["BATTLECARD"] += 5
            if sig in lower_text:
                scores["BATTLECARD"] += 2
        if detected_competitor and ("vs" in lower_fn or "battlecard" in lower_fn or "comparison" in lower_fn):
            scores["BATTLECARD"] += 6

        # PRICING_PACKAGING
        pricing_signals = [
            "pricing", "rate card", "price list", "packaging", "subscription tier",
            "per user", "per month", "per seat", "discount", "quote", "enterprise tier",
            "starter tier", "billing cycle", "arr", "acv", "payment schedule", "license fee"
        ]
        for sig in pricing_signals:
            if sig in lower_fn:
                scores["PRICING_PACKAGING"] += 5
            if sig in lower_text:
                scores["PRICING_PACKAGING"] += 2

        # CASE_STUDY_ROI
        case_study_signals = [
            "case study", "customer story", "success story", "roi", "return on investment",
            "client story", "testimonial", "customer spotlight", "saved 40%", "increased conversion",
            "efficiency gain", "metrics gained", "benchmark results"
        ]
        for sig in case_study_signals:
            if sig in lower_fn:
                scores["CASE_STUDY_ROI"] += 5
            if sig in lower_text:
                scores["CASE_STUDY_ROI"] += 2

        # SECURITY_COMPLIANCE
        security_signals = [
            "soc 2", "soc2", "iso 27001", "iso27001", "gdpr", "hipaa", "compliance",
            "penetration test", "pen test", "data privacy", "encryption at rest", "cve",
            "security whitepaper", "access control", "audit report", "subprocessor"
        ]
        for sig in security_signals:
            if sig in lower_fn:
                scores["SECURITY_COMPLIANCE"] += 5
            if sig in lower_text:
                scores["SECURITY_COMPLIANCE"] += 2

        # PRODUCT_SPEC
        spec_signals = [
            "spec", "specification", "architecture", "api documentation", "api endpoint",
            "technical requirement", "data model", "schema", "sdk", "webhook", "payload",
            "release notes", "system architecture", "latency benchmark"
        ]
        for sig in spec_signals:
            if sig in lower_fn:
                scores["PRODUCT_SPEC"] += 5
            if sig in lower_text:
                scores["PRODUCT_SPEC"] += 2

        # CONTRACT_LEGAL
        legal_signals = [
            "master services agreement", "msa", "service level agreement", "sla",
            "data processing agreement", "dpa", "order form", "terms and conditions",
            "terms of service", "indemnification", "limitation of liability", "governing law"
        ]
        for sig in legal_signals:
            if sig in lower_fn:
                scores["CONTRACT_LEGAL"] += 5
            if sig in lower_text:
                scores["CONTRACT_LEGAL"] += 2

        # Pick top scoring category
        best_category = max(scores, key=lambda k: scores[k])
        max_score = scores[best_category]

        if max_score < 3:
            best_category = "GENERAL_RESOURCE"
            confidence = 0.5
        else:
            confidence = min(0.95, 0.5 + (max_score * 0.05))

        # Generate tags
        tags = []
        if detected_competitor:
            tags.append(f"vs {detected_competitor}")
        if detected_industry:
            tags.append(detected_industry)

        for sig in ["SOC2", "GDPR", "HIPAA", "Enterprise", "Pricing", "SLA", "API", "ROI"]:
            if sig.lower() in combined and sig not in tags:
                tags.append(sig)

        # Generate heuristic sales summary
        summary_templates = {
            "BATTLECARD": f"Competitive positioning and rebuttal intelligence against {detected_competitor or 'industry rivals'}.",
            "PRICING_PACKAGING": "Pricing structure, packaging tiers, and discounting guidelines for deal proposals.",
            "CASE_STUDY_ROI": f"Customer proof points and quantified ROI metrics in {detected_industry or 'enterprise environments'}.",
            "SECURITY_COMPLIANCE": "Security posture, compliance certifications, and enterprise trust documentation.",
            "PRODUCT_SPEC": "Detailed technical specifications, architecture blueprints, and product capabilities.",
            "CONTRACT_LEGAL": "Legal contract framework, service level agreements, and commercial commitments.",
            "GENERAL_RESOURCE": f"General business collateral and reference documentation for {filename}."
        }

        return SalesClassificationResult(
            category=best_category,
            target_competitor=detected_competitor,
            target_industry=detected_industry,
            sales_summary=summary_templates.get(best_category, f"Sales collateral: {filename}"),
            sales_tags=tags[:5],
            confidence_score=confidence,
            classifier_used="heuristic_rule_engine",
        )

"""Catalog relevance ranking (pure functions, no database)."""

import uuid

from catalog.search_ranking import SearchableProduct, rank_products, stem, terms


def _product(name, **fields):
    return SearchableProduct(product_id=uuid.uuid4(), name=name, **fields)


LAPTOP = _product(
    "Surface Laptop 6 for Business",
    category="laptops",
    keywords=["laptop", "business laptop", "windows"],
    description="A fast business laptop for small business teams that run software all day.",
    target_industries=["professional services"],
    skus=["SURF-6-16GB"],
)
EARBUDS = _product(
    "QuietComfort Ultra Earbuds",
    category="audio",
    keywords=["earbuds", "noise cancelling"],
    description="Premium earbuds for business travel and focus at work.",
    skus=["QC-ULTRA-BLK"],
)
INVOICING = _product(
    "Ledgerly Invoicing Suite",
    category="software",
    keywords=["invoice", "billing", "accounts receivable"],
    use_cases=["Automate invoicing for small businesses", "Chase late payments"],
    value_proposition="Get paid twice as fast with automated invoices and reminders.",
    description="Cloud software to create, send and track invoices.",
    skus=["LEDG-PRO-ANNUAL"],
)
CRM = _product(
    "PipeFlow CRM",
    category="software",
    keywords=["crm", "sales pipeline"],
    use_cases=["Track deals for small business sales teams"],
    description="Sales software for managing contacts and deals.",
    skus=["PIPE-TEAM"],
)
CATALOG = [LAPTOP, EARBUDS, INVOICING, CRM]


def test_a_rare_telling_word_outranks_common_ones():
    ranked = rank_products("software for small business invoicing", CATALOG)

    assert ranked[0].product_id == INVOICING.product_id
    assert EARBUDS.product_id not in [item.product_id for item in ranked]  # "business" alone isn't enough
    assert ranked[0].rationale.startswith("Matched 'invoicing' in name")  # explained with the words as typed
    assert ranked[0].matched_terms[0] == "invoicing"


def test_word_forms_match_each_other():
    assert stem("invoicing") == stem("invoices") == stem("invoice")
    assert stem("business") == "business" and stem("laptops") == "laptop"
    assert terms("How do we bill our customers?") == ["bill", "customer"]

    [top, *_] = rank_products("invoice automation", CATALOG)
    assert top.product_id == INVOICING.product_id


def test_an_exact_sku_wins_outright():
    ranked = rank_products("qc-ultra-blk", CATALOG)
    assert ranked[0].product_id == EARBUDS.product_id and ranked[0].rationale.startswith("Matched exact SKU")


def test_weak_matches_far_below_the_best_are_dropped_and_nothing_matches_nothing():
    ranked = rank_products("crm for sales pipeline", CATALOG)
    assert [item.product_id for item in ranked][:1] == [CRM.product_id]
    assert all(item.score >= ranked[0].score * 0.25 for item in ranked)
    assert rank_products("t-shirt", CATALOG) == []


def test_expanded_terms_widen_recall_but_never_outrank_the_typed_words():
    # "billing" was not typed; it only comes from query expansion.
    typed_only = rank_products("accounts", CATALOG)
    expanded = rank_products("accounts", CATALOG, expanded_terms=["billing", "earbuds"])
    assert [item.product_id for item in typed_only] == [INVOICING.product_id]
    assert expanded[0].product_id == INVOICING.product_id  # the typed word still decides the top result

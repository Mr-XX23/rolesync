"""Tests for the dynamic classification content sampler (build_classification_content)."""

from module_1_document_processing.classification.sales_classifier import (
    build_classification_content,
)

SEP = "\n\n[...]\n\n"


def test_empty_returns_empty():
    assert build_classification_content("", max_chars=1000) == ""
    assert build_classification_content("   ", max_chars=1000) == ""


def test_short_document_used_whole():
    text = "This is a short battlecard vs Salesforce. " * 5  # ~210 chars
    out = build_classification_content(text, max_chars=4000)
    assert out == text.strip()  # no sampling for short docs


def test_document_at_budget_boundary_used_whole():
    text = "a" * 4000
    assert build_classification_content(text, max_chars=4000) == text


def test_long_document_sampled_within_budget_with_start_and_end():
    text = ("S" * 50000) + ("E" * 50000)  # 100k chars
    out = build_classification_content(text, max_chars=4000, min_chunk_chars=500, max_regions=12)
    assert len(out) <= 4000                 # never exceeds the budget
    assert out.startswith("S" * 100)        # includes the beginning
    assert out.endswith("E" * 100)          # includes the very end


def test_sampling_is_deterministic():
    text = "".join(chr(65 + (i % 26)) for i in range(75000))
    a = build_classification_content(text, max_chars=3000)
    b = build_classification_content(text, max_chars=3000)
    assert a == b


def test_more_regions_for_larger_documents():
    small = "a" * 20000
    big = "b" * 400000
    small_out = build_classification_content(small, max_chars=8000, region_stride_chars=6000, max_regions=12)
    big_out = build_classification_content(big, max_chars=8000, region_stride_chars=6000, max_regions=12)
    small_regions = small_out.count(SEP) + 1
    big_regions = big_out.count(SEP) + 1
    assert big_regions > small_regions
    assert big_regions <= 12
    assert len(big_out) <= 8000 and len(small_out) <= 8000


def test_budget_respected_across_many_sizes():
    for n in (5_000, 50_000, 500_000, 2_000_000):
        text = "x" * n
        out = build_classification_content(text, max_chars=6000, min_chunk_chars=500, max_regions=12)
        assert len(out) <= 6000, f"budget exceeded for size {n}: {len(out)}"


def test_chunk_size_never_below_minimum():
    text = "z" * 200000
    out = build_classification_content(text, max_chars=6000, min_chunk_chars=500, max_regions=12)
    for chunk in out.split(SEP):
        assert len(chunk) >= 500

"""Guardrails (implementation-plan §8): turn limits + loop detection, saga compensation,
per-tenant budgets. Per-call retry/timeout and the per-tool circuit breaker live in
``app.tools.executor``; the approval TTL worker lives in the runner's maintenance sweep."""

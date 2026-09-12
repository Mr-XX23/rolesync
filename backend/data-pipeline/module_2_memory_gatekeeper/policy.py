"""Gatekeeper policy, driven by configuration rather than hardcoded constants.

The architecture calls for a config-driven gatekeeper whose audit trail records
the policy version behind each decision. Previously the thresholds were module
constants and every audit entry claimed "v1.0.0" no matter what they were, so a
decision could not be explained after the fact.

`version` is derived from the active values, so changing a threshold changes the
recorded version automatically.

Config (env):
  GATEKEEPER_MIN_TEXT_LENGTH          default 10
  GATEKEEPER_MAX_ENTROPY              default 6.0    (above this = corrupted/encrypted)
  GATEKEEPER_MIN_UNIQUE_RATIO         default 0.2    (below this = repetitive noise)
  GATEKEEPER_SEMANTIC_ENABLED         default true
  GATEKEEPER_SEMANTIC_ENFORCED        default false  (log-only; see arch.md)
  GATEKEEPER_SEMANTIC_MIN_SCORE       default 0.35
  GOOGLE_GEMINI_MODE                  default gemini-3.5-flash-lite
  GATEKEEPER_SEMANTIC_TIMEOUT_SECONDS default 20
  GATEKEEPER_REJECTED_TTL_DAYS        default 30
  GATEKEEPER_QUARANTINE_TTL_DAYS      default 90
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

DEFAULT_SEMANTIC_MODEL = "gemini-3.5-flash-lite"
_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSEY:
        return False
    return default


@dataclass(frozen=True)
class GatekeeperPolicy:
    min_text_length: int
    max_shannon_entropy: float
    min_unique_ratio: float
    semantic_enabled: bool
    semantic_enforced: bool
    semantic_min_score: float
    semantic_model: str
    semantic_timeout_seconds: float
    rejected_ttl_days: int
    quarantine_ttl_days: int

    @property
    def version(self) -> str:
        """Stable fingerprint of the active policy, recorded on every decision."""
        payload = "|".join(
            str(v)
            for v in (
                self.min_text_length,
                self.max_shannon_entropy,
                self.min_unique_ratio,
                self.semantic_enabled,
                self.semantic_enforced,
                self.semantic_min_score,
                self.semantic_model,
            )
        )
        return "gk-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def describe(self) -> dict:
        return {
            "version": self.version,
            "min_text_length": self.min_text_length,
            "max_shannon_entropy": self.max_shannon_entropy,
            "min_unique_ratio": self.min_unique_ratio,
            "semantic_enabled": self.semantic_enabled,
            "semantic_enforced": self.semantic_enforced,
            "semantic_min_score": self.semantic_min_score,
            "semantic_model": self.semantic_model,
            "rejected_ttl_days": self.rejected_ttl_days,
            "quarantine_ttl_days": self.quarantine_ttl_days,
        }


def load_policy() -> GatekeeperPolicy:
    """Read the active policy from the environment."""
    return GatekeeperPolicy(
        min_text_length=_int_env("GATEKEEPER_MIN_TEXT_LENGTH", 10),
        max_shannon_entropy=_float_env("GATEKEEPER_MAX_ENTROPY", 6.0),
        min_unique_ratio=_float_env("GATEKEEPER_MIN_UNIQUE_RATIO", 0.2),
        semantic_enabled=_bool_env("GATEKEEPER_SEMANTIC_ENABLED", True),
        # Log-only by default: arch.md says launch the scorer in LOG-ONLY mode,
        # and rejecting on an untuned threshold would silently drop good content.
        semantic_enforced=_bool_env("GATEKEEPER_SEMANTIC_ENFORCED", False),
        semantic_min_score=_float_env("GATEKEEPER_SEMANTIC_MIN_SCORE", 0.35),
        semantic_model=(os.environ.get("GOOGLE_GEMINI_MODE", "").strip() or DEFAULT_SEMANTIC_MODEL),
        semantic_timeout_seconds=_float_env("GATEKEEPER_SEMANTIC_TIMEOUT_SECONDS", 20.0),
        rejected_ttl_days=_int_env("GATEKEEPER_REJECTED_TTL_DAYS", 30),
        quarantine_ttl_days=_int_env("GATEKEEPER_QUARANTINE_TTL_DAYS", 90),
    )

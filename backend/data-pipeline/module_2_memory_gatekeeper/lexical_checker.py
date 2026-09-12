import math
import re
from dataclasses import dataclass
from typing import Optional

from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_2_memory_gatekeeper.policy import GatekeeperPolicy, load_policy


@dataclass
class LexicalResult:
    is_valid: bool
    reason: str
    entropy: float = 0.0
    unique_ratio: float = 0.0


class LexicalChecker:
    """Lexical & Shannon entropy checker filtering low-quality/corrupted content.

    Thresholds come from the active gatekeeper policy rather than module
    constants, so they can be tuned per deployment and the decision can be
    explained by its recorded policy version.
    """

    def __init__(self, policy: Optional[GatekeeperPolicy] = None) -> None:
        self._policy = policy

    @property
    def policy(self) -> GatekeeperPolicy:
        return self._policy or load_policy()

    def check(self, document: ParsedDocument, policy: Optional[GatekeeperPolicy] = None) -> LexicalResult:
        # The caller may pass the policy it is auditing against, so a single
        # policy governs the whole decision and the recorded version is honest.
        policy = policy or self.policy
        text = (document.text_content or "").strip()

        if len(text) < policy.min_text_length:
            return LexicalResult(
                is_valid=False,
                reason=f"Text length ({len(text)}) below minimum limit of {policy.min_text_length} characters",
            )

        entropy = self._calculate_shannon_entropy(text)
        if entropy > policy.max_shannon_entropy:
            return LexicalResult(
                is_valid=False,
                reason=(
                    f"High Shannon Entropy ({round(entropy, 2)} > {policy.max_shannon_entropy}) "
                    "indicates corrupted/encrypted text"
                ),
                entropy=entropy,
            )

        words = re.findall(r"\b\w+\b", text.lower())
        if words:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio < policy.min_unique_ratio:
                return LexicalResult(
                    is_valid=False,
                    reason=(
                        f"Low unique word ratio ({round(unique_ratio, 2)} < {policy.min_unique_ratio}) "
                        "indicates repetitive noise"
                    ),
                    entropy=entropy,
                    unique_ratio=unique_ratio,
                )
        else:
            unique_ratio = 1.0

        return LexicalResult(is_valid=True, reason="Clean text content", entropy=entropy, unique_ratio=unique_ratio)

    def _calculate_shannon_entropy(self, text: str) -> float:
        if not text:
            return 0.0
        entropy = 0.0
        length = len(text)
        counts: dict[str, int] = {}
        for char in text:
            counts[char] = counts.get(char, 0) + 1
        for count in counts.values():
            p = count / length
            entropy -= p * math.log2(p)
        return round(entropy, 4)

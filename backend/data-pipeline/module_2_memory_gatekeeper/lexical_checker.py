import math
import re
from dataclasses import dataclass
from module_1_document_processing.parsing.parsed_document import ParsedDocument

MIN_TEXT_LENGTH = 10
MAX_SHANNON_ENTROPY = 6.0
MIN_UNIQUE_RATIO = 0.2

@dataclass
class LexicalResult:
    is_valid: bool
    reason: str
    entropy: float = 0.0
    unique_ratio: float = 0.0

class LexicalChecker:
    """Lexical & Shannon Entropy Checker to filter low-quality/corrupted document memory."""

    def check(self, document: ParsedDocument) -> LexicalResult:
        text = (document.text_content or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            return LexicalResult(is_valid=False, reason=f"Text length ({len(text)}) below minimum limit of 10 characters")

        entropy = self._calculate_shannon_entropy(text)
        if entropy > MAX_SHANNON_ENTROPY:
            return LexicalResult(
                is_valid=False,
                reason=f"High Shannon Entropy ({round(entropy, 2)} > {MAX_SHANNON_ENTROPY}) indicates corrupted/encrypted text",
                entropy=entropy,
            )

        words = re.findall(r"\b\w+\b", text.lower())
        if words:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio < MIN_UNIQUE_RATIO:
                return LexicalResult(
                    is_valid=False,
                    reason=f"Low unique word ratio ({round(unique_ratio, 2)} < {MIN_UNIQUE_RATIO}) indicates repetitive noise",
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

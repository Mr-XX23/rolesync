import math
import re
from dataclasses import dataclass
from parsing.parsed_document import ParsedDocument

MIN_TEXT_LENGTH = 10
MAX_SHANNON_ENTROPY = 6.0  # High entropy indicates encrypted/base64/compressed noise
MIN_UNIQUE_RATIO = 0.2     # Low unique ratio indicates repeated gibberish e.g. "aaaaa aaaaa"

@dataclass
class LexicalResult:
    is_valid: bool
    entropy: float
    unique_ratio: float
    word_count: int
    reason: str

class LexicalChecker:
    """Lexical & Shannon Entropy Checker to reject gibberish, noise, or corrupt text."""

    def check(self, document: ParsedDocument) -> LexicalResult:
        text = document.text_content.strip()
        
        # 1. Minimum text length check
        if len(text) < MIN_TEXT_LENGTH:
            return LexicalResult(
                is_valid=False,
                entropy=0.0,
                unique_ratio=0.0,
                word_count=0,
                reason=f"Text length ({len(text)}) below minimum threshold of {MIN_TEXT_LENGTH} chars",
            )

        # 2. Words & Unique Ratio Check
        words = re.findall(r"\b\w+\b", text.lower())
        word_count = len(words)
        if word_count == 0:
            return LexicalResult(
                is_valid=False,
                entropy=0.0,
                unique_ratio=0.0,
                word_count=0,
                reason="No readable words found in text",
            )

        unique_words = set(words)
        unique_ratio = len(unique_words) / float(word_count)

        if unique_ratio < MIN_UNIQUE_RATIO and word_count > 15:
            return LexicalResult(
                is_valid=False,
                entropy=0.0,
                unique_ratio=unique_ratio,
                word_count=word_count,
                reason=f"Low unique word ratio ({unique_ratio:.2f}) indicates repetitive noise",
            )

        # 3. Shannon Entropy Check
        entropy = self._calculate_shannon_entropy(text)
        if entropy > MAX_SHANNON_ENTROPY:
            return LexicalResult(
                is_valid=False,
                entropy=entropy,
                unique_ratio=unique_ratio,
                word_count=word_count,
                reason=f"High Shannon entropy ({entropy:.2f}) indicates random/encrypted noise",
            )

        return LexicalResult(
            is_valid=True,
            entropy=entropy,
            unique_ratio=unique_ratio,
            word_count=word_count,
            reason="Clean document text",
        )

    def _calculate_shannon_entropy(self, text: str) -> float:
        if not text:
            return 0.0
        frequencies = {}
        for char in text:
            frequencies[char] = frequencies.get(char, 0) + 1

        entropy = 0.0
        text_len = len(text)
        for count in frequencies.values():
            p = count / text_len
            entropy -= p * math.log2(p)

        return entropy

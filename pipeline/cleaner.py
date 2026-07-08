from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002700-\U000027bf"
    "\U00002600-\U000026ff"
    "]"
)

LOW_SIGNAL_TEXTS = {
    ".",
    "-",
    "bad",
    "fine",
    "good",
    "great",
    "love it",
    "nice",
    "ok",
    "okay",
    "thanks",
    "thank you",
}


@dataclass
class ProcessedReview:
    source: str
    app_id: str
    app_name: str
    country: str
    review_id: str
    author: str | None
    rating: int
    version: str | None
    title: str | None
    review_text: str
    review_date: str
    collected_at: str
    language_code: str | None
    review_text_hash: str
    review_text_length: int
    review_word_count: int
    has_emoji: bool
    is_low_signal: bool
    is_duplicate_text: bool = False


@dataclass(frozen=True)
class CleaningResult:
    reviews: list[ProcessedReview]
    records_skipped: int


def trim_whitespace(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().casefold()


def text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def word_count(value: str) -> int:
    return len(re.findall(r"\b[\w']+\b", value, flags=re.UNICODE))


def contains_emoji(value: str) -> bool:
    return bool(EMOJI_RE.search(value))


def low_signal(value: str) -> bool:
    normalized = normalize_text(value)
    compact = re.sub(r"\s+", "", normalized)
    words = word_count(normalized)

    if not normalized:
        return True
    if normalized in LOW_SIGNAL_TEXTS:
        return True
    if words <= 2:
        return True
    if len(compact) >= 3 and len(set(compact)) <= 2:
        return True
    return False


def _clean_one(raw: Mapping[str, Any]) -> ProcessedReview | None:
    source = trim_whitespace(raw.get("source")) or "apple_app_store"
    app_id = trim_whitespace(raw.get("app_id"))
    app_name = trim_whitespace(raw.get("app_name"))
    country = (trim_whitespace(raw.get("country")) or "").lower()
    review_id = trim_whitespace(raw.get("review_id"))
    review_text_value = raw.get("review_text")
    review_date = trim_whitespace(raw.get("review_date"))
    collected_at = trim_whitespace(raw.get("collected_at"))

    if review_text_value is None:
        return None

    review_text = str(review_text_value)
    if not app_id or not app_name or not country or not review_id or not review_date or not collected_at:
        return None
    if not normalize_text(review_text):
        return None

    try:
        rating = int(raw.get("rating"))
    except (TypeError, ValueError):
        return None

    if rating < 1 or rating > 5:
        return None

    return ProcessedReview(
        source=source,
        app_id=app_id,
        app_name=app_name,
        country=country,
        review_id=review_id,
        author=trim_whitespace(raw.get("author")),
        rating=rating,
        version=trim_whitespace(raw.get("version")),
        title=trim_whitespace(raw.get("title")),
        review_text=review_text,
        review_date=review_date,
        collected_at=collected_at,
        language_code=trim_whitespace(raw.get("language_code")),
        review_text_hash=text_hash(review_text),
        review_text_length=len(review_text.strip()),
        review_word_count=word_count(review_text),
        has_emoji=contains_emoji(review_text),
        is_low_signal=low_signal(review_text),
    )


def clean_reviews(raw_reviews: Iterable[Mapping[str, Any]]) -> CleaningResult:
    processed: list[ProcessedReview] = []
    skipped = 0

    for raw in raw_reviews:
        review = _clean_one(raw)
        if review is None:
            skipped += 1
            continue
        processed.append(review)

    hash_counts: dict[str, int] = {}
    for review in processed:
        hash_counts[review.review_text_hash] = hash_counts.get(review.review_text_hash, 0) + 1

    for review in processed:
        review.is_duplicate_text = hash_counts[review.review_text_hash] > 1

    return CleaningResult(reviews=processed, records_skipped=skipped)


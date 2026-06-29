from __future__ import annotations

import logging
from typing import Any

from structuring.parser import CleanReview, parse_review
from structuring.validator import ValidationReport, validate_review


logger = logging.getLogger(__name__)


def transform_reviews(raw_reviews: list[dict[str, Any]]) -> tuple[list[CleanReview], ValidationReport]:
    report = ValidationReport()
    cleaned: list[CleanReview] = []
    seen_keys: set[tuple[str, str]] = set()

    for index, raw in enumerate(raw_reviews, start=1):
        review = parse_review(raw)
        errors = validate_review(review)
        key = (review.source, review.source_review_id)
        if key in seen_keys:
            errors.append("duplicate source/source_review_id in current batch")

        if errors:
            report.invalid_count += 1
            report.errors.append(f"record {index}: {', '.join(errors)}")
            logger.warning("Dropping invalid record %s: %s", index, "; ".join(errors))
            continue

        seen_keys.add(key)
        cleaned.append(review)
        report.valid_count += 1

    return cleaned, report

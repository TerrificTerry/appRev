from __future__ import annotations

from dataclasses import dataclass, field

from structuring.parser import CleanReview


@dataclass
class ValidationReport:
    valid_count: int = 0
    invalid_count: int = 0
    errors: list[str] = field(default_factory=list)


def validate_review(review: CleanReview) -> list[str]:
    errors: list[str] = []
    if not review.source_review_id:
        errors.append("source_review_id is required")
    if not review.product_name:
        errors.append("product_name is required")
    if not review.review_text:
        errors.append("review_text is required")
    if not 1 <= review.rating <= 5:
        errors.append("rating must be an integer from 1 to 5")
    return errors

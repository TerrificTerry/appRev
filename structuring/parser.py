from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from structuring.cleaner import clean_datetime, clean_rating, clean_text


@dataclass(frozen=True)
class CleanReview:
    source: str
    source_review_id: str
    source_url: str | None
    product_name: str
    product_id: str | None
    reviewer_name: str | None
    rating: int
    review_title: str | None
    review_text: str
    review_date: datetime
    price: str | None
    availability: str | None
    raw_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["review_date"] = self.review_date.isoformat()
        return data


def parse_review(raw: dict[str, Any]) -> CleanReview:
    return CleanReview(
        source=clean_text(raw.get("source")) or "unknown",
        source_review_id=clean_text(raw.get("source_review_id")) or "",
        source_url=clean_text(raw.get("source_url")),
        product_name=clean_text(raw.get("product_name")) or "",
        product_id=clean_text(raw.get("product_id")),
        reviewer_name=clean_text(raw.get("reviewer_name")),
        rating=clean_rating(raw.get("rating")) or 0,
        review_title=clean_text(raw.get("review_title")),
        review_text=clean_text(raw.get("review_text")) or "",
        review_date=clean_datetime(raw.get("review_date")),
        price=clean_text(raw.get("price")),
        availability=clean_text(raw.get("availability")),
        raw_payload=raw.get("raw_payload") if isinstance(raw.get("raw_payload"), dict) else {},
    )

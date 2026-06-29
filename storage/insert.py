from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import Product, Review
from structuring.parser import CleanReview


def upsert_reviews(session: Session, reviews: list[CleanReview]) -> tuple[int, int]:
    inserted = 0
    updated = 0

    for clean in reviews:
        product = get_or_create_product(session, clean)
        existing = session.scalar(
            select(Review).where(
                Review.source == clean.source,
                Review.source_review_id == clean.source_review_id,
            )
        )

        payload = {
            "product_id": product.id,
            "source": clean.source,
            "source_review_id": clean.source_review_id,
            "source_url": clean.source_url,
            "reviewer_name": clean.reviewer_name,
            "rating": clean.rating,
            "title": clean.review_title,
            "text": clean.review_text,
            "review_date": clean.review_date,
            "price": clean.price,
            "availability": clean.availability,
            "raw_payload": clean.raw_payload,
        }

        if existing:
            for field, value in payload.items():
                setattr(existing, field, value)
            updated += 1
        else:
            session.add(Review(**payload))
            inserted += 1

    return inserted, updated


def get_or_create_product(session: Session, review: CleanReview) -> Product:
    product = session.scalar(
        select(Product).where(
            Product.source == review.source,
            Product.source_product_id == review.product_id,
            Product.name == review.product_name,
        )
    )
    if product:
        return product

    product = Product(
        source=review.source,
        source_product_id=review.product_id,
        name=review.product_name,
    )
    session.add(product)
    session.flush()
    return product

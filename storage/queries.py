from __future__ import annotations

from sqlalchemy import desc, func, select

from storage.database import get_session
from storage.models import Product, Review


def get_database_summary() -> dict[str, object]:
    with get_session() as session:
        total_products = session.scalar(select(func.count(Product.id))) or 0
        total_reviews = session.scalar(select(func.count(Review.id))) or 0
        average_rating = session.scalar(select(func.avg(Review.rating))) or 0
        by_source = session.execute(
            select(Review.source, func.count(Review.id))
            .group_by(Review.source)
            .order_by(desc(func.count(Review.id)))
        ).all()
        latest_reviews = session.execute(
            select(Review.source, Review.rating, Review.title, Review.review_date)
            .order_by(desc(Review.review_date))
            .limit(5)
        ).all()

    return {
        "total_products": total_products,
        "total_reviews": total_reviews,
        "average_rating": round(float(average_rating), 2),
        "reviews_by_source": dict(by_source),
        "latest_reviews": [
            {
                "source": source,
                "rating": rating,
                "title": title,
                "review_date": review_date.isoformat(),
            }
            for source, rating, title, review_date in latest_reviews
        ],
    }


def print_database_summary() -> None:
    summary = get_database_summary()
    print("\nDatabase summary")
    print("----------------")
    print(f"Products: {summary['total_products']}")
    print(f"Reviews: {summary['total_reviews']}")
    print(f"Average rating: {summary['average_rating']}")
    print(f"Reviews by source: {summary['reviews_by_source']}")
    print("Latest reviews:")
    for review in summary["latest_reviews"]:
        print(f"- [{review['rating']}/5] {review['title']} ({review['source']})")

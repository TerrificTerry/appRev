from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests


APP_ID = "1058959277"
APP_NAME = "Uber Eats"
COUNTRY = "us"
OUTPUT_CSV = "ubereats_apple_reviews_us.csv"

APPLE_REVIEW_FEED_URL = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "page={page}/sortBy=mostRecent/id={app_id}/json"
)

REQUIRED_FIELDS = [
    "source",
    "app_id",
    "app_name",
    "country",
    "review_id",
    "author",
    "rating",
    "version",
    "title",
    "review_text",
    "review_date",
    "collected_at",
]


def feed_url(app_id: str, country: str, page: int) -> str:
    return APPLE_REVIEW_FEED_URL.format(country=country, page=page, app_id=app_id)


def label(entry: dict[str, Any], *path: str) -> str | None:
    value: Any = entry
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)

    if isinstance(value, str):
        return value.strip() or None
    return None


def fetch_review_page(
    session: requests.Session,
    app_id: str,
    country: str,
    page: int,
) -> list[dict[str, Any]]:
    response = session.get(feed_url(app_id=app_id, country=country, page=page), timeout=20)

    if response.status_code == 404:
        return []

    response.raise_for_status()
    data = response.json()
    entries = data.get("feed", {}).get("entry", [])

    if isinstance(entries, dict):
        entries = [entries]

    return [entry for entry in entries if isinstance(entry, dict)]


def parse_review(
    entry: dict[str, Any],
    app_id: str,
    app_name: str,
    country: str,
    collected_at: str,
) -> dict[str, Any] | None:
    review_id = label(entry, "id", "label")
    rating = label(entry, "im:rating", "label")

    if not review_id or not rating:
        return None

    try:
        rating_value = int(rating)
    except ValueError:
        return None

    record = {
        "source": "apple_app_store",
        "app_id": app_id,
        "app_name": app_name,
        "country": country,
        "review_id": review_id,
        "author": label(entry, "author", "name", "label"),
        "rating": rating_value,
        "version": label(entry, "im:version", "label"),
        "title": label(entry, "title", "label"),
        "review_text": label(entry, "content", "label"),
        "review_date": label(entry, "updated", "label"),
        "collected_at": collected_at,
    }

    if any(record[field] in (None, "") for field in REQUIRED_FIELDS):
        return None

    return record


def collect_reviews(
    app_id: str = APP_ID,
    app_name: str = APP_NAME,
    country: str = COUNTRY,
    max_pages: int = 10,
) -> pd.DataFrame:
    collected_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    seen_review_ids: set[str] = set()

    with requests.Session() as session:
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Sciencia Apple Review Prototype/1.0",
            }
        )

        for page in range(1, max_pages + 1):
            entries = fetch_review_page(
                session=session,
                app_id=app_id,
                country=country,
                page=page,
            )

            review_count_before_page = len(rows)
            for entry in entries:
                record = parse_review(
                    entry=entry,
                    app_id=app_id,
                    app_name=app_name,
                    country=country,
                    collected_at=collected_at,
                )

                if record is None:
                    continue

                review_id = record["review_id"]
                if review_id in seen_review_ids:
                    continue

                seen_review_ids.add(review_id)
                rows.append(record)

            if not entries or len(rows) == review_count_before_page:
                break

    return pd.DataFrame(rows, columns=REQUIRED_FIELDS)


def main() -> None:
    reviews = collect_reviews()
    reviews.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    print(f"Collected {len(reviews)} Apple App Store reviews")
    print(f"Saved to {OUTPUT_CSV}")
    print(reviews.head())


if __name__ == "__main__":
    main()

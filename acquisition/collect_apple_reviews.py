from __future__ import annotations

import argparse
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

from storage.apple_review_store import DEFAULT_DB_PATH, write_reviews_to_database


SOURCE = "apple_app_store"
DEFAULT_MAX_PAGES_PER_COUNTRY = 10
DEFAULT_DELAY_SECONDS = 0.35
RESULTS_DIR = Path("data/apple_review_collection")
REVIEWS_OUTPUT = RESULTS_DIR / "apple_app_reviews.csv"
SUMMARY_OUTPUT = RESULTS_DIR / "apple_app_collection_summary.csv"
PER_APP_OUTPUT_DIR = RESULTS_DIR / "reviews_by_app"

APPLE_REVIEW_FEED_URL = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "page={page}/sortBy=mostRecent/id={app_id}/json"
)

TARGET_APPS = [
    {
        "app_key": "ubereats",
        "app_id": "1058959277",
        "app_name": "Uber Eats",
    },
    {
        "app_key": "doordash",
        "app_id": "719972451",
        "app_name": "DoorDash",
    },
    {
        "app_key": "discord",
        "app_id": "985746746",
        "app_name": "Discord",
    },
]

DEFAULT_COUNTRIES = [
    "us",
    "ca",
    "gb",
    "au",
    "nz",
    "ie",
    "fr",
    "de",
    "es",
    "it",
    "nl",
    "be",
    "ch",
    "mx",
    "br",
    "cl",
    "co",
    "pe",
    "cr",
    "jp",
    "tw",
    "hk",
    "sg",
    "za",
    "pl",
    "se",
    "no",
    "dk",
    "fi",
    "pt",
]

REQUIRED_FIELDS = [
    "source",
    "app_id",
    "app_name",
    "app_key",
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


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "app"


@dataclass
class CollectionSummary:
    app_key: str
    app_id: str
    app_name: str
    country: str
    pages_requested: int = 0
    reviews_collected: int = 0
    malformed_skipped: int = 0
    duplicate_skipped: int = 0
    status: str = "not_started"


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
    retries: int = 2,
) -> tuple[list[dict[str, Any]], str]:
    url = feed_url(app_id=app_id, country=country, page=page)

    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=25)
            if response.status_code == 404:
                return [], "not_found"

            response.raise_for_status()
            data = response.json()
            entries = data.get("feed", {}).get("entry", [])

            if isinstance(entries, dict):
                entries = [entries]

            if not isinstance(entries, list):
                return [], "malformed_feed"

            return [entry for entry in entries if isinstance(entry, dict)], "ok"
        except requests.RequestException as exc:
            if attempt == retries:
                return [], f"request_error:{exc.__class__.__name__}"
            time.sleep(1.5 * (attempt + 1))
        except ValueError:
            return [], "json_error"

    return [], "unknown_error"


def parse_review(
    entry: dict[str, Any],
    app: dict[str, str],
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
        "source": SOURCE,
        "app_id": app["app_id"],
        "app_name": app["app_name"],
        "app_key": app["app_key"],
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


def collect_app_country_reviews(
    session: requests.Session,
    app: dict[str, str],
    country: str,
    seen_review_keys: set[tuple[str, str]],
    max_pages: int,
    delay_seconds: float,
    collected_at: str,
) -> tuple[list[dict[str, Any]], CollectionSummary]:
    rows: list[dict[str, Any]] = []
    summary = CollectionSummary(
        app_key=app["app_key"],
        app_id=app["app_id"],
        app_name=app["app_name"],
        country=country,
        status="ok",
    )

    for page in range(1, max_pages + 1):
        entries, status = fetch_review_page(
            session=session,
            app_id=app["app_id"],
            country=country,
            page=page,
        )
        summary.pages_requested += 1

        if status != "ok":
            summary.status = status
            break

        if not entries:
            summary.status = "empty_page"
            break

        page_rows_before = len(rows)
        for entry in entries:
            record = parse_review(
                entry=entry,
                app=app,
                country=country,
                collected_at=collected_at,
            )

            if record is None:
                summary.malformed_skipped += 1
                continue

            review_key = (record["app_id"], record["review_id"])
            if review_key in seen_review_keys:
                summary.duplicate_skipped += 1
                continue

            seen_review_keys.add(review_key)
            rows.append(record)

        if len(rows) == page_rows_before:
            summary.status = "no_new_reviews"
            break

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    summary.reviews_collected = len(rows)
    return rows, summary


def collect_reviews(
    apps: list[dict[str, str]],
    countries: list[str],
    max_pages_per_country: int = DEFAULT_MAX_PAGES_PER_COUNTRY,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    progress_callback: Callable[[CollectionSummary, int, int], None] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    collected_at = datetime.now(timezone.utc).isoformat()
    seen_review_keys: set[tuple[str, str]] = set()
    all_rows: list[dict[str, Any]] = []
    summaries: list[CollectionSummary] = []
    total_tasks = len(apps) * len(countries)
    completed_tasks = 0

    with requests.Session() as session:
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Sciencia Apple Review Collector/1.0",
            }
        )

        for app in apps:
            print(f"\nCollecting {app['app_name']} ({app['app_id']})")
            for country in countries:
                country_code = country.lower()
                country_rows, summary = collect_app_country_reviews(
                    session=session,
                    app=app,
                    country=country_code,
                    seen_review_keys=seen_review_keys,
                    max_pages=max_pages_per_country,
                    delay_seconds=delay_seconds,
                    collected_at=collected_at,
                )
                all_rows.extend(country_rows)
                summaries.append(summary)
                completed_tasks += 1
                if progress_callback is not None:
                    progress_callback(summary, completed_tasks, total_tasks)
                print(
                    f"  {summary.country}: {summary.reviews_collected} reviews "
                    f"({summary.status}, {summary.pages_requested} pages)"
                )

    reviews = pd.DataFrame(all_rows, columns=REQUIRED_FIELDS)
    summary_df = pd.DataFrame([asdict(summary) for summary in summaries])
    return reviews, summary_df


def save_review_outputs(
    reviews: pd.DataFrame,
    summary: pd.DataFrame,
    reviews_output: Path = REVIEWS_OUTPUT,
    summary_output: Path = SUMMARY_OUTPUT,
    per_app_output_dir: Path | None = PER_APP_OUTPUT_DIR,
) -> list[Path]:
    reviews_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    reviews.to_csv(reviews_output, index=False, encoding="utf-8")
    summary.to_csv(summary_output, index=False, encoding="utf-8")

    per_app_paths: list[Path] = []
    if per_app_output_dir is None or reviews.empty:
        return per_app_paths

    per_app_output_dir.mkdir(parents=True, exist_ok=True)
    for app_key, app_reviews in reviews.groupby("app_key"):
        app_name = str(app_reviews["app_name"].iloc[0])
        filename = f"{slugify(app_name)}_{slugify(str(app_key))}_apple_reviews.csv"
        output_path = per_app_output_dir / filename
        app_reviews.to_csv(output_path, index=False, encoding="utf-8")
        per_app_paths.append(output_path)

    return per_app_paths


def parse_countries(raw_countries: str | None) -> list[str]:
    if not raw_countries:
        return DEFAULT_COUNTRIES

    countries = [country.strip().lower() for country in raw_countries.split(",")]
    return [country for country in countries if country]


def parse_apps(raw_apps: str | None) -> list[dict[str, str]]:
    if not raw_apps:
        return TARGET_APPS

    requested = {app.strip().lower() for app in raw_apps.split(",") if app.strip()}
    apps = [app for app in TARGET_APPS if app["app_key"] in requested]
    unknown = requested - {app["app_key"] for app in TARGET_APPS}

    if unknown:
        raise ValueError(f"Unknown app keys: {', '.join(sorted(unknown))}")

    return apps


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Apple App Store reviews from the public RSS/JSON feed."
    )
    parser.add_argument(
        "--apps",
        help="Comma-separated app keys. Options: ubereats,doordash,discord.",
    )
    parser.add_argument(
        "--countries",
        help="Comma-separated country codes. Defaults to a broad App Store market list.",
    )
    parser.add_argument(
        "--max-pages-per-country",
        type=int,
        default=DEFAULT_MAX_PAGES_PER_COUNTRY,
    )
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--reviews-output", type=Path, default=REVIEWS_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=SUMMARY_OUTPUT)
    parser.add_argument("--per-app-output-dir", type=Path, default=PER_APP_OUTPUT_DIR)
    parser.add_argument("--db-output", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--no-db", action="store_true", help="Skip writing to SQLite.")
    args = parser.parse_args()

    apps = parse_apps(args.apps)
    countries = parse_countries(args.countries)
    ingestion_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    reviews, summary = collect_reviews(
        apps=apps,
        countries=countries,
        max_pages_per_country=args.max_pages_per_country,
        delay_seconds=args.delay_seconds,
    )

    per_app_paths = save_review_outputs(
        reviews=reviews,
        summary=summary,
        reviews_output=args.reviews_output,
        summary_output=args.summary_output,
        per_app_output_dir=args.per_app_output_dir,
    )

    print()
    print(f"Collected {len(reviews)} unique Apple App Store reviews")
    print(f"Saved reviews to {args.reviews_output}")
    print(f"Saved collection summary to {args.summary_output}")
    for path in per_app_paths:
        print(f"Saved per-app reviews to {path}")
    if not args.no_db:
        db_result = write_reviews_to_database(
            reviews=reviews,
            summary=summary,
            apps=apps,
            countries=countries,
            ingestion_run_id=ingestion_run_id,
            db_path=args.db_output,
            collector_name="collect_apple_reviews",
            max_pages_per_country=args.max_pages_per_country,
            delay_seconds=args.delay_seconds,
        )
        print(
            f"Saved database to {db_result.db_path} "
            f"({db_result.records_inserted} inserted, {db_result.records_updated} updated)"
        )
    print(reviews.groupby("app_key").size().sort_values(ascending=False))
    print(reviews.head())


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.apple_store_collector import collect_apple_reviews
from database.db import DEFAULT_DB_PATH, database_connection
from pipeline.cleaner import clean_reviews
from pipeline.ingestion import (
    create_ingestion_run,
    finish_ingestion_run,
    get_or_create_source,
    upsert_reviews,
)


CollectorFn = Callable[..., list[dict]]


@dataclass(frozen=True)
class PipelineSummary:
    ingestion_run_id: int
    app_id: str
    country: str
    pages_requested: int
    database_path: Path
    records_collected: int
    records_seen: int
    records_inserted: int
    records_updated: int
    records_skipped: int
    status: str


def run_pipeline(
    *,
    app_id: str,
    country: str,
    pages: int,
    db_path: str | Path = DEFAULT_DB_PATH,
    app_name: str | None = None,
    retries: int = 3,
    delay_seconds: float = 0.25,
    collector: CollectorFn | None = None,
) -> PipelineSummary:
    db_path = Path(db_path)
    collector_fn = collector or collect_apple_reviews

    with database_connection(db_path) as connection:
        source_id = get_or_create_source(connection)
        ingestion_run_id = create_ingestion_run(connection, source_id)

        records_collected = 0
        records_inserted = 0
        records_updated = 0
        records_skipped = 0
        records_seen = 0

        try:
            raw_reviews = collector_fn(
                app_id=app_id,
                country=country,
                pages=pages,
                app_name=app_name,
                retries=retries,
                delay_seconds=delay_seconds,
            )
            records_collected = len(raw_reviews)
            cleaning_result = clean_reviews(raw_reviews)
            ingest_result = upsert_reviews(
                connection,
                cleaning_result.reviews,
                ingestion_run_id=ingestion_run_id,
                source_id=source_id,
            )

            records_seen = records_collected
            records_inserted = ingest_result.records_inserted
            records_updated = ingest_result.records_updated
            records_skipped = cleaning_result.records_skipped + ingest_result.records_skipped
            finish_ingestion_run(
                connection,
                ingestion_run_id,
                status="success",
                records_seen=records_seen,
                records_inserted=records_inserted,
                records_updated=records_updated,
                records_skipped=records_skipped,
            )
            status = "success"
        except Exception as exc:
            finish_ingestion_run(
                connection,
                ingestion_run_id,
                status="failed",
                records_seen=records_seen,
                records_inserted=records_inserted,
                records_updated=records_updated,
                records_skipped=records_skipped,
                error_message=str(exc),
            )
            connection.commit()
            raise

    return PipelineSummary(
        ingestion_run_id=ingestion_run_id,
        app_id=app_id,
        country=country.lower(),
        pages_requested=pages,
        database_path=db_path,
        records_collected=records_collected,
        records_seen=records_seen,
        records_inserted=records_inserted,
        records_updated=records_updated,
        records_skipped=records_skipped,
        status=status,
    )


def format_summary(summary: PipelineSummary) -> str:
    return "\n".join(
        [
            "Apple review ingestion complete",
            f"Run ID: {summary.ingestion_run_id}",
            f"Status: {summary.status}",
            f"App ID: {summary.app_id}",
            f"Country: {summary.country}",
            f"Pages requested: {summary.pages_requested}",
            f"Reviews collected: {summary.records_collected}",
            f"Records inserted: {summary.records_inserted}",
            f"Records updated: {summary.records_updated}",
            f"Records skipped: {summary.records_skipped}",
            f"Database: {summary.database_path}",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect, clean, and ingest Apple App Store reviews into SQLite."
    )
    parser.add_argument("--app-id", required=True, help="Apple App Store app id.")
    parser.add_argument("--country", default="us", help="App Store country code.")
    parser.add_argument("--pages", type=int, default=1, help="Number of review pages to fetch.")
    parser.add_argument("--app-name", help="Optional app name override.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_pipeline(
        app_id=args.app_id,
        country=args.country,
        pages=args.pages,
        app_name=args.app_name,
        db_path=args.db_path,
        retries=args.retries,
        delay_seconds=args.delay_seconds,
    )
    print(format_summary(summary))


if __name__ == "__main__":
    main()


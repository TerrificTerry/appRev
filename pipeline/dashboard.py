from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from database.db import DEFAULT_DB_PATH, database_connection


@dataclass(frozen=True)
class RecentRun:
    ingestion_run_id: int
    started_at: str
    finished_at: str | None
    status: str
    records_seen: int
    records_inserted: int
    records_updated: int
    records_skipped: int


@dataclass(frozen=True)
class RecentReview:
    app_name: str
    country: str
    rating: int
    title: str | None
    review_date: str


@dataclass(frozen=True)
class DatabaseDashboard:
    database_path: Path
    total_sources: int
    total_apps: int
    total_source_apps: int
    total_runs: int
    total_reviews: int
    average_rating: float
    low_signal_reviews: int
    duplicate_text_reviews: int
    recent_runs: list[RecentRun]
    recent_reviews: list[RecentReview]


def _count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def load_database_dashboard(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    recent_limit: int = 10,
) -> DatabaseDashboard:
    path = Path(db_path)

    with database_connection(path) as connection:
        rating_row = connection.execute("SELECT AVG(rating) AS average_rating FROM reviews").fetchone()
        low_signal_row = connection.execute(
            "SELECT COUNT(*) AS count FROM review_quality WHERE is_low_signal = 1"
        ).fetchone()
        duplicate_row = connection.execute(
            "SELECT COUNT(*) AS count FROM review_quality WHERE is_duplicate_text = 1"
        ).fetchone()
        run_rows = connection.execute(
            """
            SELECT ingestion_run_id, started_at, finished_at, status, records_seen,
                   records_inserted, records_updated, records_skipped
            FROM ingestion_runs
            ORDER BY ingestion_run_id DESC
            LIMIT ?
            """,
            (recent_limit,),
        ).fetchall()
        review_rows = connection.execute(
            """
            SELECT apps.canonical_name AS app_name, reviews.country, reviews.rating,
                   reviews.title, reviews.review_date
            FROM reviews
            JOIN source_apps ON reviews.source_app_id = source_apps.source_app_id
            JOIN apps ON source_apps.app_id = apps.app_id
            ORDER BY reviews.review_date DESC
            LIMIT ?
            """,
            (recent_limit,),
        ).fetchall()

        return DatabaseDashboard(
            database_path=path,
            total_sources=_count(connection, "sources"),
            total_apps=_count(connection, "apps"),
            total_source_apps=_count(connection, "source_apps"),
            total_runs=_count(connection, "ingestion_runs"),
            total_reviews=_count(connection, "reviews"),
            average_rating=round(float(rating_row["average_rating"] or 0), 2),
            low_signal_reviews=int(low_signal_row["count"]),
            duplicate_text_reviews=int(duplicate_row["count"]),
            recent_runs=[
                RecentRun(
                    ingestion_run_id=int(row["ingestion_run_id"]),
                    started_at=str(row["started_at"]),
                    finished_at=row["finished_at"],
                    status=str(row["status"]),
                    records_seen=int(row["records_seen"]),
                    records_inserted=int(row["records_inserted"]),
                    records_updated=int(row["records_updated"]),
                    records_skipped=int(row["records_skipped"]),
                )
                for row in run_rows
            ],
            recent_reviews=[
                RecentReview(
                    app_name=str(row["app_name"]),
                    country=str(row["country"]),
                    rating=int(row["rating"]),
                    title=row["title"],
                    review_date=str(row["review_date"]),
                )
                for row in review_rows
            ],
        )


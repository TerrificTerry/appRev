from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from storage.apple_review_store import DEFAULT_DB_PATH, init_apple_review_db


def print_query(connection: sqlite3.Connection, title: str, query: str) -> None:
    print(f"\n{title}")
    rows = connection.execute(query).fetchall()
    if not rows:
        print("(none)")
        return

    headers = rows[0].keys()
    print(" | ".join(headers))
    for row in rows:
        print(" | ".join(str(row[header]) for header in headers))


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Apple review SQLite database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.db) as connection:
        connection.row_factory = sqlite3.Row
        init_apple_review_db(connection)

        print(f"Database: {args.db}")
        print_query(
            connection,
            "Review counts by app",
            """
            SELECT a.canonical_name, sa.external_app_id, COUNT(*) AS review_count
            FROM reviews r
            JOIN source_apps sa ON sa.source_app_id = r.source_app_id
            JOIN apps a ON a.app_id = sa.app_id
            GROUP BY a.canonical_name, sa.external_app_id
            ORDER BY review_count DESC
            """,
        )
        print_query(
            connection,
            "Review counts by app and country",
            """
            SELECT a.canonical_name, r.country, COUNT(*) AS review_count
            FROM reviews r
            JOIN source_apps sa ON sa.source_app_id = r.source_app_id
            JOIN apps a ON a.app_id = sa.app_id
            GROUP BY a.canonical_name, r.country
            ORDER BY a.canonical_name, review_count DESC
            """,
        )
        print_query(
            connection,
            "Ingestion runs",
            """
            SELECT ingestion_run_id, collector_name, status, records_seen,
                   records_inserted, records_updated, records_skipped_malformed,
                   records_skipped_duplicate, started_at, finished_at
            FROM ingestion_runs
            ORDER BY started_at DESC
            LIMIT 20
            """,
        )
        print_query(
            connection,
            "Quality summary",
            """
            SELECT
                COUNT(*) AS quality_rows,
                SUM(is_low_signal) AS low_signal_rows,
                SUM(has_emoji) AS emoji_rows,
                SUM(is_duplicate_text) AS duplicate_text_rows
            FROM review_quality
            """,
        )


if __name__ == "__main__":
    main()

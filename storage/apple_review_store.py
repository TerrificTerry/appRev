from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SOURCE_KEY = "apple_app_store"
SOURCE_NAME = "Apple App Store"
SOURCE_BASE_URL = "https://itunes.apple.com"
SCHEMA_PATH = Path("storage/apple_review_schema_v1.sql")
DEFAULT_DB_PATH = Path("data/apple_review_collection/apple_reviews.sqlite")
QUALITY_VERSION = "quality_v1"

EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002700-\U000027bf"
    "\U00002600-\U000026ff"
    "]"
)


@dataclass
class DatabaseWriteResult:
    db_path: Path
    ingestion_run_id: str
    records_seen: int
    records_inserted: int
    records_updated: int
    quality_rows_written: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.lower()).strip()


def text_hash(value: object) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def text_length(value: object) -> int:
    if not isinstance(value, str):
        return 0
    return len(value.strip())


def word_count(value: object) -> int:
    if not isinstance(value, str):
        return 0
    return len(re.findall(r"\b\w+\b", value))


def ascii_ratio(value: object) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    return sum(1 for char in value if ord(char) < 128) / len(value)


def has_emoji(*values: object) -> bool:
    return any(isinstance(value, str) and EMOJI_RE.search(value) for value in values)


def is_low_signal(value: object) -> bool:
    if not isinstance(value, str):
        return True

    text = value.strip().lower()
    if not text:
        return True

    compact = re.sub(r"\s+", "", text)
    repeated_char = len(set(compact)) <= 2 and len(compact) >= 3
    short_generic = compact in {
        ".",
        "-",
        "good",
        "great",
        "bad",
        "nice",
        "ok",
        "okay",
        "loveit",
        "thanks",
        "thankyou",
        "👍",
        "👎",
    }
    return word_count(text) <= 2 or repeated_char or short_generic


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_apple_review_db(connection: sqlite3.Connection) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    connection.commit()


def get_or_create_source(connection: sqlite3.Connection) -> int:
    now = utc_now()
    connection.execute(
        """
        INSERT INTO sources (source_key, source_name, base_url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            source_name = excluded.source_name,
            base_url = excluded.base_url,
            updated_at = excluded.updated_at
        """,
        (SOURCE_KEY, SOURCE_NAME, SOURCE_BASE_URL, now, now),
    )
    row = connection.execute(
        "SELECT source_id FROM sources WHERE source_key = ?",
        (SOURCE_KEY,),
    ).fetchone()
    return int(row["source_id"])


def get_or_create_app(connection: sqlite3.Connection, app_key: str, app_name: str) -> int:
    now = utc_now()
    connection.execute(
        """
        INSERT INTO apps (app_key, canonical_name, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(app_key) DO UPDATE SET
            canonical_name = excluded.canonical_name,
            updated_at = excluded.updated_at
        """,
        (app_key, app_name, now, now),
    )
    row = connection.execute(
        "SELECT app_id FROM apps WHERE app_key = ?",
        (app_key,),
    ).fetchone()
    return int(row["app_id"])


def get_or_create_source_app(
    connection: sqlite3.Connection,
    source_id: int,
    app_id: int,
    external_app_id: str,
    external_app_name: str,
    store_country: str | None = None,
    app_url: str | None = None,
) -> int:
    now = utc_now()
    connection.execute(
        """
        INSERT INTO source_apps (
            source_id, app_id, external_app_id, external_app_name, store_country,
            app_url, is_active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(source_id, external_app_id) DO UPDATE SET
            app_id = excluded.app_id,
            external_app_name = excluded.external_app_name,
            store_country = COALESCE(excluded.store_country, source_apps.store_country),
            app_url = COALESCE(excluded.app_url, source_apps.app_url),
            is_active = 1,
            updated_at = excluded.updated_at
        """,
        (
            source_id,
            app_id,
            external_app_id,
            external_app_name,
            store_country,
            app_url,
            now,
            now,
        ),
    )
    row = connection.execute(
        """
        SELECT source_app_id
        FROM source_apps
        WHERE source_id = ? AND external_app_id = ?
        """,
        (source_id, external_app_id),
    ).fetchone()
    return int(row["source_app_id"])


def create_ingestion_run(
    connection: sqlite3.Connection,
    ingestion_run_id: str,
    source_id: int,
    collector_name: str,
    requested_apps: list[str],
    requested_countries: list[str],
    max_pages_per_country: int,
    delay_seconds: float,
) -> None:
    now = utc_now()
    connection.execute(
        """
        INSERT INTO ingestion_runs (
            ingestion_run_id, source_id, collector_name, started_at, status,
            requested_apps, requested_countries, max_pages_per_country,
            delay_seconds, created_at
        )
        VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)
        """,
        (
            ingestion_run_id,
            source_id,
            collector_name,
            now,
            json.dumps(requested_apps),
            json.dumps(requested_countries),
            max_pages_per_country,
            delay_seconds,
            now,
        ),
    )


def finish_ingestion_run(
    connection: sqlite3.Connection,
    ingestion_run_id: str,
    status: str,
    records_seen: int,
    records_inserted: int,
    records_updated: int,
    records_skipped_malformed: int,
    records_skipped_duplicate: int,
    error_message: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE ingestion_runs
        SET finished_at = ?,
            status = ?,
            records_seen = ?,
            records_inserted = ?,
            records_updated = ?,
            records_skipped_malformed = ?,
            records_skipped_duplicate = ?,
            error_message = ?
        WHERE ingestion_run_id = ?
        """,
        (
            utc_now(),
            status,
            records_seen,
            records_inserted,
            records_updated,
            records_skipped_malformed,
            records_skipped_duplicate,
            error_message,
            ingestion_run_id,
        ),
    )


def write_review_quality(connection: sqlite3.Connection, review_pk: int, row: pd.Series) -> None:
    title = row.get("title")
    review_text = row.get("review_text")
    duplicate_group_key = text_hash(review_text)
    duplicate_count = connection.execute(
        "SELECT COUNT(*) AS count FROM reviews WHERE review_text_hash = ?",
        (duplicate_group_key,),
    ).fetchone()["count"]

    connection.execute(
        """
        INSERT INTO review_quality (
            review_pk, title_length, review_text_length, review_word_count,
            ascii_ratio, has_emoji, is_low_signal, is_duplicate_text,
            duplicate_group_key, missing_required_fields, quality_flags,
            computed_at, quality_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_pk) DO UPDATE SET
            title_length = excluded.title_length,
            review_text_length = excluded.review_text_length,
            review_word_count = excluded.review_word_count,
            ascii_ratio = excluded.ascii_ratio,
            has_emoji = excluded.has_emoji,
            is_low_signal = excluded.is_low_signal,
            is_duplicate_text = excluded.is_duplicate_text,
            duplicate_group_key = excluded.duplicate_group_key,
            missing_required_fields = excluded.missing_required_fields,
            quality_flags = excluded.quality_flags,
            computed_at = excluded.computed_at,
            quality_version = excluded.quality_version
        """,
        (
            review_pk,
            text_length(title),
            text_length(review_text),
            word_count(review_text),
            ascii_ratio(review_text),
            int(has_emoji(title, review_text)),
            int(is_low_signal(review_text)),
            int(duplicate_count > 1),
            duplicate_group_key,
            json.dumps([]),
            json.dumps([]),
            utc_now(),
            QUALITY_VERSION,
        ),
    )


def upsert_review(
    connection: sqlite3.Connection,
    row: pd.Series,
    source_app_id: int,
    ingestion_run_id: str,
) -> tuple[int, bool]:
    now = utc_now()
    source_review_id = str(row["review_id"])
    existing = connection.execute(
        """
        SELECT review_pk, first_seen_at
        FROM reviews
        WHERE source_app_id = ? AND source_review_id = ?
        """,
        (source_app_id, source_review_id),
    ).fetchone()

    if existing is None:
        connection.execute(
            """
            INSERT INTO reviews (
                source_app_id, ingestion_run_id, source_review_id, country,
                author_name, rating, app_version, title, review_text,
                review_text_hash, review_date, source_updated_at, collected_at,
                first_seen_at, last_seen_at, raw_payload, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_app_id,
                ingestion_run_id,
                source_review_id,
                str(row["country"]),
                row.get("author"),
                int(row["rating"]),
                row.get("version"),
                row.get("title"),
                row.get("review_text"),
                text_hash(row.get("review_text")),
                row.get("review_date"),
                row.get("review_date"),
                row.get("collected_at"),
                row.get("collected_at"),
                row.get("collected_at"),
                None,
                now,
                now,
            ),
        )
        review_pk = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        return review_pk, True

    review_pk = int(existing["review_pk"])
    connection.execute(
        """
        UPDATE reviews
        SET ingestion_run_id = ?,
            country = ?,
            author_name = ?,
            rating = ?,
            app_version = ?,
            title = ?,
            review_text = ?,
            review_text_hash = ?,
            review_date = ?,
            source_updated_at = ?,
            collected_at = ?,
            last_seen_at = ?,
            updated_at = ?
        WHERE review_pk = ?
        """,
        (
            ingestion_run_id,
            str(row["country"]),
            row.get("author"),
            int(row["rating"]),
            row.get("version"),
            row.get("title"),
            row.get("review_text"),
            text_hash(row.get("review_text")),
            row.get("review_date"),
            row.get("review_date"),
            row.get("collected_at"),
            row.get("collected_at"),
            now,
            review_pk,
        ),
    )
    return review_pk, False


def write_reviews_to_database(
    reviews: pd.DataFrame,
    summary: pd.DataFrame,
    apps: list[dict[str, str]],
    countries: list[str],
    ingestion_run_id: str,
    db_path: Path = DEFAULT_DB_PATH,
    collector_name: str = "apple_review_collector",
    max_pages_per_country: int = 0,
    delay_seconds: float = 0.0,
) -> DatabaseWriteResult:
    records_inserted = 0
    records_updated = 0
    quality_rows_written = 0
    records_seen = int(len(reviews))
    records_skipped_malformed = 0
    records_skipped_duplicate = 0

    if not summary.empty:
        records_skipped_malformed = int(summary["malformed_skipped"].sum())
        records_skipped_duplicate = int(summary["duplicate_skipped"].sum())
        records_seen += records_skipped_malformed + records_skipped_duplicate

    with connect(db_path) as connection:
        init_apple_review_db(connection)
        source_id = get_or_create_source(connection)
        create_ingestion_run(
            connection=connection,
            ingestion_run_id=ingestion_run_id,
            source_id=source_id,
            collector_name=collector_name,
            requested_apps=[app["app_key"] for app in apps],
            requested_countries=countries,
            max_pages_per_country=max_pages_per_country,
            delay_seconds=delay_seconds,
        )

        source_app_cache: dict[str, int] = {}
        try:
            for _, row in reviews.iterrows():
                app_key = str(row["app_key"])
                external_app_id = str(row["app_id"])
                if external_app_id not in source_app_cache:
                    app_id = get_or_create_app(
                        connection,
                        app_key=app_key,
                        app_name=str(row["app_name"]),
                    )
                    source_app_cache[external_app_id] = get_or_create_source_app(
                        connection=connection,
                        source_id=source_id,
                        app_id=app_id,
                        external_app_id=external_app_id,
                        external_app_name=str(row["app_name"]),
                    )

                review_pk, inserted = upsert_review(
                    connection=connection,
                    row=row,
                    source_app_id=source_app_cache[external_app_id],
                    ingestion_run_id=ingestion_run_id,
                )
                if inserted:
                    records_inserted += 1
                else:
                    records_updated += 1
                write_review_quality(connection, review_pk, row)
                quality_rows_written += 1

            finish_ingestion_run(
                connection=connection,
                ingestion_run_id=ingestion_run_id,
                status="success",
                records_seen=records_seen,
                records_inserted=records_inserted,
                records_updated=records_updated,
                records_skipped_malformed=records_skipped_malformed,
                records_skipped_duplicate=records_skipped_duplicate,
            )
            connection.commit()
        except Exception as exc:
            finish_ingestion_run(
                connection=connection,
                ingestion_run_id=ingestion_run_id,
                status="failed",
                records_seen=records_seen,
                records_inserted=records_inserted,
                records_updated=records_updated,
                records_skipped_malformed=records_skipped_malformed,
                records_skipped_duplicate=records_skipped_duplicate,
                error_message=str(exc),
            )
            connection.commit()
            raise

    return DatabaseWriteResult(
        db_path=db_path,
        ingestion_run_id=ingestion_run_id,
        records_seen=records_seen,
        records_inserted=records_inserted,
        records_updated=records_updated,
        quality_rows_written=quality_rows_written,
    )

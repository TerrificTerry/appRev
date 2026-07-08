from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from collector.apple_store_collector import SOURCE_KEY, SOURCE_NAME
from pipeline.cleaner import ProcessedReview


@dataclass(frozen=True)
class UpsertResult:
    records_seen: int
    records_inserted: int
    records_updated: int
    records_skipped: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return slug.strip("_") or "app"


def get_or_create_source(
    connection: sqlite3.Connection,
    source_key: str = SOURCE_KEY,
    source_name: str = SOURCE_NAME,
) -> int:
    connection.execute(
        """
        INSERT INTO sources (source_key, source_name)
        VALUES (?, ?)
        ON CONFLICT(source_key) DO UPDATE SET source_name = excluded.source_name
        """,
        (source_key, source_name),
    )
    row = connection.execute(
        "SELECT source_id FROM sources WHERE source_key = ?",
        (source_key,),
    ).fetchone()
    return int(row["source_id"])


def get_or_create_app(
    connection: sqlite3.Connection,
    app_key: str,
    canonical_name: str,
    publisher: str | None = None,
    category: str | None = None,
) -> int:
    connection.execute(
        """
        INSERT INTO apps (app_key, canonical_name, publisher, category)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(app_key) DO UPDATE SET
            canonical_name = excluded.canonical_name,
            publisher = COALESCE(excluded.publisher, apps.publisher),
            category = COALESCE(excluded.category, apps.category)
        """,
        (app_key, canonical_name, publisher, category),
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
    store_country: str,
) -> int:
    connection.execute(
        """
        INSERT INTO source_apps (source_id, app_id, external_app_id, store_country)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_id, external_app_id, store_country) DO UPDATE SET
            app_id = excluded.app_id
        """,
        (source_id, app_id, external_app_id, store_country),
    )
    row = connection.execute(
        """
        SELECT source_app_id
        FROM source_apps
        WHERE source_id = ? AND external_app_id = ? AND store_country = ?
        """,
        (source_id, external_app_id, store_country),
    ).fetchone()
    return int(row["source_app_id"])


def create_ingestion_run(connection: sqlite3.Connection, source_id: int) -> int:
    cursor = connection.execute(
        """
        INSERT INTO ingestion_runs (source_id, started_at, status)
        VALUES (?, ?, 'running')
        """,
        (source_id, utc_now()),
    )
    return int(cursor.lastrowid)


def finish_ingestion_run(
    connection: sqlite3.Connection,
    ingestion_run_id: int,
    *,
    status: str,
    records_seen: int,
    records_inserted: int,
    records_updated: int,
    records_skipped: int,
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
            records_skipped = ?,
            error_message = ?
        WHERE ingestion_run_id = ?
        """,
        (
            utc_now(),
            status,
            records_seen,
            records_inserted,
            records_updated,
            records_skipped,
            error_message,
            ingestion_run_id,
        ),
    )


def _material_payload(review: ProcessedReview) -> dict[str, object]:
    return {
        "country": review.country,
        "language_code": review.language_code,
        "author": review.author,
        "rating": review.rating,
        "app_version": review.version,
        "title": review.title,
        "review_text": review.review_text,
        "review_date": review.review_date,
        "review_text_hash": review.review_text_hash,
    }


def _row_differs(row: sqlite3.Row, payload: dict[str, object]) -> bool:
    for field, value in payload.items():
        if row[field] != value:
            return True
    return False


def _write_quality(connection: sqlite3.Connection, review_pk: int, review: ProcessedReview) -> None:
    connection.execute(
        """
        INSERT INTO review_quality (
            review_pk, review_text_length, review_word_count, has_emoji,
            is_low_signal, is_duplicate_text
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_pk) DO UPDATE SET
            review_text_length = excluded.review_text_length,
            review_word_count = excluded.review_word_count,
            has_emoji = excluded.has_emoji,
            is_low_signal = excluded.is_low_signal,
            is_duplicate_text = excluded.is_duplicate_text
        """,
        (
            review_pk,
            review.review_text_length,
            review.review_word_count,
            int(review.has_emoji),
            int(review.is_low_signal),
            int(review.is_duplicate_text),
        ),
    )


def refresh_duplicate_text_flags(connection: sqlite3.Connection) -> None:
    connection.execute("UPDATE review_quality SET is_duplicate_text = 0")
    duplicate_hash_rows = connection.execute(
        """
        SELECT review_text_hash
        FROM reviews
        GROUP BY review_text_hash
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    duplicate_hashes = [row["review_text_hash"] for row in duplicate_hash_rows]
    if not duplicate_hashes:
        return

    placeholders = ",".join("?" for _ in duplicate_hashes)
    connection.execute(
        f"""
        UPDATE review_quality
        SET is_duplicate_text = 1
        WHERE review_pk IN (
            SELECT review_pk
            FROM reviews
            WHERE review_text_hash IN ({placeholders})
        )
        """,
        duplicate_hashes,
    )


def upsert_reviews(
    connection: sqlite3.Connection,
    reviews: list[ProcessedReview],
    *,
    ingestion_run_id: int,
    source_id: int,
) -> UpsertResult:
    inserted = 0
    updated = 0
    skipped = 0
    source_app_cache: dict[tuple[str, str], int] = {}

    for review in reviews:
        app_key = slugify(review.app_name)
        app_pk = get_or_create_app(
            connection,
            app_key=app_key,
            canonical_name=review.app_name,
        )
        source_app_key = (review.app_id, review.country)
        if source_app_key not in source_app_cache:
            source_app_cache[source_app_key] = get_or_create_source_app(
                connection,
                source_id=source_id,
                app_id=app_pk,
                external_app_id=review.app_id,
                store_country=review.country,
            )

        source_app_id = source_app_cache[source_app_key]
        existing = connection.execute(
            """
            SELECT review_pk, country, language_code, author, rating, app_version,
                   title, review_text, review_date, review_text_hash
            FROM reviews
            WHERE source_app_id = ? AND source_review_id = ?
            """,
            (source_app_id, review.review_id),
        ).fetchone()
        payload = _material_payload(review)

        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO reviews (
                    source_app_id, ingestion_run_id, source_review_id, country,
                    language_code, author, rating, app_version, title, review_text,
                    review_date, collected_at, review_text_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_app_id,
                    ingestion_run_id,
                    review.review_id,
                    review.country,
                    review.language_code,
                    review.author,
                    review.rating,
                    review.version,
                    review.title,
                    review.review_text,
                    review.review_date,
                    review.collected_at,
                    review.review_text_hash,
                ),
            )
            review_pk = int(cursor.lastrowid)
            inserted += 1
        else:
            review_pk = int(existing["review_pk"])
            if _row_differs(existing, payload):
                connection.execute(
                    """
                    UPDATE reviews
                    SET ingestion_run_id = ?,
                        country = ?,
                        language_code = ?,
                        author = ?,
                        rating = ?,
                        app_version = ?,
                        title = ?,
                        review_text = ?,
                        review_date = ?,
                        collected_at = ?,
                        review_text_hash = ?
                    WHERE review_pk = ?
                    """,
                    (
                        ingestion_run_id,
                        review.country,
                        review.language_code,
                        review.author,
                        review.rating,
                        review.version,
                        review.title,
                        review.review_text,
                        review.review_date,
                        review.collected_at,
                        review.review_text_hash,
                        review_pk,
                    ),
                )
                updated += 1
            else:
                skipped += 1

        _write_quality(connection, review_pk, review)

    refresh_duplicate_text_flags(connection)
    return UpsertResult(
        records_seen=len(reviews),
        records_inserted=inserted,
        records_updated=updated,
        records_skipped=skipped,
    )


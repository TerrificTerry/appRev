from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pipeline.cleaner import clean_reviews, normalize_text, text_hash
from pipeline.dashboard import load_database_dashboard
from pipeline.run_pipeline import parse_country_codes, run_pipeline, run_pipeline_for_countries
from pipeline.web_gui import _validate_run_config


def sample_reviews() -> list[dict]:
    return [
        {
            "source": "apple_app_store",
            "app_id": "1058959277",
            "app_name": "Uber Eats",
            "country": "us",
            "review_id": "review-1",
            "author": "A Reviewer",
            "rating": 5,
            "version": "6.1",
            "title": " Fast ",
            "review_text": "  Delivery was fast and the driver was kind.  ",
            "review_date": "2026-07-01T12:00:00-07:00",
            "collected_at": "2026-07-08T00:00:00+00:00",
        },
        {
            "source": "apple_app_store",
            "app_id": "1058959277",
            "app_name": "Uber Eats",
            "country": "us",
            "review_id": "review-2",
            "author": "Another Reviewer",
            "rating": 1,
            "version": "6.1",
            "title": "Late",
            "review_text": "Order was late and support did not help.",
            "review_date": "2026-07-02T12:00:00-07:00",
            "collected_at": "2026-07-08T00:00:00+00:00",
        },
    ]


def duplicate_text_reviews() -> list[dict]:
    reviews = sample_reviews()
    reviews[1] = {**reviews[1], "review_text": reviews[0]["review_text"]}
    return reviews


def fake_collector(**_: object) -> list[dict]:
    return sample_reviews()


def fake_duplicate_collector(**_: object) -> list[dict]:
    return duplicate_text_reviews()


def fake_country_collector(**kwargs: object) -> list[dict]:
    country = str(kwargs["country"])
    rows = []
    for row in sample_reviews():
        rows.append({**row, "country": country, "review_id": f"{country}-{row['review_id']}"})
    return rows


class AppleReviewPipelineTests(unittest.TestCase):
    def test_parse_country_codes_accepts_commas_and_deduplicates(self) -> None:
        self.assertEqual(parse_country_codes("US, ca, gb,us"), ["us", "ca", "gb"])

    def test_web_gui_config_accepts_comma_separated_countries(self) -> None:
        config = _validate_run_config(
            {
                "app_id": "1058959277",
                "app_name": "Uber Eats",
                "countries": "us,ca,gb",
                "pages": 1,
                "retries": 3,
                "delay_seconds": 0.25,
                "repeat": 1,
            }
        )

        self.assertEqual(config["countries"], ["us", "ca", "gb"])

    def test_cleaner_preserves_raw_review_text_and_generates_features(self) -> None:
        raw = sample_reviews()[0]
        result = clean_reviews([raw])

        self.assertEqual(result.records_skipped, 0)
        review = result.reviews[0]
        self.assertEqual(review.review_text, raw["review_text"])
        self.assertEqual(review.title, "Fast")
        self.assertEqual(review.review_text_length, len(raw["review_text"].strip()))
        self.assertEqual(review.review_text_hash, text_hash(raw["review_text"]))
        self.assertEqual(normalize_text(review.review_text), "delivery was fast and the driver was kind.")

    def test_pipeline_is_idempotent_for_repeated_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "reviews.sqlite"

            first = run_pipeline(
                app_id="1058959277",
                country="us",
                pages=1,
                db_path=db_path,
                collector=fake_collector,
            )
            second = run_pipeline(
                app_id="1058959277",
                country="us",
                pages=1,
                db_path=db_path,
                collector=fake_collector,
            )

            self.assertEqual(first.records_inserted, 2)
            self.assertEqual(second.records_inserted, 0)
            self.assertEqual(second.records_updated, 0)
            self.assertEqual(second.records_skipped, 2)

            with closing(sqlite3.connect(db_path)) as connection:
                review_count = connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
                run_count = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]
                latest_review_run_id = connection.execute(
                    "SELECT MIN(ingestion_run_id), MAX(ingestion_run_id) FROM reviews"
                ).fetchone()

            self.assertEqual(review_count, 2)
            self.assertEqual(run_count, 2)
            self.assertEqual(latest_review_run_id, (second.ingestion_run_id, second.ingestion_run_id))

    def test_dashboard_recent_reviews_show_latest_seen_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "reviews.sqlite"

            run_pipeline(
                app_id="1058959277",
                country="us",
                pages=1,
                db_path=db_path,
                collector=fake_collector,
            )
            second = run_pipeline(
                app_id="1058959277",
                country="us",
                pages=1,
                db_path=db_path,
                collector=fake_collector,
            )

            dashboard = load_database_dashboard(db_path)

            self.assertTrue(dashboard.recent_reviews)
            self.assertEqual(dashboard.recent_reviews[0].ingestion_run_id, second.ingestion_run_id)

    def test_pipeline_runs_all_comma_separated_countries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "reviews.sqlite"

            summaries = run_pipeline_for_countries(
                app_id="1058959277",
                countries="us,ca",
                pages=1,
                db_path=db_path,
                collector=fake_country_collector,
            )

            self.assertEqual([summary.country for summary in summaries], ["us", "ca"])
            self.assertEqual(sum(summary.records_inserted for summary in summaries), 4)

            with closing(sqlite3.connect(db_path)) as connection:
                review_count = connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
                run_count = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]

            self.assertEqual(review_count, 4)
            self.assertEqual(run_count, 2)

    def test_duplicate_text_quality_flag_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "reviews.sqlite"

            run_pipeline(
                app_id="1058959277",
                country="us",
                pages=1,
                db_path=db_path,
                collector=fake_duplicate_collector,
            )

            with closing(sqlite3.connect(db_path)) as connection:
                duplicate_count = connection.execute(
                    "SELECT SUM(is_duplicate_text) FROM review_quality"
                ).fetchone()[0]

            self.assertEqual(duplicate_count, 2)


if __name__ == "__main__":
    unittest.main()

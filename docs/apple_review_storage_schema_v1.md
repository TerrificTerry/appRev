# Apple Review Storage Schema v1

## Purpose

This schema upgrades Apple App Store review collection from temporary CSV files into a durable data model. It is designed for multi-app, multi-country, multi-source ingestion, while preserving raw review text for future sentiment analysis, topic modeling, language detection, and other NLP tasks.

The v1 model is intentionally normalized around stable entities:

- `sources`: external platforms such as Apple App Store.
- `apps`: canonical internal app records.
- `source_apps`: source-specific app identifiers and metadata.
- `ingestion_runs`: one execution of a collector.
- `reviews`: one review record from one source app.
- `review_quality`: derived data-quality and deduplication signals.
- `review_nlp_annotations`: future NLP outputs, versioned by model/task.

## Design Principles

- Preserve raw source data and raw text.
- Keep app/source identity separate from reviews.
- Make country and language first-class fields.
- Track every ingestion run and collection timestamp.
- Support idempotent upserts by source review identity.
- Add derived quality/NLP fields without mutating raw review content.
- Keep v1 simple enough for SQLite/PostgreSQL, but compatible with larger warehouses later.

## Entity Relationship Summary

```text
sources 1--many source_apps many--1 apps
source_apps 1--many reviews
ingestion_runs 1--many reviews
reviews 1--1 review_quality
reviews 1--many review_nlp_annotations
```

## Tables

### `sources`

Stores external data platforms.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `source_id` | integer pk | yes | Internal key |
| `source_key` | text unique | yes | Example: `apple_app_store` |
| `source_name` | text | yes | Example: `Apple App Store` |
| `base_url` | text | no | Example: `https://itunes.apple.com` |
| `created_at` | timestamp | yes | UTC |
| `updated_at` | timestamp | yes | UTC |

### `apps`

Canonical app/product identity, independent of platform.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `app_id` | integer pk | yes | Internal key |
| `app_key` | text unique | yes | Stable slug, e.g. `uber_eats` |
| `canonical_name` | text | yes | Example: `Uber Eats` |
| `publisher` | text | no | Example: `Uber Technologies, Inc.` |
| `category` | text | no | App category if known |
| `created_at` | timestamp | yes | UTC |
| `updated_at` | timestamp | yes | UTC |

### `source_apps`

Maps an internal app to a source-specific app listing.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `source_app_id` | integer pk | yes | Internal key |
| `source_id` | integer fk | yes | References `sources.source_id` |
| `app_id` | integer fk | yes | References `apps.app_id` |
| `external_app_id` | text | yes | Apple app id, e.g. `1058959277` |
| `external_app_name` | text | yes | Apple listing name |
| `store_country` | text | no | Country used for app resolution, e.g. `us` |
| `app_url` | text | no | App Store URL |
| `is_active` | boolean | yes | Soft-disable source app |
| `created_at` | timestamp | yes | UTC |
| `updated_at` | timestamp | yes | UTC |

Unique constraint:

- (`source_id`, `external_app_id`)

### `ingestion_runs`

Tracks every collector execution.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `ingestion_run_id` | text pk | yes | UUID or timestamp id |
| `source_id` | integer fk | yes | References `sources.source_id` |
| `collector_name` | text | yes | Example: `apple_review_gui` |
| `collector_version` | text | no | Git SHA or semantic version |
| `started_at` | timestamp | yes | UTC |
| `finished_at` | timestamp | no | UTC |
| `status` | text | yes | `running`, `success`, `partial`, `failed` |
| `requested_apps` | json/text | no | App keys or ids requested |
| `requested_countries` | json/text | no | Country codes requested |
| `max_pages_per_country` | integer | no | Collector config |
| `delay_seconds` | real | no | Collector config |
| `records_seen` | integer | yes | Raw candidate count |
| `records_inserted` | integer | yes | New rows |
| `records_updated` | integer | yes | Existing rows updated |
| `records_skipped_malformed` | integer | yes | Parse failures |
| `records_skipped_duplicate` | integer | yes | Dedupe skips |
| `error_message` | text | no | Failure context |
| `created_at` | timestamp | yes | UTC |

### `reviews`

One source review. This is the core fact table.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `review_pk` | integer pk | yes | Internal key |
| `source_app_id` | integer fk | yes | References `source_apps.source_app_id` |
| `ingestion_run_id` | text fk | yes | References `ingestion_runs.ingestion_run_id` |
| `source_review_id` | text | yes | Apple review id |
| `country` | text | yes | Review feed country, e.g. `us` |
| `language_code` | text | no | Detected or source-provided ISO-like code |
| `language_confidence` | real | no | Later language detection confidence |
| `author_name` | text | no | Raw author display name |
| `rating` | integer | yes | Expected 1-5 |
| `app_version` | text | no | Version reported by Apple feed |
| `title` | text | no | Raw title |
| `review_text` | text | yes | Raw review body |
| `review_text_hash` | text | yes | SHA-256 of normalized review text |
| `review_date` | timestamp | yes | Source review timestamp |
| `source_updated_at` | timestamp | no | Source updated timestamp if different |
| `collected_at` | timestamp | yes | When collector saw this row |
| `first_seen_at` | timestamp | yes | First time stored |
| `last_seen_at` | timestamp | yes | Last time observed |
| `raw_payload` | json/text | no | Optional raw source entry |
| `created_at` | timestamp | yes | UTC |
| `updated_at` | timestamp | yes | UTC |

Unique constraint:

- (`source_app_id`, `source_review_id`)

Recommended indexes:

- (`source_app_id`, `country`, `review_date`)
- (`rating`)
- (`app_version`)
- (`review_text_hash`)
- (`language_code`)

### `review_quality`

Derived quality and deduplication signals. Keep this separate from raw review data so quality logic can evolve.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `review_pk` | integer pk/fk | yes | References `reviews.review_pk` |
| `title_length` | integer | yes | Character count |
| `review_text_length` | integer | yes | Character count |
| `review_word_count` | integer | yes | Token-ish word count |
| `ascii_ratio` | real | yes | Useful language/noise proxy |
| `has_emoji` | boolean | yes | Emoji signal |
| `is_low_signal` | boolean | yes | Short/generic/repeated text |
| `is_duplicate_text` | boolean | yes | Duplicate normalized text |
| `duplicate_group_key` | text | no | Hash/key for duplicate clusters |
| `missing_required_fields` | json/text | no | Missingness diagnostics |
| `quality_flags` | json/text | no | Flexible list of flags |
| `computed_at` | timestamp | yes | UTC |
| `quality_version` | text | yes | Example: `quality_v1` |

### `review_nlp_annotations`

Future extension table for sentiment analysis and NLP outputs. Multiple rows per review are allowed so model versions can coexist.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `annotation_id` | integer pk | yes | Internal key |
| `review_pk` | integer fk | yes | References `reviews.review_pk` |
| `task_name` | text | yes | `sentiment`, `topic`, `intent`, etc. |
| `model_name` | text | yes | Model/provider identifier |
| `model_version` | text | no | Version or checkpoint |
| `label` | text | no | Main class label |
| `score` | real | no | Confidence or scalar result |
| `scores_json` | json/text | no | Full score map |
| `annotation_json` | json/text | no | Structured task output |
| `created_at` | timestamp | yes | UTC |

Unique constraint:

- (`review_pk`, `task_name`, `model_name`, `model_version`)

## CSV-to-v1 Mapping

| Current CSV Field | v1 Destination |
|---|---|
| `source` | `sources.source_key` |
| `app_id` | `source_apps.external_app_id` |
| `app_name` | `source_apps.external_app_name`; also maps to `apps.canonical_name` |
| `app_key` | `apps.app_key` |
| `country` | `reviews.country` |
| `review_id` | `reviews.source_review_id` |
| `author` | `reviews.author_name` |
| `rating` | `reviews.rating` |
| `version` | `reviews.app_version` |
| `title` | `reviews.title` |
| `review_text` | `reviews.review_text` |
| `review_date` | `reviews.review_date` |
| `collected_at` | `reviews.collected_at`; initial `first_seen_at` and `last_seen_at` |

## Ingestion Behavior

For every ingestion run:

1. Create an `ingestion_runs` row with `status='running'`.
2. Resolve or create `sources`, `apps`, and `source_apps`.
3. Parse each raw review entry.
4. Skip malformed rows missing source review id, rating, review text, or review date.
5. Compute `review_text_hash` from normalized text.
6. Upsert into `reviews` by (`source_app_id`, `source_review_id`).
7. On insert, set `first_seen_at=collected_at` and `last_seen_at=collected_at`.
8. On repeat observation, update `last_seen_at`, mutable metadata, and `updated_at`.
9. Compute or refresh `review_quality`.
10. Finish `ingestion_runs` with record counts and status.

## Open Decisions For v2

- Whether to store raw Apple JSON payload for every review or only for debug samples.
- Whether language detection should run during ingestion or as a downstream batch job.
- Whether duplicate text should be scoped per app, per country, or globally.
- Whether app metadata history needs slowly changing dimensions.
- Whether to move JSON/text columns to native JSONB in PostgreSQL.


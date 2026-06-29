-- Apple App Store review storage schema v1.
-- SQLite-compatible DDL. JSON fields are stored as TEXT in v1.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL,
    base_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apps (
    app_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key TEXT NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL,
    publisher TEXT,
    category TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_apps (
    source_app_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    app_id INTEGER NOT NULL,
    external_app_id TEXT NOT NULL,
    external_app_name TEXT NOT NULL,
    store_country TEXT,
    app_url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources (source_id),
    FOREIGN KEY (app_id) REFERENCES apps (app_id),
    UNIQUE (source_id, external_app_id)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    ingestion_run_id TEXT PRIMARY KEY,
    source_id INTEGER NOT NULL,
    collector_name TEXT NOT NULL,
    collector_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    requested_apps TEXT,
    requested_countries TEXT,
    max_pages_per_country INTEGER,
    delay_seconds REAL,
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    records_skipped_malformed INTEGER NOT NULL DEFAULT 0,
    records_skipped_duplicate INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources (source_id),
    CHECK (status IN ('running', 'success', 'partial', 'failed'))
);

CREATE TABLE IF NOT EXISTS reviews (
    review_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    source_app_id INTEGER NOT NULL,
    ingestion_run_id TEXT NOT NULL,
    source_review_id TEXT NOT NULL,
    country TEXT NOT NULL,
    language_code TEXT,
    language_confidence REAL,
    author_name TEXT,
    rating INTEGER NOT NULL,
    app_version TEXT,
    title TEXT,
    review_text TEXT NOT NULL,
    review_text_hash TEXT NOT NULL,
    review_date TEXT NOT NULL,
    source_updated_at TEXT,
    collected_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_payload TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_app_id) REFERENCES source_apps (source_app_id),
    FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs (ingestion_run_id),
    UNIQUE (source_app_id, source_review_id),
    CHECK (rating BETWEEN 1 AND 5)
);

CREATE TABLE IF NOT EXISTS review_quality (
    review_pk INTEGER PRIMARY KEY,
    title_length INTEGER NOT NULL,
    review_text_length INTEGER NOT NULL,
    review_word_count INTEGER NOT NULL,
    ascii_ratio REAL NOT NULL,
    has_emoji INTEGER NOT NULL,
    is_low_signal INTEGER NOT NULL,
    is_duplicate_text INTEGER NOT NULL,
    duplicate_group_key TEXT,
    missing_required_fields TEXT,
    quality_flags TEXT,
    computed_at TEXT NOT NULL,
    quality_version TEXT NOT NULL,
    FOREIGN KEY (review_pk) REFERENCES reviews (review_pk) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_nlp_annotations (
    annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_pk INTEGER NOT NULL,
    task_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    label TEXT,
    score REAL,
    scores_json TEXT,
    annotation_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (review_pk) REFERENCES reviews (review_pk) ON DELETE CASCADE,
    UNIQUE (review_pk, task_name, model_name, model_version)
);

CREATE INDEX IF NOT EXISTS idx_source_apps_app_id
    ON source_apps (app_id);

CREATE INDEX IF NOT EXISTS idx_reviews_source_app_country_date
    ON reviews (source_app_id, country, review_date);

CREATE INDEX IF NOT EXISTS idx_reviews_rating
    ON reviews (rating);

CREATE INDEX IF NOT EXISTS idx_reviews_app_version
    ON reviews (app_version);

CREATE INDEX IF NOT EXISTS idx_reviews_text_hash
    ON reviews (review_text_hash);

CREATE INDEX IF NOT EXISTS idx_reviews_language_code
    ON reviews (language_code);

CREATE INDEX IF NOT EXISTS idx_review_quality_low_signal
    ON review_quality (is_low_signal);

CREATE INDEX IF NOT EXISTS idx_nlp_task_model
    ON review_nlp_annotations (task_name, model_name, model_version);


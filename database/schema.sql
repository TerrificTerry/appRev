PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apps (
    app_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key TEXT NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL,
    publisher TEXT,
    category TEXT
);

CREATE TABLE IF NOT EXISTS source_apps (
    source_app_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    app_id INTEGER NOT NULL,
    external_app_id TEXT NOT NULL,
    store_country TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources (source_id),
    FOREIGN KEY (app_id) REFERENCES apps (app_id),
    UNIQUE (source_id, external_app_id, store_country)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    ingestion_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    records_skipped INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (source_id) REFERENCES sources (source_id),
    CHECK (status IN ('running', 'success', 'failed'))
);

CREATE TABLE IF NOT EXISTS reviews (
    review_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    source_app_id INTEGER NOT NULL,
    ingestion_run_id INTEGER NOT NULL,
    source_review_id TEXT NOT NULL,
    country TEXT NOT NULL,
    language_code TEXT,
    author TEXT,
    rating INTEGER NOT NULL,
    app_version TEXT,
    title TEXT,
    review_text TEXT NOT NULL,
    review_date TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    review_text_hash TEXT NOT NULL,
    FOREIGN KEY (source_app_id) REFERENCES source_apps (source_app_id),
    FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs (ingestion_run_id),
    UNIQUE (source_app_id, source_review_id),
    CHECK (rating BETWEEN 1 AND 5)
);

CREATE TABLE IF NOT EXISTS review_quality (
    review_pk INTEGER PRIMARY KEY,
    review_text_length INTEGER NOT NULL,
    review_word_count INTEGER NOT NULL,
    has_emoji INTEGER NOT NULL,
    is_low_signal INTEGER NOT NULL,
    is_duplicate_text INTEGER NOT NULL,
    FOREIGN KEY (review_pk) REFERENCES reviews (review_pk) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_apps_source_external_country
    ON source_apps (source_id, external_app_id, store_country);

CREATE INDEX IF NOT EXISTS idx_reviews_source_identity
    ON reviews (source_app_id, source_review_id);

CREATE INDEX IF NOT EXISTS idx_reviews_country_date
    ON reviews (country, review_date);

CREATE INDEX IF NOT EXISTS idx_reviews_text_hash
    ON reviews (review_text_hash);

CREATE INDEX IF NOT EXISTS idx_review_quality_low_signal
    ON review_quality (is_low_signal);


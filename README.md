# Sciencia Apple App Review Pipeline

A Python pipeline for collecting recent Apple App Store reviews, storing them in a normalized SQLite database, and producing lightweight exploratory data analysis (EDA) reports.

The project supports multi-app and multi-country collection through both a command-line interface and a desktop GUI. It preserves raw review text while keeping collection metadata and derived quality signals separate for future NLP work.

## What It Does

- Collects recent reviews from Apple's public RSS/JSON customer-review feed.
- Supports Uber Eats, DoorDash, and Discord from the CLI; the GUI can resolve other apps by name.
- Collects across configurable App Store countries with request pacing.
- Deduplicates reviews during a collection run.
- Writes combined and per-app CSV files.
- Upserts reviews into a normalized SQLite schema.
- Tracks ingestion runs and derived quality signals such as text length, emoji use, and duplicate text.
- Generates Markdown EDA reports and PNG charts for collected CSV files.

## Repository Layout

```text
.
|-- main.py                         # Primary command-line entry point
|-- acquisition/
|   |-- collect_apple_reviews.py    # Multi-app, multi-country collector
|   |-- apple_review_gui.py         # Desktop collection interface
|   |-- analyze_apple_reviews.py    # EDA reports and charts
|   `-- reader.py                   # Earlier single-app collector prototype
|-- storage/
|   |-- apple_review_store.py       # SQLite persistence and upserts
|   |-- apple_review_schema_v1.sql  # Normalized schema
|   `-- check_apple_review_db.py    # Database inspection utility
|-- docs/
|   `-- apple_review_storage_schema_v1.md
`-- requirements.txt
```

The `structuring/` package and SQLAlchemy-based files in `storage/` are retained from the earlier generic ingestion prototype. The Apple review workflow uses `apple_review_store.py` and the v1 SQL schema directly.

## Requirements

- Python 3.10 or newer
- Internet access for App Store search and review collection
- Tk support only if you want to use the desktop GUI

## Quick Start

Create a fresh virtual environment instead of using a machine-specific environment committed or copied from elsewhere.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Collect Reviews

Run a small collection first:

```powershell
python main.py --apps ubereats --countries us --max-pages-per-country 1
```

The CLI accepts these app keys: `ubereats`, `doordash`, and `discord`.

Collect multiple apps and countries:

```powershell
python main.py `
  --apps ubereats,doordash `
  --countries us,ca,gb `
  --max-pages-per-country 3 `
  --delay-seconds 0.5
```

Use `python main.py --help` for all output-path and database options. Add `--no-db` if you only want CSV output.

By default, generated files are written under `data/apple_review_collection/`:

- `apple_app_reviews.csv`: combined review records
- `apple_app_collection_summary.csv`: collection status by app and country
- `reviews_by_app/`: one CSV per app
- `apple_reviews.sqlite`: normalized SQLite database

## Reusable Ingestion Pipeline

The reusable pipeline modules live in `collector/`, `database/`, and `pipeline/`.
Run a one-app ingestion directly with:

```powershell
python -m pipeline.run_pipeline --app-id 1058959277 --country us --pages 1
```

You can pass multiple storefront countries as comma-separated codes:

```powershell
python -m pipeline.run_pipeline --app-id 1058959277 --country us,ca,gb --pages 1
```

The default SQLite output is `data/apple_review_pipeline/apple_reviews.sqlite`.
Repeated runs are idempotent by `(source_app_id, source_review_id)` and are
tracked in `ingestion_runs`.

Launch the lightweight local web GUI with:

```powershell
.\SCI_new\Scripts\python.exe -m pipeline.web_gui
```

Then open `http://127.0.0.1:8765` in a browser. The Countries field accepts
comma-separated codes such as `us,ca,gb`, and the quick-select list can fill
that field for you. The GUI is a thin wrapper over the same pipeline entry
point; it does not duplicate collector, cleaner, or database logic.
The Recent Reviews table is ordered by the latest ingestion run that observed
each review, so rerunning the same query brings that run's seen reviews back to
the top without duplicating rows.

On Windows you can also run:

```powershell
.\scripts\run_pipeline_web_gui.cmd
```

## Desktop GUI

```powershell
python -m acquisition.apple_review_gui
```

The GUI can search the App Store by app name, collect reviews, write the same CSV and SQLite outputs, and summarize a completed run. If Tkinter is unavailable, install a Python distribution that includes Tk support or use the CLI.

## Analyze a Collection

```powershell
python -m acquisition.analyze_apple_reviews `
  --input data/apple_review_collection/apple_app_reviews.csv `
  --output-dir data/apple_review_collection/analysis
```

The analyzer creates a Markdown summary and PNG charts for rating distribution, review length, country counts, and missingness.

## Inspect the Database

```powershell
python -m storage.check_apple_review_db
```

This prints review counts by app and country, recent ingestion runs, and a quality-signal summary. The complete schema and design rationale are documented in [docs/apple_review_storage_schema_v1.md](docs/apple_review_storage_schema_v1.md).

## Data Model

The v1 schema separates stable entities and derived outputs:

- `sources`: external review platforms
- `apps`: canonical app identities
- `source_apps`: platform-specific app listings
- `ingestion_runs`: collection configuration, status, and record counts
- `reviews`: raw review content and source metadata
- `review_quality`: derived quality and deduplication signals
- `review_nlp_annotations`: reserved for versioned downstream NLP results

Reviews are upserted by source app and source review ID, so rerunning a collection updates existing records instead of duplicating them.

## Important Limitations

- Apple's RSS feed exposes recent reviews; it is not a complete historical archive.
- App availability and returned reviews vary by country storefront.
- The current CLI app list is defined in `acquisition/collect_apple_reviews.py`; use the GUI to resolve arbitrary app names.
- Language and low-signal indicators are heuristics, not production classifiers.
- Generated review data may contain public usernames and free-form text. Keep it out of source control and handle it according to your research or organizational privacy requirements.

## Responsible Use

Use conservative page limits and a nonzero delay between requests. Review Apple's applicable terms before using collected data beyond development or research. Do not treat the feed as guaranteed, exhaustive, or stable without independent validation.

from __future__ import annotations

import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Button, Entry, Frame, Label, Listbox, StringVar, Tk
from tkinter import messagebox, ttk
from typing import Any

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from acquisition.collect_apple_reviews import (
    DEFAULT_COUNTRIES,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_MAX_PAGES_PER_COUNTRY,
    collect_reviews,
    parse_countries,
    save_review_outputs,
)
from acquisition.analyze_apple_reviews import analyze_path
from storage.apple_review_store import DEFAULT_DB_PATH, write_reviews_to_database


RESULTS_ROOT = Path("data/apple_review_collection/gui_runs")
APPLE_SEARCH_URL = "https://itunes.apple.com/search"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "app"


def search_app(term: str, country: str = "us", limit: int = 5) -> list[dict[str, str]]:
    response = requests.get(
        APPLE_SEARCH_URL,
        params={
            "term": term,
            "country": country,
            "entity": "software",
            "limit": limit,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    apps: list[dict[str, str]] = []
    for item in data.get("results", []):
        track_id = item.get("trackId")
        track_name = item.get("trackName")
        if not track_id or not track_name:
            continue

        apps.append(
            {
                "app_key": slugify(track_name),
                "app_id": str(track_id),
                "app_name": str(track_name),
                "app_url": str(item.get("trackViewUrl") or ""),
            }
        )

    return apps


class AppleReviewCollectorGui:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Apple App Store Review Collector")
        self.root.geometry("920x680")

        self.app_terms = StringVar(value="uber eat, doordash, discord")
        self.search_country = StringVar(value="us")
        self.countries = StringVar(value=",".join(DEFAULT_COUNTRIES))
        self.max_pages = StringVar(value=str(DEFAULT_MAX_PAGES_PER_COUNTRY))
        self.delay_seconds = StringVar(value=str(DEFAULT_DELAY_SECONDS))
        self.status = StringVar(value="Ready")
        self.selected_run = StringVar()

        self.resolved_apps: list[dict[str, str]] = []
        self.run_options: list[Path] = []
        self.worker: threading.Thread | None = None
        self.messages: queue.Queue[str] = queue.Queue()
        self.last_run_dir: Path | None = None

        self.build()
        self.root.after(150, self.drain_messages)

    def build(self) -> None:
        outer = Frame(self.root, padx=14, pady=14)
        outer.pack(fill=BOTH, expand=True)

        input_frame = ttk.LabelFrame(outer, text="Collection Inputs", padding=12)
        input_frame.pack(fill="x")

        Label(input_frame, text="App names").grid(row=0, column=0, sticky="w")
        app_entry = Entry(input_frame, textvariable=self.app_terms)
        app_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        Label(input_frame, text="Search country").grid(row=1, column=0, sticky="w", pady=(8, 0))
        Entry(input_frame, textvariable=self.search_country, width=10).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        Label(input_frame, text="Review countries").grid(row=2, column=0, sticky="w", pady=(8, 0))
        Entry(input_frame, textvariable=self.countries).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )

        Label(input_frame, text="Max pages / country").grid(row=3, column=0, sticky="w", pady=(8, 0))
        Entry(input_frame, textvariable=self.max_pages, width=10).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        Label(input_frame, text="Delay seconds").grid(row=4, column=0, sticky="w", pady=(8, 0))
        Entry(input_frame, textvariable=self.delay_seconds, width=10).grid(
            row=4, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        input_frame.columnconfigure(1, weight=1)

        buttons = Frame(outer, pady=10)
        buttons.pack(fill="x")
        Button(buttons, text="Resolve Apps", command=self.resolve_apps).pack(side=LEFT)
        Button(buttons, text="Collect Reviews", command=self.start_collection).pack(side=LEFT, padx=(8, 0))
        Button(buttons, text="Summarize Last Run", command=self.start_summary).pack(side=LEFT, padx=(8, 0))
        Button(buttons, text="Refresh Runs", command=self.refresh_run_choices).pack(side=LEFT, padx=(8, 0))
        Button(buttons, text="Clear Log", command=self.clear_log).pack(side=RIGHT)

        runs_frame = ttk.LabelFrame(outer, text="Run To Summarize", padding=12)
        runs_frame.pack(fill="x")
        self.run_combo = ttk.Combobox(
            runs_frame,
            textvariable=self.selected_run,
            state="readonly",
        )
        self.run_combo.pack(fill="x")
        self.refresh_run_choices()

        resolved_frame = ttk.LabelFrame(outer, text="Resolved Apps", padding=12)
        resolved_frame.pack(fill="x")
        self.resolved_list = Listbox(resolved_frame, height=6)
        self.resolved_list.pack(fill="x")

        log_frame = ttk.LabelFrame(outer, text="Run Log", padding=12)
        log_frame.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.log = Listbox(log_frame)
        self.log.pack(fill=BOTH, expand=True)

        status_bar = Label(outer, textvariable=self.status, anchor="w")
        status_bar.pack(fill="x", pady=(8, 0))

    def log_message(self, message: str) -> None:
        self.messages.put(message)

    def drain_messages(self) -> None:
        while not self.messages.empty():
            message = self.messages.get()
            self.log.insert(END, message)
            self.log.see(END)
            self.status.set(message)

        self.root.after(150, self.drain_messages)

    def clear_log(self) -> None:
        self.log.delete(0, END)

    def app_search_terms(self) -> list[str]:
        return [term.strip() for term in self.app_terms.get().split(",") if term.strip()]

    def resolve_apps(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Collector running", "Please wait for the current task to finish.")
            return

        self.worker = threading.Thread(target=self.resolve_apps_worker, daemon=True)
        self.worker.start()

    def resolve_apps_worker(self) -> None:
        terms = self.app_search_terms()
        if not terms:
            self.log_message("Enter at least one app name.")
            return

        search_country = self.search_country.get().strip().lower() or "us"
        resolved: list[dict[str, str]] = []
        self.log_message(f"Resolving app names in App Store country={search_country}")

        for term in terms:
            try:
                candidates = search_app(term=term, country=search_country, limit=5)
            except requests.RequestException as exc:
                self.log_message(f"{term}: search failed ({exc.__class__.__name__})")
                continue

            if not candidates:
                self.log_message(f"{term}: no app found")
                continue

            app = candidates[0]
            resolved.append(app)
            self.log_message(f"{term}: selected {app['app_name']} / id={app['app_id']}")

        self.resolved_apps = resolved
        self.root.after(0, self.refresh_resolved_list)

    def refresh_resolved_list(self) -> None:
        self.resolved_list.delete(0, END)
        for app in self.resolved_apps:
            self.resolved_list.insert(
                END,
                f"{app['app_name']} | app_id={app['app_id']} | key={app['app_key']}",
            )

    def start_collection(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Collector running", "Please wait for the current task to finish.")
            return

        if not self.resolved_apps:
            self.resolve_apps_worker()
            if not self.resolved_apps:
                return

        self.worker = threading.Thread(target=self.collect_worker, daemon=True)
        self.worker.start()

    def collect_worker(self) -> None:
        try:
            max_pages = int(self.max_pages.get())
            delay = float(self.delay_seconds.get())
            countries = parse_countries(self.countries.get())
        except ValueError:
            self.log_message("Invalid numeric input for max pages or delay.")
            return

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = RESULTS_ROOT / stamp
        reviews_output = run_dir / "apple_app_reviews.csv"
        summary_output = run_dir / "apple_app_collection_summary.csv"
        per_app_output_dir = run_dir / "reviews_by_app"

        self.log_message(
            f"Starting collection: {len(self.resolved_apps)} apps, "
            f"{len(countries)} countries, max_pages={max_pages}"
        )

        start_time = time.monotonic()

        def progress(summary: Any, completed: int, total: int) -> None:
            elapsed = time.monotonic() - start_time
            avg_seconds = elapsed / completed if completed else 0
            remaining_seconds = max(total - completed, 0) * avg_seconds
            eta_minutes = int(remaining_seconds // 60)
            eta_seconds = int(remaining_seconds % 60)
            self.log_message(
                f"[{completed}/{total}] {summary.app_name} / {summary.country}: "
                f"{summary.reviews_collected} reviews, {summary.pages_requested} pages, "
                f"{summary.status}. ETA {eta_minutes:02d}:{eta_seconds:02d}"
            )

        try:
            reviews, summary = collect_reviews(
                apps=self.resolved_apps,
                countries=countries,
                max_pages_per_country=max_pages,
                delay_seconds=delay,
                progress_callback=progress,
            )
        except requests.RequestException as exc:
            self.log_message(f"Collection failed: {exc.__class__.__name__}")
            return
        except Exception as exc:
            self.log_message(f"Collection failed: {exc}")
            return

        per_app_paths = save_review_outputs(
            reviews=reviews,
            summary=summary,
            reviews_output=reviews_output,
            summary_output=summary_output,
            per_app_output_dir=per_app_output_dir,
        )
        try:
            db_result = write_reviews_to_database(
                reviews=reviews,
                summary=summary,
                apps=self.resolved_apps,
                countries=countries,
                ingestion_run_id=stamp,
                db_path=DEFAULT_DB_PATH,
                collector_name="apple_review_gui",
                max_pages_per_country=max_pages,
                delay_seconds=delay,
            )
        except Exception as exc:
            db_result = None
            self.log_message(f"Database write failed: {exc}")

        self.last_run_dir = run_dir
        self.root.after(0, self.refresh_run_choices)

        app_counts = (
            reviews.groupby("app_name").size().sort_values(ascending=False)
            if not reviews.empty
            else pd.Series(dtype=int)
        )
        self.log_message(f"Collected {len(reviews)} reviews")
        for app_name, count in app_counts.items():
            self.log_message(f"{app_name}: {count} reviews")
        self.log_message(f"Saved reviews: {reviews_output}")
        self.log_message(f"Saved summary: {summary_output}")
        for path in per_app_paths:
            self.log_message(f"Saved per-app CSV: {path}")
        if db_result is not None:
            self.log_message(
                f"Saved SQLite DB: {db_result.db_path} "
                f"({db_result.records_inserted} inserted, {db_result.records_updated} updated)"
            )
        self.log_message("Click Summarize Last Run to generate EDA reports and graphs.")

    def start_summary(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Task running", "Please wait for the current task to finish.")
            return

        selected_run = self.selected_run.get().strip()
        if selected_run:
            self.last_run_dir = RESULTS_ROOT / selected_run
        elif self.last_run_dir is None:
            latest_run = self.find_latest_run_dir()
            if latest_run is None:
                self.log_message("No run folder found to summarize.")
                return
            self.last_run_dir = latest_run

        self.worker = threading.Thread(target=self.summary_worker, daemon=True)
        self.worker.start()

    def refresh_run_choices(self) -> None:
        if not hasattr(self, "run_combo"):
            return

        if not RESULTS_ROOT.exists():
            self.run_options = []
            self.run_combo["values"] = []
            self.selected_run.set("")
            return

        self.run_options = sorted(
            [path for path in RESULTS_ROOT.iterdir() if path.is_dir()],
            reverse=True,
        )
        values = [path.name for path in self.run_options]
        self.run_combo["values"] = values

        if values and not self.selected_run.get():
            self.selected_run.set(values[0])

    def find_latest_run_dir(self) -> Path | None:
        if not RESULTS_ROOT.exists():
            return None

        run_dirs = [path for path in RESULTS_ROOT.iterdir() if path.is_dir()]
        if not run_dirs:
            return None

        return sorted(run_dirs)[-1]

    def summary_worker(self) -> None:
        if self.last_run_dir is None:
            self.log_message("No run folder found to summarize.")
            return

        output_dir = self.last_run_dir / "eda"
        self.log_message(f"Summarizing run: {self.last_run_dir}")
        try:
            report_paths = analyze_path(self.last_run_dir, output_dir)
        except Exception as exc:
            self.log_message(f"Summary failed: {exc}")
            return

        if not report_paths:
            self.log_message("No review CSV files found for summary.")
            return

        self.log_message(f"Generated {len(report_paths)} EDA report(s)")
        for path in report_paths:
            self.log_message(f"Saved EDA report: {path}")


def main() -> None:
    root = Tk()
    root.lift()
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))
    AppleReviewCollectorGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import html as html_lib
import json
import sys
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.db import DEFAULT_DB_PATH
from pipeline.dashboard import load_database_dashboard
from pipeline.run_pipeline import parse_country_codes, run_pipeline


RUN_STATE = {
    "running": False,
    "status": "Ready",
    "log": [],
    "summaries": [],
}
RUN_LOCK = threading.Lock()


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Apple Review Pipeline</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1d2430;
      --muted: #667085;
      --line: #d7dce3;
      --accent: #176b87;
      --accent-strong: #0f4c64;
      --warn: #946200;
      --error: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
    }
    header {
      padding: 18px 24px;
      background: #1f2937;
      color: white;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 650;
    }
    main {
      padding: 18px 24px 24px;
      max-width: 1280px;
      margin: 0 auto;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px;
      margin-bottom: 14px;
    }
    h2 {
      margin: 0 0 12px;
      font-size: 15px;
      font-weight: 650;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 5px;
    }
    input,
    select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 7px 9px;
      color: var(--text);
      background: white;
    }
    input { min-height: 36px; }
    select { min-height: 108px; }
    .wide { grid-column: span 2; }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    button {
      min-height: 36px;
      border: 1px solid var(--accent);
      border-radius: 4px;
      padding: 7px 12px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      font-weight: 600;
    }
    button.secondary {
      background: white;
      color: var(--accent-strong);
    }
    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 10px;
      min-height: 70px;
      background: #fbfcfe;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 7px;
    }
    .metric strong {
      display: block;
      font-size: 19px;
    }
    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 8px 7px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      background: #fbfcfe;
    }
    pre {
      margin: 0;
      min-height: 180px;
      max-height: 320px;
      overflow: auto;
      white-space: pre-wrap;
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 10px;
      background: #101828;
      color: #e4e7ec;
    }
    .status {
      font-weight: 650;
      color: white;
      background: rgba(255,255,255,.14);
      padding: 6px 10px;
      border-radius: 4px;
    }
    .error { color: var(--error); }
    @media (max-width: 900px) {
      .grid, .metrics, .split { grid-template-columns: 1fr; }
      .wide { grid-column: span 1; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Apple Review Pipeline</h1>
    <div class="status" id="status">Ready</div>
  </header>
  <main>
    <section>
      <h2>Controls</h2>
      <div class="grid">
        <div>
          <label for="app_id">Apple app id</label>
          <input id="app_id" value="1058959277">
        </div>
        <div>
          <label for="app_name">App name</label>
          <input id="app_name" value="Uber Eats">
        </div>
        <div>
          <label for="country">Countries</label>
          <input id="country" value="us">
        </div>
        <div>
          <label for="pages">Pages</label>
          <input id="pages" type="number" min="1" value="1">
        </div>
        <div>
          <label for="retries">Retries</label>
          <input id="retries" type="number" min="0" value="3">
        </div>
        <div>
          <label for="delay_seconds">Delay seconds</label>
          <input id="delay_seconds" type="number" min="0" step="0.05" value="0.25">
        </div>
        <div class="wide">
          <label for="db_path">SQLite database</label>
          <input id="db_path" value="__DEFAULT_DB_PATH__">
        </div>
        <div class="wide">
          <label for="country_select">Country quick select</label>
          <select id="country_select" multiple>
            <option value="us" selected>US - United States</option>
            <option value="ca">CA - Canada</option>
            <option value="gb">GB - United Kingdom</option>
            <option value="au">AU - Australia</option>
            <option value="nz">NZ - New Zealand</option>
            <option value="ie">IE - Ireland</option>
            <option value="de">DE - Germany</option>
            <option value="fr">FR - France</option>
            <option value="es">ES - Spain</option>
            <option value="it">IT - Italy</option>
            <option value="nl">NL - Netherlands</option>
            <option value="be">BE - Belgium</option>
            <option value="ch">CH - Switzerland</option>
            <option value="mx">MX - Mexico</option>
            <option value="br">BR - Brazil</option>
            <option value="jp">JP - Japan</option>
            <option value="tw">TW - Taiwan</option>
            <option value="hk">HK - Hong Kong</option>
            <option value="sg">SG - Singapore</option>
            <option value="za">ZA - South Africa</option>
          </select>
        </div>
      </div>
      <div class="actions">
        <button id="run_once">Run Once</button>
        <button id="run_twice">Run Twice / Idempotency Test</button>
        <button class="secondary" id="refresh">Refresh Dashboard</button>
        <button class="secondary" id="clear_log">Clear Log</button>
      </div>
    </section>

    <section>
      <h2>Database</h2>
      <div class="metrics">
        <div class="metric"><span>Reviews</span><strong id="m_reviews">0</strong></div>
        <div class="metric"><span>Runs</span><strong id="m_runs">0</strong></div>
        <div class="metric"><span>Apps</span><strong id="m_apps">0</strong></div>
        <div class="metric"><span>Average rating</span><strong id="m_rating">0</strong></div>
        <div class="metric"><span>Low signal</span><strong id="m_low">0</strong></div>
        <div class="metric"><span>Duplicate text</span><strong id="m_dup">0</strong></div>
      </div>
    </section>

    <div class="split">
      <section>
        <h2>Recent Runs</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Status</th><th>Seen</th><th>Inserted</th><th>Updated</th><th>Skipped</th></tr>
          </thead>
          <tbody id="runs_body"></tbody>
        </table>
      </section>
      <section>
        <h2>Recent Reviews</h2>
        <table>
          <thead>
            <tr><th>Run ID</th><th>App</th><th>Country</th><th>Rating</th><th>Title</th></tr>
          </thead>
          <tbody id="reviews_body"></tbody>
        </table>
      </section>
    </div>

    <section>
      <h2>Run Log</h2>
      <pre id="log"></pre>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const fields = ["app_id", "app_name", "country", "country_select", "pages", "retries", "delay_seconds", "db_path"];

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function payload(repeat) {
      return {
        app_id: $("app_id").value.trim(),
        app_name: $("app_name").value.trim(),
        countries: $("country").value.trim(),
        pages: Number($("pages").value),
        retries: Number($("retries").value),
        delay_seconds: Number($("delay_seconds").value),
        db_path: $("db_path").value.trim(),
        repeat
      };
    }

    function setRunning(running) {
      $("run_once").disabled = running;
      $("run_twice").disabled = running;
      fields.forEach((id) => $(id).disabled = running);
    }

    async function api(path, options = {}) {
      const response = await fetch(path, options);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || response.statusText);
      return body;
    }

    async function startRun(repeat) {
      try {
        await api("/api/run", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload(repeat))
        });
        await refreshStatus();
      } catch (err) {
        $("status").textContent = "Error";
        $("log").textContent += "\\n" + err.message;
      }
    }

    async function refreshDashboard() {
      const params = new URLSearchParams({db_path: $("db_path").value.trim()});
      const data = await api("/api/dashboard?" + params.toString());
      $("m_reviews").textContent = data.total_reviews;
      $("m_runs").textContent = data.total_runs;
      $("m_apps").textContent = data.total_apps;
      $("m_rating").textContent = data.average_rating;
      $("m_low").textContent = data.low_signal_reviews;
      $("m_dup").textContent = data.duplicate_text_reviews;

      $("runs_body").innerHTML = data.recent_runs.map((run) =>
        `<tr><td>${run.ingestion_run_id}</td><td>${escapeHtml(run.status)}</td><td>${run.records_seen}</td><td>${run.records_inserted}</td><td>${run.records_updated}</td><td>${run.records_skipped}</td></tr>`
      ).join("");
      $("reviews_body").innerHTML = data.recent_reviews.map((review) =>
        `<tr><td>${review.ingestion_run_id}</td><td>${escapeHtml(review.app_name)}</td><td>${escapeHtml(review.country)}</td><td>${review.rating}</td><td>${escapeHtml(review.title || "")}</td></tr>`
      ).join("");
    }

    async function refreshStatus() {
      const state = await api("/api/status");
      $("status").textContent = state.status;
      $("log").textContent = state.log.join("\\n");
      $("log").scrollTop = $("log").scrollHeight;
      setRunning(state.running);
      await refreshDashboard();
    }

    $("run_once").addEventListener("click", () => startRun(1));
    $("run_twice").addEventListener("click", () => startRun(2));
    $("country_select").addEventListener("change", () => {
      const selected = Array.from($("country_select").selectedOptions).map((option) => option.value);
      if (selected.length) $("country").value = selected.join(",");
    });
    $("refresh").addEventListener("click", refreshStatus);
    $("clear_log").addEventListener("click", async () => {
      await api("/api/clear-log", {method: "POST"});
      await refreshStatus();
    });

    refreshStatus();
    setInterval(refreshStatus, 1500);
  </script>
</body>
</html>
"""


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _html_response(handler: BaseHTTPRequestHandler) -> None:
    html = HTML.replace("__DEFAULT_DB_PATH__", html_lib.escape(str(DEFAULT_DB_PATH), quote=True))
    encoded = html.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _state_snapshot() -> dict:
    with RUN_LOCK:
        return {
            "running": RUN_STATE["running"],
            "status": RUN_STATE["status"],
            "log": list(RUN_STATE["log"]),
            "summaries": list(RUN_STATE["summaries"]),
        }


def _append_log(message: str) -> None:
    with RUN_LOCK:
        RUN_STATE["log"].append(message)
        RUN_STATE["status"] = message


def _run_worker(config: dict) -> None:
    repeat = int(config["repeat"])
    countries = list(config["countries"])
    summaries: list[dict] = []

    try:
        _append_log(
            f"Starting pipeline: app_id={config['app_id']}, countries={','.join(countries)}, "
            f"pages={config['pages']}, repeat={repeat}"
        )
        for run_number in range(1, repeat + 1):
            for country in countries:
                started = time.monotonic()
                summary = run_pipeline(
                    app_id=config["app_id"],
                    country=country,
                    pages=int(config["pages"]),
                    app_name=config.get("app_name") or None,
                    db_path=Path(config["db_path"]),
                    retries=int(config["retries"]),
                    delay_seconds=float(config["delay_seconds"]),
                )
                elapsed = time.monotonic() - started
                summary_dict = asdict(summary)
                summary_dict["database_path"] = str(summary.database_path)
                summaries.append(summary_dict)
                _append_log(
                    " | ".join(
                        [
                            f"Run {run_number}/{repeat}",
                            f"country={country}",
                            f"id={summary.ingestion_run_id}",
                            f"status={summary.status}",
                            f"collected={summary.records_collected}",
                            f"inserted={summary.records_inserted}",
                            f"updated={summary.records_updated}",
                            f"skipped={summary.records_skipped}",
                            f"elapsed={elapsed:.1f}s",
                        ]
                    )
                )

        if repeat == 2:
            _append_log("Idempotency check complete. On unchanged data, the second run should have inserted=0.")

        with RUN_LOCK:
            RUN_STATE["summaries"] = summaries
            RUN_STATE["status"] = "Complete"
    except Exception as exc:
        _append_log(f"Run failed: {exc}")
    finally:
        with RUN_LOCK:
            RUN_STATE["running"] = False


def _validate_run_config(config: dict) -> dict:
    app_id = str(config.get("app_id", "")).strip()
    app_name = str(config.get("app_name", "")).strip()
    raw_countries = str(config.get("countries") or config.get("country", "")).strip().lower()
    countries = parse_country_codes(raw_countries)
    db_path = str(config.get("db_path", "")).strip() or str(DEFAULT_DB_PATH)
    pages = int(config.get("pages", 1))
    retries = int(config.get("retries", 3))
    delay_seconds = float(config.get("delay_seconds", 0.25))
    repeat = int(config.get("repeat", 1))

    if not app_id:
        raise ValueError("Apple app id is required.")
    if pages < 1:
        raise ValueError("Pages must be at least 1.")
    if retries < 0:
        raise ValueError("Retries cannot be negative.")
    if delay_seconds < 0:
        raise ValueError("Delay seconds cannot be negative.")
    if repeat not in {1, 2}:
        raise ValueError("Repeat must be 1 or 2.")

    return {
        "app_id": app_id,
        "app_name": app_name,
        "countries": countries,
        "pages": pages,
        "retries": retries,
        "delay_seconds": delay_seconds,
        "db_path": db_path,
        "repeat": repeat,
    }


class PipelineGuiHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            _html_response(self)
            return
        if parsed.path == "/api/status":
            _json_response(self, HTTPStatus.OK, _state_snapshot())
            return
        if parsed.path == "/api/dashboard":
            query = parse_qs(parsed.query)
            db_path = query.get("db_path", [str(DEFAULT_DB_PATH)])[0] or str(DEFAULT_DB_PATH)
            try:
                dashboard = load_database_dashboard(Path(db_path))
            except Exception as exc:
                _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            payload = asdict(dashboard)
            payload["database_path"] = str(dashboard.database_path)
            _json_response(self, HTTPStatus.OK, payload)
            return

        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/clear-log":
            with RUN_LOCK:
                RUN_STATE["log"] = []
                RUN_STATE["status"] = "Ready"
            _json_response(self, HTTPStatus.OK, _state_snapshot())
            return

        if parsed.path != "/api/run":
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            raw_body = self.rfile.read(length).decode("utf-8")
            config = _validate_run_config(json.loads(raw_body or "{}"))
        except Exception as exc:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        with RUN_LOCK:
            if RUN_STATE["running"]:
                _json_response(self, HTTPStatus.CONFLICT, {"error": "Pipeline is already running."})
                return
            RUN_STATE["running"] = True
            RUN_STATE["status"] = "Starting"
            RUN_STATE["log"] = []
            RUN_STATE["summaries"] = []

        worker = threading.Thread(target=_run_worker, args=(config,), daemon=True)
        worker.start()
        _json_response(self, HTTPStatus.ACCEPTED, _state_snapshot())

    def log_message(self, format: str, *args: object) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local web GUI for the Apple review pipeline.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="Import-check the web GUI without starting the server.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.check:
        print("Apple review pipeline web GUI import check OK")
        return

    server = ThreadingHTTPServer((args.host, args.port), PipelineGuiHandler)
    print(f"Apple review pipeline GUI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

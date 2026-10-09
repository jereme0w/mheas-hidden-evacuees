"""Merged Riverford reporting API: python backend/app.py --seed-demo.

The fictional scenario uses a fixed demo snapshot. Real receipt timestamps are
stored separately. Regional expectations are learned; report priority is a
paper-aligned weighted priority model. This app writes riverford_reports.sqlite3.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
from uuid import uuid4

from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from contextual_prioritisation_model import load_reporting_model
from riverford_service import assess, demo_records, load_scenario, parse_time, score_record, normalise_report as _normalise

PROJECT_DIR = Path(__file__).resolve().parents[1]
TABLE = "riverford_reports"
APP_VERSION = "riverford-paper-aligned-2026-10-10.1"


def _connection(database):
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=3)
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS riverford_reports (
            report_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, region_id TEXT NOT NULL,
            household_id TEXT NOT NULL, submitted_at TEXT NOT NULL, created_at TEXT NOT NULL,
            record_json TEXT NOT NULL)""")
        connection.execute("CREATE INDEX IF NOT EXISTS riverford_event ON riverford_reports(event_id)")
    except BaseException:
        connection.close()
        raise
    return connection


def _records(connection, event_id):
    return [json.loads(row[0]) for row in connection.execute(
        "SELECT record_json FROM riverford_reports WHERE event_id=? ORDER BY created_at, report_id", (event_id,))]


def _insert(connection, record, ignore=False):
    verb = "INSERT OR IGNORE" if ignore else "INSERT"
    connection.execute(f"{verb} INTO riverford_reports VALUES (?,?,?,?,?,?,?)", (
        record["report_id"], record["event_id"], record["region_id"], record["household_id"],
        record["submitted_at"], record["created_at"], json.dumps(record, allow_nan=False)))


def _save_report(database, record, scenario, model):
    """Save report and its regional result in one transaction before success."""
    with closing(_connection(database)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _insert(connection, record)
            snapshot = assess(scenario, model, _records(connection, record["event_id"]))
            region = next(row for row in snapshot["area_information_gaps"] if row["region_id"] == record["region_id"])
            record["regional_assessment"] = region
            connection.execute("UPDATE riverford_reports SET record_json=? WHERE report_id=?",
                               (json.dumps(record, allow_nan=False), record["report_id"]))
    return snapshot


def seed_demo(app):
    """Insert scored demo reports; upgrade only matching legacy count fixtures."""
    scenario = app.extensions["riverford_scenario"]
    model = app.extensions["riverford_model"]
    incoming = demo_records(scenario)  # Validate all inputs before touching storage.
    with closing(_connection(app.config["DATABASE"])) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = []
            for record in incoming:
                previous = connection.execute(
                    "SELECT record_json FROM riverford_reports WHERE report_id=?",
                    (record["report_id"],)).fetchone()
                if previous is None:
                    _insert(connection, record)
                elif json.loads(previous[0]).get("source") == "synthetic_count_fixture":
                    connection.execute("UPDATE riverford_reports SET record_json=? WHERE report_id=?",
                                       (json.dumps(record, allow_nan=False), record["report_id"]))
                else:
                    continue  # Preserve form submissions and already-scored demo records.
                changed.append(record)
            if changed:
                snapshot = assess(scenario, model, _records(connection, scenario["event"]["event_id"]))
                regions = {row["region_id"]: row for row in snapshot["area_information_gaps"]}
                for record in changed:
                    record["regional_assessment"] = regions[record["region_id"]]
                    connection.execute("UPDATE riverford_reports SET record_json=? WHERE report_id=?",
                                       (json.dumps(record, allow_nan=False), record["report_id"]))


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        MAX_CONTENT_LENGTH=64*1024,
        DATABASE=os.environ.get("CS789_DATABASE", str(PROJECT_DIR / "data" / "riverford_reports.sqlite3")),
        FORM_PATH=str(PROJECT_DIR / "frontend" / "evac_form.html"),
        DATASET_DIR=os.environ.get("CS789_DATASET_DIR", str(PROJECT_DIR / "datasets" / "riverford")),
        MODEL_PATH=str(PROJECT_DIR / "models" / "regional_model.json"),
    )
    if config:
        app.config.update(config)
    scenario = load_scenario(app.config["DATASET_DIR"])
    model = load_reporting_model(app.config["MODEL_PATH"])
    app.extensions["riverford_scenario"] = scenario
    app.extensions["riverford_model"] = model

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(status="error", error=error.description), error.code

    @app.get("/")
    def form():
        return send_file(Path(app.config["FORM_PATH"]).resolve())

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/version")
    def version():
        return jsonify(application="riverford", version=APP_VERSION, regions_url="/api/regions", dashboard_url="/dashboard")

    @app.get("/form.js")
    def form_script():
        return send_file(PROJECT_DIR / "frontend" / "form.js", mimetype="text/javascript")

    @app.get("/dashboard")
    def dashboard_page():
        return send_file(PROJECT_DIR / "frontend" / "dashboard.html")

    @app.get("/dashboard.js")
    def dashboard_script():
        return send_file(PROJECT_DIR / "frontend" / "dashboard.js", mimetype="text/javascript")

    @app.get("/dashboard.css")
    def dashboard_styles():
        return send_file(PROJECT_DIR / "frontend" / "dashboard.css", mimetype="text/css")

    @app.get("/api/dashboard")
    def dashboard_data():
        try:
            with closing(_connection(app.config["DATABASE"])) as connection:
                records = _records(connection, scenario["event"]["event_id"])
            start = parse_time(scenario["event"]["earthquake_at"])
            records = [row for row in records if start <= parse_time(row["submitted_at"]) <= scenario["snapshot_at"]]
            snapshot = assess(scenario, model, records)
            for row in snapshot["area_information_gaps"]:
                context = scenario["contexts"][row["region_id"]]
                row["context"] = {"population": context.estimated_people_present,
                    "occupied_households": context.occupied_households,
                    "shaking_intensity": context.shaking_intensity,
                    "damage_level": context.damage_level,
                    "infrastructure": context.infrastructure, "communications": context.communications,
                    "report_feed_complete": context.report_feed_complete,
                    "reporting_participation": context.reporting_participation}
            snapshot["reports"] = records
            snapshot["submission_count"] = len(records)
            snapshot["fixture_submission_count"] = sum(row["source"] == "synthetic_count_fixture" for row in records)
            snapshot["demo_submission_count"] = sum(row["source"] == "synthetic_community_report" for row in records)
            snapshot["application_version"] = APP_VERSION
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
            return jsonify(status="error", error="Dashboard data unavailable. Report counts are unknown until the feed is available."), 503
        return jsonify(snapshot)

    @app.get("/api/context")
    def context():
        return jsonify(event_id=scenario["event"]["event_id"], clock_mode=scenario["event"]["clock_mode"],
                       hours_since_earthquake=scenario["event"]["hours_since_earthquake"],
                       assessment_time=scenario["snapshot_at"].isoformat(),
                       regions=[{"region_id": key, "region_name": scenario["names"][key],
                                 "occupied_households": row.occupied_households,
                                 "estimated_people_present": row.estimated_people_present}
                                for key, row in scenario["contexts"].items()])

    @app.get("/api/regions")
    def regions():
        try:
            with closing(_connection(app.config["DATABASE"])) as connection:
                snapshot = assess(scenario, model, _records(connection, scenario["event"]["event_id"]))
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
            return jsonify(status="error", error="Regional assessment unavailable; the report feed cannot be treated as empty."), 503
        return jsonify(snapshot)

    @app.get("/api/reports")
    def reports():
        try:
            with closing(_connection(app.config["DATABASE"])) as connection:
                rows = _records(connection, scenario["event"]["event_id"])
            return jsonify(event_id=scenario["event"]["event_id"], count=len(rows), reports=rows)
        except (sqlite3.Error, OSError, ValueError):
            return jsonify(status="error", error="Report storage unavailable"), 503

    @app.get("/api/reports/<report_id>")
    def report_details(report_id):
        try:
            with closing(_connection(app.config["DATABASE"])) as connection:
                row = connection.execute("SELECT record_json FROM riverford_reports WHERE report_id=? AND event_id=?",
                                         (report_id, scenario["event"]["event_id"])).fetchone()
            if row is None:
                return jsonify(status="error", error="Report not found"), 404
            return jsonify(json.loads(row[0]))
        except (sqlite3.Error, OSError, ValueError):
            return jsonify(status="error", error="Report storage unavailable"), 503

    @app.post("/api/reports")
    def submit_report():
        if request.is_json:
            payload = request.get_json()
            if not isinstance(payload, dict):
                return jsonify(status="error", error="JSON body must be an object"), 400
        elif request.mimetype in ("application/x-www-form-urlencoded", "multipart/form-data"):
            if any(file.filename for file in request.files.values()):
                return jsonify(status="error", error="Uploads are not supported"), 422
            payload = {}
            for key in request.form:
                values = request.form.getlist(key)
                if key in ("needs", "primary_needs", "high_risk_vulnerabilities"):
                    payload[key] = values
                elif len(values) == 1:
                    payload[key] = values[0]
                else:
                    return jsonify(status="error", error=f"{key} must have one value"), 422
        else:
            return jsonify(status="error", error="Use JSON or form data"), 415
        try:
            json.dumps(payload, allow_nan=False)
            values = _normalise(payload, scenario)
            record = {"report_id": str(uuid4()), "event_id": scenario["event"]["event_id"],
                      "region_id": values["region_id"], "household_id": values["household_id"],
                      "created_at": datetime.now(timezone.utc).isoformat(),
                      "submitted_at": scenario["snapshot_at"].isoformat(),
                      "clock_mode": scenario["event"]["clock_mode"],
                      "source": "fictional_community_form", "verification_status": "unverified",
                      "original_report": payload, "model_report": values,
                      "context": {"source": "fictional_backend_datasets", "context_version": scenario["event"]["context_version"]}}
            record["priority"] = score_record(scenario, record)
        except (ValueError, TypeError, OverflowError) as error:
            return jsonify(status="error", error=str(error)), 422
        try:
            snapshot = _save_report(app.config["DATABASE"], record, scenario, model)
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
            app.logger.error("Report transaction failed")
            return jsonify(status="error", error="Could not save the report. Your answers are still available; retry."), 503
        return jsonify(status="received", report_id=record["report_id"], created_at=record["created_at"],
                       priority=record["priority"], regional_assessment=record["regional_assessment"],
                       regional_alert_count=snapshot["alert_count"]), 201

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app


app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-demo", action="store_true", help="Insert 65 scored fictional reports and upgrade legacy count fixtures")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(.2)
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            parser.error(f"Port {args.port} already has a server. Stop that server or choose another --port, such as 5001 or 5002.")
    if args.seed_demo:
        seed_demo(app)
    print(f"Riverford fictional snapshot: {app.extensions['riverford_scenario']['event']['hours_since_earthquake']} hours after the earthquake")
    print(f"Reports database: {app.config['DATABASE']}")
    print(f"Application version: {APP_VERSION}")
    print(f"Backend file: {Path(__file__).resolve()}")
    print(f"Regions: http://127.0.0.1:{args.port}/api/regions")
    print(f"Dashboard: http://127.0.0.1:{args.port}/dashboard")
    app.run(host="127.0.0.1", port=args.port, debug=False)

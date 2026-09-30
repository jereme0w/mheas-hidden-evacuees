"""Translate fictional Riverford datasets and stored reports into model inputs."""
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from contextual_prioritisation_model import (
    AreaContext, CommunityReport, evaluate_city_snapshot, prioritise_report, NEED_SCORES,
)
from demo_regions import load_regions


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Scenario timestamps must include a timezone")
    return parsed


def load_scenario(directory):
    directory = Path(directory)
    event = json.loads((directory / "city_context.json").read_text(encoding="utf-8"))
    if event.get("clock_mode") != "fixed_demo_snapshot":
        raise ValueError("This prototype requires clock_mode=fixed_demo_snapshot")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("Scenario requires a non-empty event_id")
    hours = event["hours_since_earthquake"]
    if isinstance(hours, bool) or not isinstance(hours, (float, int)) or not math.isfinite(hours) or hours < 0:
        raise ValueError("Invalid scenario hours_since_earthquake")
    earthquake_at = parse_time(event["earthquake_at"])
    snapshot_at = earthquake_at + timedelta(hours=hours)
    rows = load_regions(directory)
    contexts = {}
    for row in rows:
        mmi = row["shaking_intensity"]
        shaking = "Severe" if mmi >= 8 else "Strong" if mmi >= 7 else "Moderate" if mmi >= 5 else "Light"
        contexts[row["region_id"]] = AreaContext(
            district=row["region_id"], estimated_people_present=row["fictional_population"],
            occupied_households=row["occupied_households"], shaking=shaking,
            shaking_intensity=mmi, damage_level=row["damage_level"],
            infrastructure=row["infrastructure_status"], communications=row["communications_status"],
            reporting_participation=row["reporting_participation"], earthquake_at=earthquake_at,
            assessed_at=snapshot_at, report_feed_complete=row["report_feed_complete"],
            context_version=event["context_version"],
        )
    return {"event": event, "snapshot_at": snapshot_at, "contexts": contexts,
            "names": {row["region_id"]: row["region_name"] for row in rows},
            "directory": directory}


def community_report(record):
    values = record["model_report"]
    return CommunityReport(
        report_id=record["report_id"], district=record["region_id"],
        household_id=record["household_id"], submitted_at=parse_time(record["submitted_at"]),
        people_affected=values["people_affected"], immediate_danger=values["immediate_danger"],
        urgency=values["urgency"], needs=values["needs"],
        shelter_status=values["shelter_status"], responder_access=values["responder_access"],
    )


def assess(scenario, model, records):
    snapshot = evaluate_city_snapshot(list(scenario["contexts"].values()),
                                      [community_report(record) for record in records],
                                      scenario["snapshot_at"], model)
    # Return the regional assessment separately from individual priorities.
    gaps = snapshot["area_information_gaps"]
    for gap in gaps:
        gap["region_name"] = scenario["names"][gap["region_id"]]
    return {"event_id": scenario["event"]["event_id"],
            "clock_mode": scenario["event"]["clock_mode"],
            "assessment_time": snapshot["assessment_time"],
            "hours_since_earthquake": scenario["event"]["hours_since_earthquake"],
            "area_information_gaps": gaps,
            "alert_count": sum(gap["alert"] for gap in gaps)}


def score_record(scenario, record):
    return prioritise_report(community_report(record), scenario["contexts"][record["region_id"]])


def _integer(value, name, minimum=0, maximum=None):
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be an integer from {minimum}" + (f" to {maximum}" if maximum is not None else ""))
    return value


def normalise_report(payload, scenario):
    allowed = {"region_id", "household_number", "reporter_type", "people_affected", "immediate_danger",
               "self_reported_urgency", "urgency", "primary_needs", "needs", "shelter_status", "responder_access"}
    unknown = sorted(set(payload)-allowed)
    if unknown:
        raise ValueError("Unsupported fields: " + ", ".join(unknown))
    region_id = payload.get("region_id")
    if not isinstance(region_id, str) or region_id not in scenario["contexts"]:
        raise ValueError("Choose a known Riverford region_id")
    context = scenario["contexts"][region_id]
    household_number = _integer(payload.get("household_number"), "household_number", 1, context.occupied_households)
    if "needs" in payload and "primary_needs" in payload:
        raise ValueError("Provide needs or primary_needs, not both")
    needs = payload.get("primary_needs", payload.get("needs"))
    if not isinstance(needs, list) or not needs or any(not isinstance(value, str) for value in needs):
        raise ValueError("Select at least one need; needs must be a list")
    needs = list(dict.fromkeys(value.strip().lower().replace("rescue_evacuation", "rescue/evacuation") for value in needs))
    if any(value not in NEED_SCORES for value in needs):
        raise ValueError("Unknown or unsupported need category")
    if "urgency" in payload and "self_reported_urgency" in payload:
        raise ValueError("Provide urgency or self_reported_urgency, not both")
    urgency = _integer(payload.get("self_reported_urgency", payload.get("urgency")), "urgency", maximum=10)
    people = payload.get("people_affected")
    people = 4 if people == "4+" else _integer(people, "people_affected", 1)
    danger = payload.get("immediate_danger")
    if isinstance(danger, str) and danger.strip().lower() in ("yes", "no"):
        danger = danger.strip().lower() == "yes"
    if not isinstance(danger, bool):
        raise ValueError("immediate_danger must be Yes/No or a boolean")
    shelter = payload.get("shelter_status")
    access = payload.get("responder_access")
    if shelter not in ("safe", "unsure", "unsafe") or access not in ("yes", "unsure", "no"):
        raise ValueError("Choose a valid shelter_status and responder_access")
    reporter_type = payload.get("reporter_type", "unspecified")
    if reporter_type not in ("myself", "household", "someone_else", "unspecified"):
        raise ValueError("Unknown reporter_type")
    return {"region_id": region_id, "household_id": f"fictional-{region_id}-household-{household_number:04d}",
            "household_number": household_number, "reporter_type": reporter_type,
            "people_affected": people, "immediate_danger": danger, "urgency": urgency,
            "needs": needs, "shelter_status": shelter, "responder_access": access}


def demo_records(scenario):
    """Validate and score complete fictional form answers using the form pipeline."""
    rows = json.loads((scenario["directory"] / "community_reports.json").read_text(encoding="utf-8"))
    records = []
    for row in rows:
        submitted = parse_time(scenario["event"]["earthquake_at"]) + timedelta(hours=row["hours_since_earthquake"])
        if not parse_time(scenario["event"]["earthquake_at"]) <= submitted <= scenario["snapshot_at"]:
            continue
        payload = row["form_assessment"]
        values = normalise_report(payload, scenario)
        if values["region_id"] != row["region_id"] or values["household_id"] != row["household_id"]:
            raise ValueError("Demo form answers must match the fixture region and household")
        record = {
            "report_id": "demo:" + scenario["event"]["event_id"] + ":" + row["report_id"],
            "event_id": scenario["event"]["event_id"], "region_id": row["region_id"],
            "household_id": row["household_id"], "submitted_at": submitted.isoformat(),
            "created_at": scenario["snapshot_at"].isoformat(),
            "clock_mode": scenario["event"]["clock_mode"],
            "source": "synthetic_community_report", "verification_status": "fictional_unverified",
            "original_report": payload, "model_report": values,
            "context": {"source": "fictional_backend_datasets",
                        "context_version": scenario["event"]["context_version"]},
        }
        record["priority"] = score_record(scenario, record)
        records.append(record)
    return records

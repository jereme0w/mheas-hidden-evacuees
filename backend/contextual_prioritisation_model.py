"""Paper-aligned household priority and regional visibility assessments.

The household priority model follows Table 3 and Eq. (1) of the accompanying
paper. District expectations are supplied by the learned regional reporting model.
All bundled reports and contextual data are fictional demonstration material.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from regional_model import RegionalReportModel


# Table 3 weights from the paper. These sum to exactly 1.0.
PRIORITY_WEIGHTS = {
    "P": .095, "D": .285, "U": .050, "V": .190, "N": .1425,
    "A": .1425, "Q": .040, "I": .035, "C": .020,
}
SHAKING_SCORES = {"light": 2.5, "moderate": 5., "strong": 7.5, "severe": 10.}
INFRASTRUCTURE_SCORES = {"normal": 0., "minor": 2.5, "moderate": 5., "major": 7.5, "severe": 10.}
COMMUNICATION_SCORES = {"normal": 0., "intermittent": 5., "outage": 7.5, "major outage": 10., "major_outage": 10.}
NEED_SCORES = {
    "communication": 4., "electricity": 4., "transport": 5., "other": 5.,
    "food": 6., "sanitation": 6., "water": 8., "shelter": 8., "medical": 9.,
    "rescue": 10., "evacuation": 10., "rescue/evacuation": 10.,
}
SHELTER_SCORES = {"safe": 0., "unsure": 5., "unsafe": 8.}
ACCESS_SCORES = {"yes": 0., "unsure": 5., "no": 10.}
HIGH_RISK_VULNERABILITIES = {"injury", "medication_dependency", "limited_mobility"}


@dataclass(frozen=True)
class CommunityReport:
    report_id: str
    district: str
    household_id: str  # Invented scenario identifier, not a real person's ID.
    submitted_at: datetime
    people_affected: int
    immediate_danger: bool | str
    urgency: int
    needs: Sequence[str]
    shelter_status: str
    responder_access: str
    vulnerability_count: int = 0
    high_risk_vulnerabilities: Sequence[str] = ()


@dataclass(frozen=True)
class AreaContext:
    district: str
    estimated_people_present: int
    occupied_households: int
    shaking: str
    shaking_intensity: float  # Numeric MMI estimate; not earthquake magnitude.
    damage_level: float  # Assessed damage, 0..1; independent of report count.
    infrastructure: str
    communications: str
    reporting_participation: float  # Normal-condition participation, 0..1.
    earthquake_at: datetime
    assessed_at: datetime
    report_feed_complete: bool = True
    context_version: int = 1


def _key(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a non-empty string")
    return value.strip().lower()


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Use a timezone-aware datetime, for example datetime.now(timezone.utc)")
    return value.astimezone(timezone.utc)


def _lookup(value, mapping, label):
    key = _key(value)
    if key not in mapping:
        raise ValueError(f"Unknown {label}: {value}")
    return mapping[key]


def _integer(value, label, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must not exceed {maximum}")
    return value


def normalise_people_affected(value):
    return min(_integer(value, "people_affected", 1), 4) * 2.5


def normalise_immediate_danger(value):
    if isinstance(value, bool):
        return 10. if value else 0.
    return _lookup(value, {"yes": 10., "no": 0.}, "immediate_danger")


def normalise_urgency(value):
    """Compress self-reported urgency exactly as Table 3: 0-2/3-5/6-8/9-10 -> 1/2/3/4."""
    value = _integer(value, "urgency", maximum=10)
    if value <= 2:
        return 1.
    if value <= 5:
        return 2.
    if value <= 8:
        return 3.
    return 4.


def normalise_vulnerability(count, high_risk_values=()):
    """Map vulnerability count and apply the Table 3 high-risk floor of 8."""
    count = _integer(count, "vulnerability_count", minimum=0)
    if isinstance(high_risk_values, str):
        raise ValueError("high_risk_vulnerabilities must be a list")
    values = []
    for value in high_risk_values:
        key = _key(value)
        if key not in HIGH_RISK_VULNERABILITIES:
            raise ValueError(f"Unknown high-risk vulnerability: {value}")
        if key not in values:
            values.append(key)
    if count < len(values):
        raise ValueError("vulnerability_count cannot be lower than the number of high-risk vulnerabilities")
    score = 0. if count == 0 else 5. if count == 1 else 7. if count == 2 else 9.
    return max(score, 8.) if values else score


def normalise_primary_need(values):
    if isinstance(values, str):
        raise ValueError("needs must be a list of need categories")
    return max((_lookup(value, NEED_SCORES, "need") for value in values), default=0.)


def classify_priority(score):
    return "Low" if score < 3 else "Moderate" if score < 7 else "High" if score < 9 else "Critical"


def prioritise_report(report, context):
    if _key(report.district) != _key(context.district):
        raise ValueError("Report district does not match contextual district")
    _key(report.report_id)
    _key(report.household_id)
    _aware(report.submitted_at)
    factors = {
        "P": normalise_people_affected(report.people_affected),
        "D": normalise_immediate_danger(report.immediate_danger),
        "U": normalise_urgency(report.urgency),
        "V": normalise_vulnerability(report.vulnerability_count, report.high_risk_vulnerabilities),
        "N": max(normalise_primary_need(report.needs),
                 _lookup(report.shelter_status, SHELTER_SCORES, "shelter_status")),
        "A": _lookup(report.responder_access, ACCESS_SCORES, "responder_access"),
        "Q": _lookup(context.shaking, SHAKING_SCORES, "shaking"),
        "I": _lookup(context.infrastructure, INFRASTRUCTURE_SCORES, "infrastructure"),
        "C": _lookup(context.communications, COMMUNICATION_SCORES, "communications"),
    }
    score = sum(PRIORITY_WEIGHTS[key] * factors[key] for key in PRIORITY_WEIGHTS)
    return {"report_id": report.report_id, "district": report.district,
            "normalised_factors": factors, "score": round(score, 3),
            "priority": classify_priority(score), "method": "weighted_priority_model",
            "context_assessed_at": _aware(context.assessed_at).isoformat(),
            "context_version": context.context_version}


def load_reporting_model(path=None):
    default = Path(__file__).resolve().parents[1] / "models" / "regional_model.json"
    return RegionalReportModel.load(default if path is None else path)


def _snapshot_reports(context, reports, current_time):
    start, end = _aware(context.earthquake_at), _aware(current_time)
    if start > end:
        raise ValueError("The snapshot must not precede the earthquake")
    return [report for report in reports if _key(report.district) == _key(context.district)
            and start <= _aware(report.submitted_at) <= end]


def _region_input(context, reports, current_time):
    _integer(context.estimated_people_present, "estimated_people_present")
    _lookup(context.shaking, SHAKING_SCORES, "shaking")
    _lookup(context.infrastructure, INFRASTRUCTURE_SCORES, "infrastructure")
    _lookup(context.communications, COMMUNICATION_SCORES, "communications")
    if _aware(context.assessed_at) > _aware(current_time):
        raise ValueError("Context must not be assessed after the snapshot")
    household_ids = {_key(report.household_id) for report in reports}
    return {"region_id": _key(context.district), "region_name": context.district,
            "occupied_households": context.occupied_households,
            "shaking_intensity": context.shaking_intensity, "damage_level": context.damage_level,
            "reporting_participation": context.reporting_participation,
            "hours_since_earthquake": (_aware(current_time)-_aware(context.earthquake_at)).total_seconds()/3600,
            "reports_received": len(household_ids), "report_feed_complete": context.report_feed_complete,
            "communications_available": _key(context.communications) == "normal"}


def _decorate(result, context, reports, current_time):
    latest = max((_aware(report.submitted_at) for report in reports), default=None)
    return result | {"district": context.district, "status": result["classification"],
                     "report_count": len({_key(report.household_id) for report in reports}),
                     "submission_count": len(reports),
                     "estimated_people_present": context.estimated_people_present,
                     "latest_report_at": latest.isoformat() if latest else None,
                     "latest_report_age_hours": (_aware(current_time)-latest).total_seconds()/3600 if latest else None,
                     "assessment_time": _aware(current_time).isoformat(),
                     "context_assessed_at": _aware(context.assessed_at).isoformat(),
                     "context_version": context.context_version}


def assess_area_information_gap(context, reports, current_time, model=None):
    """One district: learned expectation plus explicit damage/silence policy."""
    model = load_reporting_model() if model is None else model
    selected = _snapshot_reports(context, reports, current_time)
    result = model.classify_region(_region_input(context, selected, current_time))
    return _decorate(result, context, selected, current_time)


def evaluate_city_snapshot(contexts, reports, current_time, model=None):
    """Count each fictional household once per earthquake and city snapshot.

    All districts are assessed, even if they have no reports. Simultaneous
    district checks use the regional model's adjusted silence threshold.
    """
    model = load_reporting_model() if model is None else model
    by_district = {_key(context.district): context for context in contexts}
    if len(by_district) != len(contexts):
        raise ValueError("Contexts require distinct districts")
    _aware(current_time)
    owners = {}
    for report in reports:
        district = _key(report.district)
        if district not in by_district:
            raise ValueError(f"No context for district {report.district}")
        household = _key(report.household_id)
        if household in owners and owners[household] != district:
            raise ValueError("A fictional household identifier cannot belong to two districts")
        owners[household] = district
    selected = [_snapshot_reports(context, reports, current_time) for context in contexts]
    results = model.classify_regions([_region_input(context, rows, current_time)
                                     for context, rows in zip(contexts, selected)])
    return {"assessment_time": _aware(current_time).isoformat(),
            "report_priorities": [prioritise_report(report, context)
                                  for context, rows in zip(contexts, selected) for report in rows],
            "area_information_gaps": [_decorate(result, context, rows, current_time)
                                      for result, context, rows in zip(results, contexts, selected)]}

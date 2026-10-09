"""Small learned reporting model for Riverford (Python 3.10+).

Predicts distinct reporting households expected since earthquake onset under
functioning reporting conditions. It flags unusually low counts when contextual
damage is substantial. A low-tail probability is NOT a probability that people
are missing. Training examples and default thresholds are illustrative.
"""
import json
import math
from pathlib import Path
from scipy.stats import nbinom, poisson

MODEL_VERSION = "riverford-reporting-v1"
FEATURES = ("shaking_intensity", "damage_level", "hours_since_earthquake", "reporting_participation")


def _features(region):
    return [region["shaking_intensity"] - 5, region["damage_level"],
            math.log(region["hours_since_earthquake"] + .1), region["reporting_participation"]]


def _validate(region, require_reports=True):
    required = ["occupied_households", *FEATURES]
    if require_reports:
        required += ["reports_received", "report_feed_complete"]
    missing = [key for key in required if region.get(key) is None]
    if missing:
        raise ValueError("Missing fields: " + ", ".join(missing))
    for key in required:
        if key == "report_feed_complete":
            continue
        value = region[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
    households = region["occupied_households"]
    if not isinstance(households, int) or households < 0:
        raise ValueError("occupied_households must be a non-negative integer")
    if require_reports:
        count = region["reports_received"]
        if not isinstance(count, int) or not 0 <= count <= households:
            raise ValueError("reports_received must count distinct reporting households, from 0 to occupied_households")
        if not isinstance(region["report_feed_complete"], bool):
            raise ValueError("report_feed_complete must be true or false")
    if not 1 <= region["shaking_intensity"] <= 12:
        raise ValueError("shaking_intensity must be an MMI value between 1 and 12")
    for key in ("damage_level", "reporting_participation"):
        if not 0 <= region[key] <= 1:
            raise ValueError(f"{key} must be between 0 and 1")
    if region["hours_since_earthquake"] < 0:
        raise ValueError("hours_since_earthquake must be non-negative")


class RegionalReportModel:
    def __init__(self, parameters):
        if parameters.get("model_version") != MODEL_VERSION:
            raise ValueError("Unsupported regional model version")
        self.parameters = parameters

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def expected_reports(self, region):
        _validate(region, require_reports=False)
        log_rate = self.parameters["intercept"] + sum(
            coefficient*value for coefficient,value in zip(self.parameters["coefficients"],_features(region)))
        return region["occupied_households"] * math.exp(log_rate)

    def _distribution(self, mean):
        # Learned spread allows more variation than a strict Poisson count.
        dispersion = self.parameters["dispersion"]
        if dispersion <= 1e-6:
            return poisson(mean)
        size = 1/dispersion
        return nbinom(size, size/(size+mean))

    def classify_region(self, region, silence_threshold=.05, damage_threshold=.6):
        """Return an interpretable alert and prediction interval for one region."""
        if not 0 < silence_threshold < 1 or not 0 <= damage_threshold <= 1:
            raise ValueError("Invalid alert thresholds")
        base = {"region_id":region.get("region_id"), "region_name":region.get("region_name"),
                "model_version":MODEL_VERSION, "training_source":self.parameters["training_source"],
                "alert":False}
        try:
            _validate(region)
        except ValueError as error:
            return base | {"classification":"Insufficient data", "reason":str(error)}
        if not region["report_feed_complete"]:
            return base | {"classification":"Insufficient data", "reason":"The report feed is incomplete; missing data cannot be treated as zero reports."}
        if region["occupied_households"] == 0:
            return base | {"classification":"No estimated occupancy", "reason":"No households estimated present; this does not establish safety."}
        mean = self.expected_reports(region)
        distribution = self._distribution(mean)
        received = region["reports_received"]
        probability = float(distribution.cdf(received))
        unusual = mean >= 5 and probability <= silence_threshold
        damaged = region["damage_level"] >= damage_threshold
        alert = unusual and damaged
        classification = "Investigate" if alert else "Monitor" if unusual or damaged else "No alert"
        reason = f"Received {received} distinct household reports; expected approximately {mean:.1f} with functioning reporting."
        if alert:
            reason += " Substantial contextual damage and unusually low reporting warrant verification."
        if region.get("communications_available") is False:
            reason += " A known communications disruption may explain the silence; it does not remove the visibility concern."
        if not alert:
            reason += " This result does not establish that the area is safe."
        return base | {"classification":classification, "alert":alert,
                       "reports_received":received, "expected_reports":round(mean,2),
                       "expected_range_90":list(map(int,distribution.interval(.9))),
                       "shortfall":round(max(mean-received,0),2), "damage_level":region["damage_level"],
                       "lower_tail_probability":probability, "silence_threshold":silence_threshold,
                       "reason":reason}

    def classify_regions(self, regions):
        """Assess one city snapshot, adjusting for simultaneous region checks."""
        if not regions:
            return []
        ids=[row.get("region_id") for row in regions]
        if any(not isinstance(value,str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("Regions require distinct region_id values")
        return [self.classify_region(row, silence_threshold=.05/len(regions)) for row in regions]


def train_model(rows):
    """Fit reporting rates from functioning-reporting examples, not model scores."""
    import numpy as np
    from sklearn.linear_model import PoissonRegressor
    usable = [row for row in rows if row.get("communications_available") is True
              and row.get("report_feed_complete") is True and row["occupied_households"] > 0]
    if len(usable) < 30:
        raise ValueError("At least 30 complete functioning-reporting training examples are required")
    for row in usable:
        _validate(row)
    x = np.array([_features(row) for row in usable])
    exposure = np.array([row["occupied_households"] for row in usable])
    observed = np.array([row["reports_received"] for row in usable])
    fitted = PoissonRegressor(alpha=.0001, max_iter=1000, tol=1e-8).fit(x,observed/exposure,sample_weight=exposure)
    mean = exposure*fitted.predict(x)
    # The paper reports the estimated overdispersion to two decimal places (phi ≈ 0.08).
    # Store and use the same rounded value so reproduced lower-tail probabilities
    # match the published scenario calculations.
    dispersion = round(max(0.,float(np.sum((observed-mean)**2-mean)/np.sum(mean**2))), 2)
    parameters = {"model_version":MODEL_VERSION,"training_source":"synthetic_only",
                  "intercept":float(fitted.intercept_),"coefficients":fitted.coef_.tolist(),
                  "feature_order":list(FEATURES),"feature_transform":"MMI minus 5; damage; log(hours + 0.1); participation",
                  "dispersion":dispersion,"training_rows":len(usable),
                  "training_ranges":{key:[min(row[key] for row in usable),max(row[key] for row in usable)]
                                     for key in ["occupied_households",*FEATURES]}}
    return RegionalReportModel(parameters)

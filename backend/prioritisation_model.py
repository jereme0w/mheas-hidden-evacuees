"""Import compatibility for the revised, non-sensitive contextual model.

Use prioritise_report(CommunityReport, AreaContext), not the old dictionary-only
API. The merged app handles form translation and loading regional context.
"""
from contextual_prioritisation_model import (
    AreaContext, CommunityReport, assess_area_information_gap, classify_priority,
    evaluate_city_snapshot, load_reporting_model, prioritise_report,
)

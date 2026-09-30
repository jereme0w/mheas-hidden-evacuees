"""Run a six-region Riverford example using the fitted regional model."""
import json
from pathlib import Path
from regional_model import RegionalReportModel


def load_regions(directory):
    """Join only fictional population, impact, disruption and report data."""
    directory=Path(directory)
    population=json.loads((directory/"population.json").read_text())
    impact_rows=json.loads((directory/"earthquake_impact.json").read_text())
    disruption_rows=json.loads((directory/"infrastructure.json").read_text())
    impact={row["region_id"]:row for row in impact_rows}
    disruption={row["region_id"]:row for row in disruption_rows}
    event=json.loads((directory/"city_context.json").read_text())
    reports=json.loads((directory/"community_reports.json").read_text())
    ids={row["region_id"] for row in population}
    if (len(ids)!=len(population) or len(impact)!=len(impact_rows)
            or len(disruption)!=len(disruption_rows) or set(impact)!=ids or set(disruption)!=ids):
        raise ValueError("Context datasets must contain the same distinct region IDs")
    coverage={key:set() for key in ids}
    owners={}
    for report in reports:
        if (report["region_id"] not in ids or not isinstance(report["household_id"],str)
                or not report["household_id"].strip()):
            raise ValueError("Reports require a known region and a fictional household identifier")
        if report["household_id"] in owners and owners[report["household_id"]]!=report["region_id"]:
            raise ValueError("A fictional household identifier cannot belong to two regions")
        owners[report["household_id"]]=report["region_id"]
        if not 0 <= report["hours_since_earthquake"] <= event["hours_since_earthquake"]:
            continue
        coverage[report["region_id"]].add(report["household_id"])
    return [row|impact[row["region_id"]]|disruption[row["region_id"]]|
            {"hours_since_earthquake":event["hours_since_earthquake"],
             "report_feed_complete":event["report_feed_complete"],
             "reports_received":len(coverage[row["region_id"]])} for row in population]


if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]
    model=RegionalReportModel.load(root/"models"/"regional_model.json")
    results=model.classify_regions(load_regions(root/"datasets"/"riverford"))
    print(json.dumps(results,indent=2))

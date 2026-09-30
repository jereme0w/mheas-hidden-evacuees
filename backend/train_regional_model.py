"""Train the small regional model, with complete earthquakes held out for testing."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from scipy.stats import poisson
from sklearn.metrics import mean_poisson_deviance
from regional_model import train_model


def generate_demo_training(seed=789, events=120):
    """Fictional counts only. This simulator is not a real reporting-rate estimate.

    No health, personal characteristics or sensitive fields are used. A shared
    regional rate multiplier introduces count variation across earthquake
    snapshots. Report counts rise with time and never exceed occupied households.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for event in range(events):
        event_shaking = rng.uniform(4.3,8.2)
        for region in range(6):
            households = int(rng.integers(50,3501))
            shaking = float(np.clip(event_shaking+rng.normal(0,.7),4,9))
            damage = float(np.clip((shaking-4)/5+rng.normal(0,.15),.02,.98))
            participation = float(rng.uniform(.4,.99))
            shared_rate = rng.gamma(12,1/12)
            previous_mean, cumulative = 0.,0
            for hours in (.5,2.,8.,24.):
                rate = np.exp(-7 + .38*(shaking-5) + 1.1*damage + .55*np.log(hours+.1) + 1.5*participation)
                mean = float(households*rate)
                cumulative = min(households,cumulative+int(rng.poisson((mean-previous_mean)*shared_rate)))
                previous_mean = mean
                rows.append({"event_id":f"training-event-{event:03}","region_id":f"region-{region}",
                             "occupied_households":households,"shaking_intensity":shaking,
                             "damage_level":damage,"hours_since_earthquake":hours,
                             "reporting_participation":participation,"reports_received":cumulative,
                             "communications_available":True,"report_feed_complete":True})
    return rows


def read_training(path):
    with Path(path).open(encoding="utf-8",newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key in ("occupied_households","reports_received"):
            row[key]=int(row[key])
        for key in ("shaking_intensity","damage_level","hours_since_earthquake","reporting_participation"):
            row[key]=float(row[key])
        for key in ("communications_available","report_feed_complete"):
            if row[key].lower() not in ("true","false"):
                raise ValueError(f"{key} must be true or false")
            row[key]=row[key].lower()=="true"
    return rows


def run(training_path, model_path, metrics_path):
    rows=read_training(training_path)
    event_ids=sorted({row["event_id"] for row in rows})
    if len(event_ids)<10:
        raise ValueError("Use at least 10 independent earthquake scenarios")
    rng=np.random.default_rng(789)
    rng.shuffle(event_ids)
    boundary=int(len(event_ids)*.75)
    training_events=set(event_ids[:boundary]); test_events=set(event_ids[boundary:])
    training=[row for row in rows if row["event_id"] in training_events]
    testing=[row for row in rows if row["event_id"] in test_events and row["communications_available"] and row["report_feed_complete"]]
    if not testing:
        raise ValueError("No complete functioning-reporting test cases")
    model=train_model(training)
    observed=np.array([row["reports_received"] for row in testing])
    predicted=np.array([model.expected_reports(row) for row in testing])
    baseline_training=[row for row in training if row["communications_available"]
                       and row["report_feed_complete"] and row["occupied_households"]>0]
    constant_rate=sum(row["reports_received"] for row in baseline_training)/sum(row["occupied_households"] for row in baseline_training)
    constant_prediction=np.array([row["occupied_households"]*constant_rate for row in testing])
    covered=[]; poisson_covered=[]; false_silence=[]
    for row,mean in zip(testing,predicted):
        distribution=model._distribution(mean)
        low,high=distribution.interval(.9)
        covered.append(low<=row["reports_received"]<=high)
        low0,high0=poisson(mean).interval(.9)
        poisson_covered.append(low0<=row["reports_received"]<=high0)
        false_silence.append(mean>=5 and distribution.cdf(row["reports_received"])<=.05)
    metrics={"evaluation_source":"held-out synthetic earthquake scenarios only",
             "training_events":len(training_events),"test_events":len(test_events),
             "training_rows":len(training),"test_rows":len(testing),"event_split_overlap":len(training_events&test_events),
             "mean_absolute_count_error":float(np.mean(np.abs(observed-predicted))),
             "model_poisson_deviance":float(mean_poisson_deviance(observed,predicted)),
             "constant_rate_poisson_deviance":float(mean_poisson_deviance(observed,constant_prediction)),
             "prediction_interval_90_coverage":float(np.mean(covered)),
             "strict_poisson_interval_90_coverage":float(np.mean(poisson_covered)),
             "normal_reporting_lower_tail_flag_rate_at_05":float(np.mean(false_silence)),
             "limitation":"These metrics test recovery of invented simulation behaviour, not operational accuracy."}
    model.parameters["validation"]=metrics
    for path,data in ((model_path,model.parameters),(metrics_path,metrics)):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return metrics


if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training",type=Path,default=root/"datasets"/"training_reports.csv")
    parser.add_argument("--model",type=Path,default=root/"models"/"regional_model.json")
    parser.add_argument("--metrics",type=Path,default=root/"models"/"validation_metrics.json")
    parser.add_argument("--generate-demo-data",action="store_true",help="Overwrite the selected training CSV with fictional demonstration data")
    args=parser.parse_args()
    if args.generate_demo_data:
        rows=generate_demo_training()
        args.training.parent.mkdir(parents=True,exist_ok=True)
        with args.training.open("w",encoding="utf-8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
    print(json.dumps(run(args.training,args.model,args.metrics),indent=2))

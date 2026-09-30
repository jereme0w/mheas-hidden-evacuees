# Standalone learned reporting model

For the merged form and API, use README.md. The standalone demo below reads
the supplied JSON fixtures; it does not read new reports from SQLite.


Python 3.10+. All supplied population, city context, earthquake impact,
infrastructure disruption, community reports and evaluation data are fictional.
No biological, health, age, medication or other sensitive attributes are used.

## Run the included example

Extract this package. In its root directory, using the same Python environment
as your program:

```powershell
python -m pip install -r requirements_regional.txt
python backend/demo_regions.py
```

The trained JSON model is included, so no training is needed to run it.
The example prints assessments for six Riverford districts:

| District | Distinct household reports | Expected with functioning reporting | Assessment |
|---|---:|---:|---|
| Central | 36 | 43.82 | No silence alert |
| Eastbank | 18 | 40.83 | Monitor |
| Westbridge | 0 | 67.57 | Investigate |
| Hillcrest | 4 | 8.30 | No silence alert |
| Industrial | 0 | 0.43 | No silence alert |
| South Meadows | 7 | 2.60 | No silence alert |

Westbridge's 90% predictive report-count range is 37–105. It has severe
assessed damage and a communications outage. Zero reports is unusually low
under the functioning-reporting baseline. Industrial's low occupancy and mild
impact make zero reports unsurprising. Eastbank is monitored because of its
substantial assessed damage; its lower-tail result does not pass the stricter
city-wide threshold.

## What is learned

A small Poisson regression learns the normal reporting rate from shaking,
damage level, elapsed time and normal-condition reporting participation.
Estimated occupied households supply exposure: double the occupancy with the
same conditions, and the expected report count doubles.

Training fits four coefficients and an intercept. A learned dispersion value
allows the report counts to vary more than a strict Poisson distribution,
using a negative-binomial predictive distribution. No neural network, random
forest, external service, map subscription or pickled model is needed.

Only examples with functioning communications and complete collection feeds
train the normal-condition baseline. Communications disruption remains a
reason to investigate low visibility; it does not lower the reference count
until silence becomes normal. Road and bridge disruptions are included in the
fictional context files, but are not separate regression inputs in this version.

Reporting participation must be an independent normal-condition estimate. Do
not compute it from the current earthquake's observed report count. Likewise,
do not infer contextual damage from silence or use evaluation truth as a
prediction input.

## What remains an explicit rule

The learned model supplies expectations and uncertainty. The final alert policy
is deliberately simple: expected count at least 5, damage level at least 0.6,
and a lower-tail probability at most 0.05 for a single district. For a city
snapshot containing N districts, the threshold is 0.05/N. These are illustrative
policy thresholds, not learned probabilities of people needing rescue.

The lower-tail value means the model's probability of receiving this many or
fewer reports under normal reporting conditions. It is not the probability
that people are missing. The shortfall is a report-count gap, not a hidden
population estimate. No silence alert does not establish safety.

The model waits at least 30 minutes before checking reporting silence and
requests manual review outside its fitted context ranges. Those ranges are
stored in the JSON model, covering snapshots through 24 hours. Prediction
intervals describe count variation and do not include all uncertainty in
context estimates or fitted coefficients. Repeated snapshot checks are not
adjusted across time. Latest report age is returned for review; this version
does not implement a separate stale-information alert.

`report_feed_complete=True` means all submissions that reached collection have
been processed through the snapshot time. It does not mean every household
could submit. If the database/import feed is unavailable or incomplete, set it
to False; an empty list must not substitute for an unknown report count.

Individual report priority remains a weighted baseline, explicitly labelled
as such in its output. Vulnerabilities and medical needs have been removed.
The remaining draft weights are renormalised to sum to 1, and urgency now uses
0–10 like other factors. Scores therefore differ from the original draft.
They have not been validated as emergency priority scores.

## Data and evaluation

`datasets/training_reports.csv` contains 120 fictional earthquake scenarios,
six districts per scenario, and four snapshots per district. Observed fictional
report counts are the learning targets; earlier priority scores are not targets.
The generator uses invented relationships. Ninety whole earthquake scenarios
are used for training and thirty for testing; snapshots from an earthquake do
not cross that split.

`models/validation_metrics.json` records the held-out synthetic evaluation.
The 90% predictive intervals covered approximately 89.3% of the held-out counts.
These numbers measure recovery of the invented simulator's behaviour, not
operational accuracy or validation on real earthquakes.

`datasets/riverford/evaluated_truth.json` contains hand-authored fictional
physical damage and communications conditions for reviewing the demonstration.
Its truth is kept separate from estimated contextual inputs. It is not read
by inference or used as predicted class labels to train another model.

## Optional training and functional checks

To refit from the included CSV:

```powershell
python backend/train_regional_model.py
```

To deliberately regenerate the fictional CSV and refit:

```powershell
python backend/train_regional_model.py --generate-demo-data
```

The second command overwrites the selected training CSV. Both commands replace
the selected model and metrics files. Use different `--training`, `--model`,
and `--metrics` paths when keeping separate experiments.

Run the small functional suite:

```powershell
python -m unittest discover -s tests -v
```

The tests use the supplied fitted parameters; no long benchmarks or repeated
training runs are performed.

Algorithm references: [scikit-learn PoissonRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.PoissonRegressor.html),
[SciPy negative-binomial distribution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.nbinom.html).

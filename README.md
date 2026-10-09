# Hidden Evacuees in Post-Disaster Response

This repository contains the research prototype and supplementary materials accompanying the AISS 2026 paper **“When Technology Cannot See Everyone: Hidden Evacuees in Post-Disaster Response.”**

The prototype combines a fictional community reporting form, an interpretable household report-priority model, a learned regional visibility model, a Flask API, and a lightweight responder dashboard. All Riverford scenario data and reports are synthetic and fictional.

## Repository contents

- `backend/` — household priority model, regional visibility model, Flask API, and model-training utilities.
- `frontend/` — fictional community reporting form and responder dashboard.
- `datasets/riverford/` — six-district Riverford scenario inputs and 65 synthetic household reports.
- `datasets/training_reports.csv` — synthetic regional reporting data used to fit and evaluate the regional model.
- `models/` — fitted regional model parameters and held-out synthetic evaluation metrics.
- `tests/` — model, API, form, persistence, and dashboard checks.
- `literature/retained_sources_101.csv` — bibliographic list of the 101 sources retained in the structured literature review.
- `MODEL_README.md` — detailed description of the two model pathways and their limitations.

## Quick start

Use Python 3.10 or later from the repository root:

```powershell
python -m pip install -r requirements.txt
python backend/app.py --seed-demo
```

Then open:

- Community reporting form: `http://127.0.0.1:5000/`
- Responder dashboard: `http://127.0.0.1:5000/dashboard`
- Regional assessment JSON: `http://127.0.0.1:5000/api/regions`
- Stored report JSON: `http://127.0.0.1:5000/api/reports`

The `--seed-demo` option loads the 65 complete fictional Riverford reports. Re-running it does not duplicate the seeded records.

The application creates `data/riverford_reports.sqlite3` locally when it runs. Runtime database files are not part of the archived research release.

## Household report-priority model

The implementation follows Table 3 and Eq. (1) of the accompanying paper. The score is a weighted sum of nine normalised factors:

| Factor | Weight |
|---|---:|
| People affected (P) | 0.095 |
| Immediate danger (D) | 0.285 |
| Self-reported urgency (U) | 0.050 |
| Vulnerability (V) | 0.190 |
| Need severity (N) | 0.1425 |
| Responder access (A) | 0.1425 |
| Hazard intensity (Q) | 0.040 |
| Infrastructure disruption (I) | 0.035 |
| Communications disruption (C) | 0.020 |

Self-reported urgency is compressed from the form's 0–10 input to the paper's 1–4 model scale: 0–2 → 1, 3–5 → 2, 6–8 → 3, and 9–10 → 4. Vulnerability is scored as 0, 5, 7, or 9 for none, one, two, or three-or-more factors; injury, medication dependency, or limited mobility raises the vulnerability score to at least 8. Need severity is the maximum of the reported-need and shelter-condition values.

Priority categories are **Low** for scores below 3, **Moderate** for 3 to below 7, **High** for 7 to below 9, and **Critical** for 9 or above. Under the published mappings and weights, the maximum attainable score is 9.51. A one-person household can reach at most 8.80.

The 65 synthetic Riverford reports reproduce the paper's stated priority distribution:

| Priority | Reports |
|---|---:|
| Low | 28 |
| Moderate | 20 |
| High | 7 |
| Critical | 10 |
| **Total** | **65** |

These expected categories are produced from the same predefined rules used by the implementation. Agreement therefore checks implementation consistency only; it is not independent validation of the priority model.

## Regional visibility model

For district `r`, expected reporting is:

```text
E_r = H_r × p_hat_r
```

where `H_r` is estimated occupied households and `p_hat_r` is the context-adjusted expected reporting rate. The fitted Riverford demonstration uses:

```text
p_hat_r = exp[-6.8295
              + 0.4097(M_r - 5)
              + 0.9635 K_r
              + 0.5451 ln(T_r + 0.1)
              + 1.3010 R_r]
```

The coefficients were fitted to synthetic functioning-reporting scenarios rather than empirical disaster data. Communications disruption is deliberately excluded from the expected-count calculation so that an outage does not lower the reference level against which reporting silence is assessed.

Observed reporting counts distinct fictional households once per city snapshot. The shortfall is `max(E_r - O_r, 0)`. Lower-tail probabilities use a negative-binomial predictive distribution with estimated overdispersion approximately 0.08.

For a city snapshot containing `n` districts, reporting is unusually low when `E_r >= 5` and the lower-tail probability is at most `0.05/n`. Substantial damage is `K_r >= 0.6`. A district is classified **Investigate** when both conditions hold, **Monitor** when either holds, and **No alert** otherwise.

For the supplied six-district Riverford snapshot:

| District | Occupied households | Expected | Observed | Shortfall | Assessment |
|---|---:|---:|---:|---:|---|
| Central | 2600 | 43.82 | 36 | 7.82 | No alert |
| Eastbank | 2200 | 40.83 | 18 | 22.83 | Monitor |
| Westbridge | 1680 | 67.57 | 0 | 67.57 | Investigate |
| Hillcrest | 1000 | 8.30 | 4 | 4.30 | No alert |
| Industrial | 120 | 0.43 | 0 | 0.43 | No alert |
| South Meadows | 400 | 2.60 | 7 | 0.00 | No alert |

A regional reporting shortfall is an information-visibility signal, not an estimate of hidden people or unmet need. A **No alert** result does not establish safety.

## Synthetic training and evaluation

`datasets/training_reports.csv` contains 120 fictional earthquake scenarios, six districts per scenario, and four snapshots per district. Ninety whole earthquake scenarios are used for model fitting and thirty for held-out synthetic evaluation, so snapshots from one earthquake do not cross the split.

The fitted model parameters in `models/regional_model.json` correspond to the coefficients reported in the paper. The held-out metrics in `models/validation_metrics.json` measure recovery of the synthetic generator's behaviour only; they do not establish operational accuracy on real earthquakes.

`datasets/riverford/evaluated_truth.json` contains hand-authored fictional damage and communications conditions for reviewing the demonstration. It is kept separate from inference inputs and is not an independent validation dataset for the household priority rules.

## Tests

Run the Python checks from the repository root:

```powershell
python -m unittest discover -s tests -v
```

Optional form and dashboard DOM tests require a supported Node.js version:

```powershell
npm install
npm test
```

The tests are bounded functional checks; they do not constitute emergency-system validation.

## Supplementary literature-review material

`literature/retained_sources_101.csv` contains bibliographic metadata for the 101 sources retained during the structured literature review reported in the paper. The file does not redistribute the publications themselves.

## Legacy environment-variable names

Two environment-variable names retain the original development identifier for backwards compatibility:

- `CS789_DATABASE` — optional path for the SQLite runtime database.
- `CS789_DATASET_DIR` — optional path for the Riverford scenario datasets.

The `CS789` prefix is only a legacy implementation name; it is not the title or scope of the published research artifact.

## Licence

The original prototype source code is released under the MIT License; see `LICENSE`.

The original Riverford synthetic datasets and supplementary research data are released under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence; see `datasets/LICENSE`.

Bibliographic metadata in `literature/retained_sources_101.csv` does not alter the copyright or licensing conditions of the cited third-party publications.

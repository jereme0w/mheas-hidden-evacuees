# CS789: merged Riverford reporting prototype

The reporting form, Flask API and learned regional model now run together.
All supplied scenario data is fictional. The active form contains no health,
age, medication, vulnerability, personal name, real address, coordinates,
free-text notes or photo fields.

## Fixing a persistent `/api/regions` 404

The source in this package has the regions route. A 404 on port 5000 means
that URL is being handled by a different or stale app instance. Launch this
copy on a separate port to remove that ambiguity:

```powershell
python backend/app.py --seed-demo --port 5001
```

Open **http://127.0.0.1:5001/api/regions**, using port **5001**, not 5000.
Alternatively, run `run_riverford.bat` from the extracted project folder.
The launcher changes to its own folder and uses port 5001.

http://127.0.0.1:5001/api/version should return version
`riverford-dashboard-2026-10-01.3`. Startup also prints the absolute backend file path.
If a port is occupied, the command reports that conflict rather than implying
it replaced the existing server. Stop that server or choose another port.

The SQLite test cleanup defect is corrected: connections are explicitly
closed while retaining transaction commit/rollback handling. Every API test
now tracks all its SQLite connections and checks closure before temporary
files are removed. This detects leaked handles even on platforms that allow
an open SQLite file to be deleted. Expected failure tests may still print
`Report transaction failed` followed by `ok`.

## Visual dashboard

After starting the app, open **http://127.0.0.1:5001/dashboard** when using
`run_riverford.bat` or `--port 5001`. On the default port, use
http://127.0.0.1:5000/dashboard. The reporting form at `/` links to it.
Restart the running server after copying these files.

The dashboard uses one `/api/dashboard` snapshot backed by the current SQLite
reports and model assessment. It includes:

- A clickable, keyboard-accessible SVG map of all six fictional districts.
- Visibility-assessment and assessed-damage-index map layers.
- Received-versus-expected household report bars and 90% predictive ranges.
- A selected-district panel with population, occupancy, impact, infrastructure,
  communications and reporting-feed context.
- A review queue, ordered with visibility alerts first.
- Community reports filtered by district and weighted report priority, with
  detailed records and links to saved JSON.
- A Refresh data button for updating the display after new submissions.

The map is a fictional schematic, not surveyed geography. It uses no external
map service or subscription. Damage is shown as a normalised index out of 100,
not as a measured percentage of buildings damaged. Population and occupancy
provide context; report priority and regional visibility are distinct assessments.

The initial seeded view selects Westbridge and shows its silent, heavily
impacted district. All 65 seeded reports contain complete fictional form answers,
are scored through the same validation and priority calculation as the form,
and appear in the table by default as Fictional demo report.

Unavailable reporting feeds are labelled Unknown/Partial data, not presented
as zero reports. Failed refreshes clearly mark retained results as stale.
The dashboard remains a fixed two-hour fictional snapshot; refreshing fetches
new submissions but does not advance the scenario clock. Only manual refresh
is enabled; there are no timed polling loops or external data requests.

Dashboard files: `frontend/dashboard.html`, `frontend/dashboard.css`,
`frontend/dashboard.js`, and the routes in `backend/app.py`.
`tests/test_dashboard.py` adds six API tests. `tests/test_dashboard.cjs` adds
eight DOM behaviour tests, backed by `tests/cases/dashboard_snapshot.json`.
Together with the existing suites, 41 Python tests and 17 form/dashboard tests
passed in bounded functional runs. The DOM tests use jsdom, not a full browser
visual-rendering test. No model retraining was needed for this dashboard.

## Run in VS Code

Extract the ZIP and open its `cs789` folder in VS Code. In a terminal in that
folder, use Python 3.10 or later:

```powershell
python -m pip install -r requirements.txt
python backend/app.py --seed-demo
```

Open **http://127.0.0.1:5000**. Open the form through Flask, rather than opening
the HTML directly from the file tree. Stop the server with Ctrl+C.

`--seed-demo` imports the 65 complete fictional reporting-household assessments. Repeating
it is safe: it does not duplicate those fixture rows. Omitting the flag starts
with whichever reports already exist in the new database; for a fresh database
this means zero reports, not the 65-report example.

For an isolated environment on Windows, without activating PowerShell scripts:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python backend/app.py --seed-demo
```

The app listens on localhost. To use another port:

```powershell
python backend/app.py --seed-demo --port 5001
```

## How submissions and assessments work

1. The form loads Riverford districts from `/api/context`.
2. Choose a district and a fictional household number. Reuse the same number
   for updates to that household. Numbers range from 1 to that district's
   estimated occupied-household count.
3. Select report details and submit. The backend translates the form into
   `CommunityReport`, obtains `AreaContext` from its datasets, and scores it.
4. In one SQLite transaction, the backend saves the report, computes the city
   assessment including that report, and stores its regional result. The form
   confirms receipt only after commit.

Distinct households determine the regional count. Repeated submissions remain
available as history and receive new report scores, but do not add households.
The report scorer's `4+` option is normalised to 4 for its capped group-size
factor; it is not an exact population count.

Individual report priority remains a transparent weighted baseline. Regional
reporting expectations are learned from occupancy, shaking, assessed damage,
elapsed time and normal-condition reporting participation. The model flags
unusually low reporting combined with substantial assessed damage. A known
communications disruption explains low visibility without lowering the
normal-condition reference until silence appears normal.

The API rejects unsupported fields and health-related need categories. Context
is supplied by the backend; form users cannot override shaking, damage,
participation or earthquake timing.

## Inspect reports and regional alerts

While the server is running:

| Address | Contents |
|---|---|
| http://127.0.0.1:5000/api/context | Scenario clock and fictional district population/occupancy |
| http://127.0.0.1:5000/api/regions | Current regional assessments, count expectations, intervals and alerts |
| http://127.0.0.1:5000/api/reports | Stored reports for the current fictional event |
| `http://127.0.0.1:5000/api/reports/<report_id>` | One stored report and its submission-time assessment |

The form also links to the regional and report JSON views. An assessment with
`alert=true` and `classification="Investigate"` is the responder-facing alert
indicator. This version does not send emails or push notifications.

Stored `regional_assessment` describes the moment of that submission. Use
`/api/regions` for the latest assessment after further submissions.

## Database and existing files

The new app writes **`data/riverford_reports.sqlite3`**, table
**`riverford_reports`**, including a `record_json` column containing full details.
In VS Code's SQLite viewer, open that database and table. `record_json` contains
`priority` and, for form submissions, `regional_assessment`.

Your existing `data/reports.sqlite3` is left intact when applying the new files
over your existing project. It is not included in this code package or imported
into the new model: those records lack the district, stable fictional household
identifier and event timing needed for reliable regional counts.

To merge into your current folder, copy the supplied `backend`, `frontend`,
`datasets`, `models`, and `tests` files, plus requirements and documentation.
The compatibility file `backend/prioritisation_model.py` now re-exports the
revised contextual interface. The old `--demo-hazard` argument is replaced by
backend regional datasets; use the run command above.

For a fresh isolated run without deleting any existing database:

```powershell
$env:CS789_DATABASE = "data/another_demo.sqlite3"
python backend/app.py --seed-demo
```

## Fictional scenario clock

This exercise uses a fixed snapshot two hours after the fictional earthquake,
defined in `datasets/riverford/city_context.json`. New form reports are assigned
that **scenario time**. Their **real receipt time** is stored separately as
`created_at`. This makes the example repeatable across runs and avoids treating
the fictional earthquake as today's real event.

To explore another time, edit `hours_since_earthquake` and restart the server.
Each assessment excludes reports after that snapshot and before the event.
The fitted model covers approximately 0.5–24 hours; unsupported ranges return
an explicit review status rather than an extrapolated safety assessment.

`report_feed_complete` means collection has processed every submission that
reached it up to the snapshot, not that every household could submit. Set it
to false when collection is incomplete. A database failure returns an error,
not a zero-report city. An empty district in an available, complete collection
feed is a valid zero-report observation.

## Included test files and cases

All 12 model tests from the supplied model archive are retained. Added tests
exercise the merged form, API and persistence. No test refits the model or runs
long performance benchmarks.

| File | Cases |
|---|---|
| `tests/test_model.py` | The original 12 reporting-model and contextual integration tests |
| `tests/test_api.py` | 20 API/database tests, including submission validation, repeated households, seeding, saved scores, rollback, unavailable feeds and priority boundaries |
| `tests/test_dashboard.py` | Six dashboard API, context, persistence and unavailable-feed tests |
| `tests/test_dashboard.cjs` | Eight map, filter, detail, stale-data and text-rendering tests |
| `tests/test_http.py` | One real local HTTP flow: form/script, submission, report details and regional readback |
| `tests/test_form.cjs` | Nine form tests: context loading, household limits, needs arrays, receipts, validation, connection failures and repeat-click handling |
| `tests/cases/submission_cases.json` | Four valid priority examples and 19 invalid submission examples |
| `tests/cases/regional_expected.json` | Expected counts and classifications for all six Riverford districts |
| `datasets/riverford/community_reports.json` | All 65 complete fictional form assessments |
| `datasets/riverford/evaluated_truth.json` | Independent fictional damage/outage truth for reviewing the example |
| `datasets/training_reports.csv` | All 2,880 fictional training/evaluation rows |

Run the Python tests from the project root:

```powershell
python -m unittest discover -s tests -v
```

They use temporary SQLite databases. Your working reports are not modified.
For the optional form behaviour tests, install Node.js 24 or later and run:

```powershell
npm install
npm test
```

Verified during this merge: 41 Python tests and 17 form/dashboard tests passed in short
bounded runs. The Python suite includes the real local HTTP test. The form tests
use jsdom; they verify DOM and submission behaviour, not visual rendering in a
full browser.

## Model files and limitations

`models/regional_model.json` already contains fitted coefficients and dispersion,
so training is not needed to run the app. `backend/train_regional_model.py`
and `backend/demo_regions.py` are included, along with the full original model
datasets and evaluation metrics. See `MODEL_README.md` for algorithm details and
optional retraining commands. The standalone demo reads JSON fixture reports;
the merged app reads SQLite reports for its current assessments.

Seeded reports are marked `synthetic_community_report` and `fictional_unverified`.
Their individual priorities are computed from complete form answers and district
context, not supplied as ground-truth labels. They are demonstration inputs,
not new training examples for the learned regional model.

Training and evaluation are synthetic demonstrations. A report shortfall is
not a count of missing people, and a lower-tail value is not the probability
that people require rescue. Policy thresholds remain explicit and illustrative.
No silence alert does not establish safety. Evaluation truth is kept separate
from prediction inputs.


## Upgrade to scored fictional reports
Stop the server, copy the contents of this ZIP's cs789 folder over your project,
then run:
```powershell
python backend/app.py --seed-demo --port 5001
```
Open http://127.0.0.1:5001/dashboard and refresh. Version: riverford-dashboard-2026-10-01.4.
The seed command upgrades matching legacy count-only rows in one transaction.
It preserves report IDs, household IDs, scenario times and regional totals.
It leaves form submissions and already-scored demo entries unchanged, and
can be repeated without duplicates. Do not delete your database.
The ZIP contains no database files.

There are 36 Central, 18 Eastbank, 4 Hillcrest and 7 South Meadows reports.
Westbridge and Industrial retain zero reports. Central and Eastbank include
supply, shelter, access and urgent evacuation examples; the less-impacted
districts focus on supplies, communication and transport. No sensitive or
biological fields are used. Existing regional training and evaluated truth are
unchanged. All four individual priority bands are represented.

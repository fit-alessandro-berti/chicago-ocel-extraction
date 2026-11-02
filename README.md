# Boston municipal inspections → OCEL 2.0

Two reproducible OCEL 2.0 JSON GZ views of Boston food-establishment inspection
results, extracted from **907,385 public source rows** frozen on 2 November 2026.
The repository name is historical; the supplied setting concerns Boston.

| Download | Recorded period | Events | Objects | Object types |
|---|---|---:|---:|---|
| [Historical results](data/ocel/boston-inspections-history.json.gz) | 2006-04-04–2026-10-31 | 220,270 | 236,108 | FoodLicense, Inspection, Property |
| [Detailed results and findings](data/ocel/boston-inspections-findings-2022-2025.json.gz) | 2022–2025 | 60,304 | 239,811 | FoodLicense, Inspection, Property, Finding |

The detailed view includes **167,255 finding objects** and is a subset of the
history view, with additional relationships. Do not concatenate the two views.
Compressed sizes are approximately 19.1 MB and 10.7 MB respectively.

Read the [quality and process-mining findings](reports/QUALITY_AND_INSIGHTS.md)
and the [extraction model](docs/MODEL.md) before interpreting results.
Machine-readable [validation](reports/validation.json),
[source-quality](reports/source-quality.json), and
[process-mining](reports/process-mining.json) reports accompany the logs.

## Load the logs

Git LFS is initialized for this repository and stores the compressed logs and
source responses. After cloning:

```bash
git lfs install
git lfs pull
python -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
```

With PM4Py:

```python
import pm4py

log = pm4py.read_ocel2_json(
    "data/ocel/boston-inspections-findings-2022-2025.json.gz"
)
dfg = pm4py.discover_ocdfg(log, compute_edges_performance=False)
```

Readers without gzip support can first decompress using `gzip -dk <file.json.gz>`.
The data uses the OCEL 2.0 `eventTypes`, `objectTypes`, `events`, and `objects`
structure, qualified E2O/O2O relationships, and timestamped object attributes.

## Reproduce and verify offline

Run from the repository root. The checked-in source snapshot is sufficient:

```bash
.venv/bin/pytest -q
.venv/bin/boston-ocel extract
.venv/bin/boston-ocel validate
.venv/bin/boston-ocel analyze --pm4py
.venv/bin/python scripts/check_reproducibility.py
.venv/bin/python scripts/write_report.py
.venv/bin/python scripts/plot_insights.py
```

Extraction verifies source checksums, rebuilds both logs, and emits quality and
provenance reports. Validation reconciles every eligible source group and every
exported source row, beyond schema/graph checks. Analysis compares its
directly-follows counts with PM4Py's object-centric discovery. See
[artifact hashes](data/ocel/manifest.json) and the
[reproducibility check](reports/reproducibility.json).

The pinned environment in `requirements.lock` was tested with Python 3.13. For a
fresh dependency resolution instead, install `pip install -e '.[test]'`.
Full extraction/validation can use several GB of RAM. No network access is needed
after installing dependencies and pulling the LFS objects.

To collect a **new** source snapshot without overwriting this one:

```bash
.venv/bin/boston-ocel fetch --raw data/raw-new
.venv/bin/boston-ocel extract --raw data/raw-new --output data/ocel-new --reports reports-new
.venv/bin/boston-ocel validate --raw data/raw-new --output data/ocel-new --reports reports-new
.venv/bin/boston-ocel analyze --output data/ocel-new --reports reports-new --pm4py
```

## Interpretation

Source: [Analyze Boston food establishment inspections](https://data.boston.gov/dataset/food-establishment-inspections),
resource `4582bec6-2b4f-4f9e-bc55-cbaa73117f4c` (PDDL). The code's repository
license does not replace the source dataset's license.

The public source has no inspection ID. A result event is reconstructed from the
exact license number and result timestamp; multiple finding rows become one
event. Missing/invalid dates, ambiguous outcomes, and explicit data errors exclude
6,528 rows (0.72%); all remain available in the raw snapshot and issue ledger.

These are recorded outcomes, including administrative entries, rather than a
complete on-site visit lifecycle. License and finding metadata are labelled as
snapshot observations. No repair, closure, illness, or food-poisoning event is
inferred. Observed fail-to-pass intervals do not prove remediation duration, and
traces are truncated at the dataset boundaries. The detailed modeling decisions,
timestamp caveats, schema correction, and supported analyses are documented in
[MODEL.md](docs/MODEL.md).

# Boston municipal inspections → OCEL 2.0

This repository extracts public Boston food-establishment inspection records into
OCEL 2.0 JSON GZ. The repository name is historical; the supplied setting concerns
Boston. Source: [Analyze Boston food establishment inspections](https://data.boston.gov/dataset/food-establishment-inspections),
resource `4582bec6-2b4f-4f9e-bc55-cbaa73117f4c` (PDDL).

The extraction preserves a complete, checksummed API snapshot. An inspection is
reconstructed from license number and result timestamp, because the public data
does not expose an inspection ID. Individual source rows are findings, not
independent inspections. Quality checks and process-mining analysis accompany the
exports. Development is in progress.

Git LFS stores `*.json.gz` and `*.html.gz`. After cloning, run `git lfs install`
and `git lfs pull`.

# Extraction model and limits

## Source choice

The supplied setting explicitly lists Boston development review, permits, food
inspections, and 311 as candidate municipal processes. This extraction selects
[food-establishment inspections](https://data.boston.gov/dataset/food-establishment-inspections).
The public CKAN resource has repeated dated outcomes, license identifiers, finding
records, and property identifiers. It supports sequence and object-level analysis
without joining by approximate business names or street addresses.

The development-project website returned HTTP 403 to direct requests during
discovery. Its referenced ArcGIS layer was accessible, but supplied current state
and last-filed/last-approved dates, not a complete review history. We did not turn
those snapshots into invented lifecycle transitions. A general open-data crawler
and extraction of every candidate dataset are outside this implementation.

## Source snapshot

The source is resource `4582bec6-2b4f-4f9e-bc55-cbaa73117f4c`, labelled a legacy
dataset in its metadata but containing records through October 2026. The frozen
API responses retain every column and `_id`, plus pagination metadata. The source
advertises the Open Data Commons Public Domain Dedication and License (PDDL).
See `data/raw/food-inspections.package.json` for the original attribution and
license metadata. The repository's code license is separate from source data.

`data/raw/manifest.json` records retrieval times, URLs, SHA-256 hashes, first/last
row IDs, and exact row counts. The API capped responses at 32,000 despite a
50,000-row request; pagination advances by the number actually returned. Counts
and metadata were stable before/after collection and IDs strictly increase.
CKAN does not provide a transactional snapshot, so these checks cannot rule out
an undetectable in-place edit during collection. Offline rebuilds use the frozen
responses and verify their checksums.

## Events and objects

| Source concept | OCEL representation | Identity and qualifications |
|---|---|---|
| Result record | One `Inspection result: <raw code>` event | Exact normalized `(licenseno, resultdttm)` group; SHA-256-derived ID |
| Inferred inspection/result group | `Inspection` object | Same composite key; explicitly labelled an inferred identity |
| Food establishment license | `FoodLicense` object | Exact trimmed `licenseno`, including leading zeros |
| Recorded property | `Property` object | Positive source `property_id`; missing/zero identifiers create no object |
| Coded finding row | `Finding` object in the detailed view | Source `_id`; one object per distinct coded row, with duplicate aliases if present |

The history view contains every eligible result group. The detailed view contains
all eligible groups dated in 2022–2025, four recent complete calendar years, plus
their findings. These views overlap: **do not concatenate them as disjoint logs**.
Their common events and objects retain the same IDs. Neither is a random sample.
Source row and finding IDs are local to this frozen snapshot: a CKAN reload may
reassign `_id`. Do not join finding IDs across fresh snapshots without reconciling
their row contents. License identity assumes the public license number is not
reused for a different license; the source offers no stronger key.

Each event relates to exactly one license (`inspected_license`) and inspection
(`inspection`), optionally one property (`recorded_property`), and, in the detailed
view, zero or more findings (`recorded_finding`). Inspection objects relate to their
license and recorded property using the same qualifiers. Finding objects relate
to their inspection using `finding_of`. A property can link multiple licenses;
a license can have many inspection results. Inspection and finding objects are
single-observation entities; repeated behavior is primarily analyzed by license.

Rows are not events. Several findings share an inspection's result timestamp.
Rows without a violation code still establish a result event, but do not create
a finding. A `Pass` finding row is retained as a finding observation, not labelled
an outstanding violation. No finding is linked across inspections as the same
violation episode: the source supplies no stable episode identifier.

## Identity and data-quality decisions

- There is no public inspection ID. Exact license/time grouping is a documented
  reconstruction assumption. Two real inspections at exactly the same instant
  could merge; one real inspection recorded at different instants could split.
- Missing/invalid/naive/future result timestamps, missing license/outcome values,
  conflicting outcomes within a group, and the explicit `DATAERR` result code are
  quarantined. `reports/source-issues.json.gz` lists all affected source row IDs.
  Dates are never filled from license, violation, or status fields.
- Distinct raw outcome codes are preserved, including administrative codes such
  as `HE_NotReq`. These are **recorded outcomes**, not proof that an on-site visit
  occurred. Undocumented codes are not expanded into speculative activity names.
- Near-simultaneous results, and batches across licenses, are preserved and
  measured. Without a stable inspection ID, rounding or silently merging these
  records would invent an identity rule. Sensitivity to administrative results
  matters when interpreting directly-follows graphs.
- Only exact duplicate rows (all fields except `_id`) collapse. All aliases
  remain in provenance. There were no such duplicates in the frozen snapshot.
- A conflicting property link is omitted, while retaining the result event;
  absence of a property does not exclude a license trace. No address-based or
  business-name-based entity resolution is performed.

## Time and attribute semantics

Source result timestamps explicitly include offsets; they are normalized to UTC
without guessing a Boston timezone. Fractional seconds are retained and ordering
uses parsed datetimes, not lexical string order. Event IDs are deterministic but
do not imply causal ordering for simultaneous events on different licenses.

License metadata and finding status/description/date fields are **snapshot
observations**, named `snapshot_*` and timestamped at collection completion. They
are not asserted to have held at each historical inspection. Source date fields
inside these snapshots remain strings (including the original offset/format).
The epoch timestamp is the OCEL static-attribute convention for identifiers and
inspection identity metadata; it is not a business event or creation date.

Conflicting license metadata is omitted per field rather than arbitrarily chosen.
No such conflict occurred in this snapshot. Owner/contact names and free-text
comments remain in the raw archive but are not copied into the OCEL views.

The finding's `violdttm` and `status_date` frequently differ from the inspection
result time and can precede it. We retain these fields, but emit no assumed
"violation repaired" or "status changed" events. The dataset cannot establish
repair duration, food-poisoning incidence, outbreak causality, or compliance with
an inspection schedule.

## Provenance and validation

Each event carries all contributing `source_row_ids` as a comma-separated string
(OCEL attributes are scalar), plus raw/distinct row counts and finding counts.
Finding objects carry their contributing row IDs. Event finding-status counts
are explicitly `snapshot_*` aggregates, not historical status transitions.

Validation combines:

1. The pinned OCEL 2.0 JSON schema from the PM4Py repository, with two documented
   string-only value constraints corrected to scalar values supported by the
   [OCEL 2.0 format](https://www.ocel-standard.org/specification/formats/json/).
   The original standard's old schema URL returned 404. Its mirror provenance
   and hash are in `schemas/provenance.json`.
2. Declared attribute type checks, RFC3339 timestamps, unique IDs and attribute
   observations, qualified relations, reference integrity, and object coverage.
3. Independent full-source reconciliation: no eligible groups silently omitted;
   no invented rows/events/findings; group counts, outcomes, dates, license and
   finding attributes, and property links agree with the source.
4. PM4Py import checks for all event/object IDs, E2O/O2O edges and qualifiers,
   event timestamps, numeric attributes, and agreement with an independently
   computed license directly-follows graph.
5. Regression tests for deduplication, ambiguity, missing dates, property
   sentinels, temporal leakage, fractional seconds, malformed graphs, silent
   omissions, and deterministic gzip serialization.

The PM4Py check is not a claim of lossless object-attribute time round-tripping:
its importer treats first object observations as baseline values. Use the
delivered OCEL JSON as the authority for snapshot observation timestamps.

## Appropriate mining questions

Useful questions include repeat-result patterns, the time to the next **observed
result**, license trace variants, differences between license and property
perspectives, and the composition of recorded findings. The included analysis
uses raw `HE_Fail` and `HE_Pass` codes explicitly, rather than inferring broader
categories from undocumented result codes.

Both ends of the observation period can truncate license traces. A missing next
result is not proof of no follow-up; a next pass is not proof that it belongs to
the same remediation episode. The recent view additionally truncates events
outside 2022–2025. Timing statistics are descriptive, conditional on observed
successors, and are not service-level performance estimates or causal effects.

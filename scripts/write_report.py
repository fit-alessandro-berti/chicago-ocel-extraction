"""Generate the human-readable audit from verified machine-readable results."""
import json
from pathlib import Path

from boston_ocel.source import sha256


def main():
    reports = Path("reports")
    quality = json.loads((reports / "source-quality.json").read_text())
    q = quality["counts"]
    artifacts = json.loads(Path("data/ocel/manifest.json").read_text())["artifacts"]
    mining = json.loads((reports / "process-mining.json").read_text())
    validation = json.loads((reports / "validation.json").read_text())
    repro = json.loads((reports / "reproducibility.json").read_text())
    for a, m, v, r in zip(artifacts, mining, validation, repro["artifacts"], strict=True):
        assert a["sha256"] == m["sha256"] == v["sha256"] == r["sha256"] == sha256(Path("data/ocel") / a["file"])
        assert m["pm4py"]["status"] == v["source_reconciliation"]["status"] == "pass"
    h, s = [m["statistics"] for m in mining]
    f = s["HE_Fail_cohort"]
    sens = s["HE_NotReq_removed_sensitivity"]
    p = s["property_analysis"]
    top_batch = s["largest_cross_license_same_timestamp_batches"][0]
    sections = [f"""# Quality audit and process-mining findings

The two OCEL 2.0 logs are suitable for studying **recorded inspection-result
sequences, repeat-result intervals, and license/property/finding relationships**.
The detailed 2022–2025 view is a practical starting point for teaching; the full
history supports longer traces. These are overlapping views of one source.

They are not a complete visit or remediation lifecycle. A recorded pass does not
establish a repair date, and inspection data cannot establish food-poisoning
incidence. Current-state metadata is explicitly labelled as a snapshot.

Snapshot completed: `{quality['snapshot_at']}`. Source:
[Analyze Boston food establishment inspections](https://data.boston.gov/dataset/food-establishment-inspections).
All numbers below come from the frozen snapshot, not a live query.

## Delivered artifacts

| View | Events | Objects | Licenses | Qualified E2O links | Qualified O2O links |
|---|---:|---:|---:|---:|---:|"""]
    for label, a, m, v in zip(["History (2006–2026)", "Detailed (2022–2025)"], artifacts, mining, validation):
        sections.append(f"| {label} | {a['events']:,} | {a['objects']:,} | {m['statistics']['licenses']:,} | {v['event_object_relations']:,} | {v['object_object_relations']:,} |")
    sections.append(f"""
The detailed view includes {artifacts[1]['object_counts']['Finding']:,} finding
objects. All IDs, attributes, timestamps, and relationships were checked against
the original rows; source row IDs accompany every event and finding.

## Source quality and modeling revisions

| Check | Finding and handling |
|---|---|
| Complete API retrieval | {q['source_rows']:,} rows across 29 pages; hashes, exact counts, ordered IDs, and stable metadata checked |
| Missing/invalid result dates | {q['missing_or_invalid_result_time']:,} rows excluded; no date imputation |
| Conflicting outcomes at one license/time | {q['conflicting_results_at_same_license_time_rows']:,} rows in {q['conflicting_results_at_same_license_time_groups']} groups quarantined |
| Explicit `DATAERR` result | {q['source_result_data_error_rows']:,} rows quarantined |
| Total exclusions | {q['excluded_rows']:,} rows ({100*q['excluded_rows']/q['source_rows']:.2f}%) |
| Accepted source rows | {q['accepted_rows']:,} rows → {q['inspection_groups']:,} result events |
| Exact duplicates | {q['exact_duplicate_rows']:,}; deduplication would preserve all source row aliases |
| No usable property ID | {q['inspection_groups_without_property']:,} historical events retained without a property link |

Treating every accepted row as an inspection would inflate the event count by
**{q['accepted_rows']/q['inspection_groups']:.2f}×**. The extraction instead groups exact
license/result timestamps and links the individual findings to that result.
The public source has no inspection ID, so this grouping remains a transparent
reconstruction assumption rather than a source-verified case identifier.

The first mining run exposed lexical misordering of timestamps with fractional
seconds. The final exporter and analysis sort parsed UTC datetimes; a regression
test covers whole-second versus fractional-second records. A separate gzip test
caught embedded output filenames; the final exports rebuild to identical bytes
even in a different directory.

Of rows with usable result times, {quality['profile']['status_time_vs_result']['before']:,}
have a status timestamp before the result, and
{quality['profile']['violation_time_vs_result']['after']:,} have a violation timestamp
after it. Those fields therefore remain snapshot attributes. We do not derive
repair events, license lifecycle events, or historical status changes from them.

## Repeat-result patterns in 2022–2025

Of {s['licenses']:,} license traces, {s['licenses_with_multiple_events']:,} have more
than one recorded event; the median trace has {s['events_per_license']['median']:g}
events. There are {s['distinct_license_variants']:,} distinct activity sequences.
The historical view has {h['licenses_with_multiple_events']:,} multi-event traces
and a median of {h['events_per_license']['median']:g} events per license.

There are **{f['total_events']:,} `HE_Fail` events** in the recent view:

- The next observed result is `HE_Pass` for **{f['next_is_HE_Pass_gap_days']['n']:,}
  ({100*f['next_is_HE_Pass_gap_days']['n']/f['total_events']:.1f}%)** of them. Conditional on
  this successor, the median gap is **{f['next_is_HE_Pass_gap_days']['median']:.2f} days**,
  with a 10th–90th percentile range of
  {f['next_is_HE_Pass_gap_days']['p10']:.2f}–{f['next_is_HE_Pass_gap_days']['p90']:.2f} days.
- {f['next_is_HE_Pass_within_30_days']:,} of all {f['total_events']:,} `HE_Fail` events
  ({100*f['next_is_HE_Pass_within_30_days']/f['total_events']:.1f}%) have `HE_Pass` as their next
  result within 30 days. This uses all observed failures as the denominator,
  including those with another next outcome or no observed successor.
- {f['no_next_in_log']:,} have no next result within this view. This can reflect
  the time window or missing observations; it does not prove no follow-up.

![Next observed result after HE_Fail](next-observed-outcome.png)

The median gap to any next recorded outcome is
{s['next_observed_result_gap_days_by_current_code']['HE_Fail']['median']:.2f} days after `HE_Fail`
({s['next_observed_result_gap_days_by_current_code']['HE_Fail']['n']:,} observed pairs), versus
{s['next_observed_result_gap_days_by_current_code']['HE_Pass']['median']:.2f} days after `HE_Pass`
({s['next_observed_result_gap_days_by_current_code']['HE_Pass']['n']:,} observed pairs).
This is consistent with different follow-up patterns, but does not identify
inspection purpose or prove a causal effect of failure. No reinspection ID or
remediation episode links the two results.

## Administrative batches and sensitivity

The largest simultaneous batch has **{top_batch['licenses']:,} licenses** with
`{top_batch['result']}` at `{top_batch['time']}`. There are
{sum(e['count'] for e in s['subsecond_same_license_pairs']):,} subsecond consecutive
same-license pairs, all `HE_NotReq` → `HE_NotReq`. These patterns strongly suggest
administrative/batch recording; they should not be interpreted as physical visits
or zero-duration work. The source records remain intact rather than being merged
by an invented rounding rule.

As a sensitivity analysis, removing `HE_NotReq` removes
{sens['removed_events']:,} events, leaving {sens['remaining_events']:,} events across
{sens['remaining_licenses']:,} licenses. {sens['licenses_with_only_HE_NotReq']:,} original
license traces contain only that code. The projected fail-to-next-pass count is
{sens['HE_Fail_next_is_HE_Pass_gap_days']['n']:,}, and its median interval is
{sens['HE_Fail_next_is_HE_Pass_gap_days']['median']:.2f} days. This projection skips
administrative results; it is reported separately and does not alter the exports.

## Why object-centric analysis adds value

The recent log links {p['properties']:,} properties, of which
**{p['properties_with_multiple_licenses']:,} ({100*p['properties_with_multiple_licenses']/p['properties']:.1f}%)**
have results for multiple licenses. A property-level trace can thus interleave
different establishments/licenses. Flattening solely by property would conflate
those license processes; OCEL preserves both perspectives and their shared site.
Property IDs are recorded source associations, not inferred ownership.

{p['events_without_property']:,} recent events
({100*p['events_without_property']/s['events']:.1f}%) have no usable property link, so
site-based analyses cover a selected subset. There are
{p['same_property_timestamp_groups_with_ties']:,} property/timestamp groups with
multiple events; their serialization order is not a causal order.

Findings supply codes, severity strings, descriptions, and recorded snapshot
statuses for inspecting result composition. Each finding is a single observation,
not a recurring violation episode. Source row IDs let students inspect the
evidence behind individual result/finding relationships.

## Verification evidence

- Full-source reconciliation passed for both exports, including eligibility,
  outcome/date conservation, row grouping, findings, license attributes, and
  property links: [validation.json](validation.json).
- Qualified graphs have unique IDs, valid references, declared and correctly
  typed attributes, valid timestamps, and no objects disconnected from events.
- PM4Py **{mining[0]['pm4py']['version']}** imported both files with all IDs, E2O/O2O
  qualifiers, event timestamps, and numeric finding counts intact. Its license
  directly-follows graphs match the independent counts exactly:
  {mining[0]['pm4py']['license_dfg_edges']} historical edges and
  {mining[1]['pm4py']['license_dfg_edges']} recent edges.
- The upstream legacy schema's string-only attribute-value constraint was
  corrected to OCEL 2.0 scalar types, then actual values were checked against
  their declarations. This is explicitly recorded, not an unmodified-schema
  validation claim. See [schema provenance](../schemas/provenance.json).
- Independent full rebuilds produced identical compressed bytes for both logs
  and identical source-quality reports: [reproducibility.json](reproducibility.json).
- Every source row is either represented or quarantined, with no overlap or
  omissions: [row-accounting.json](row-accounting.json).
- Regression tests are in [tests](../tests); run `.venv/bin/pytest -q`.

All detailed statistics, directly-follows counts, and auditable example event
IDs are in [process-mining.json](process-mining.json). Quarantined row IDs are in
[source-issues.json.gz](source-issues.json.gz). For modeling assumptions,
snapshot semantics, observation-window truncation, and source limitations, see
[MODEL.md](../docs/MODEL.md).
""")
    (reports / "QUALITY_AND_INSIGHTS.md").write_text("\n".join(sections).rstrip() + "\n")


if __name__ == "__main__":
    main()

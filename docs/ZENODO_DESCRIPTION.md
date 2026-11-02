# Boston Food Establishment Inspection Results and Findings in OCEL 2.0

This dataset contains two object-centric event logs of food-establishment
inspection results in Boston, Massachusetts, USA. Both logs are provided as
gzip-compressed OCEL 2.0 JSON files (`.json.gz`) for process-mining research and
teaching. They connect recorded inspection outcomes to food-establishment
licenses and properties; the detailed log additionally links individual finding
observations to their inspections.

The logs were extracted from the City of Boston's
[Food Establishment Inspections dataset on Analyze Boston](https://data.boston.gov/dataset/food-establishment-inspections),
maintained by the Inspectional Services Department. The extraction uses a frozen
snapshot of 907,385 source rows collected on 2 November 2026.

The two files provide complementary views of the same source:

- **`boston-inspections-history.json.gz`** contains 220,270 events spanning
  4 April 2006 to 31 October 2026, with 18 event types and 236,108 objects:
  220,270 `Inspection` objects, 11,324 `FoodLicense` objects, and 4,514 `Property`
  objects. It supports analysis of longer result sequences and relationships
  between licenses and shared properties.
- **`boston-inspections-findings-2022-2025.json.gz`** contains 60,304 events
  recorded during 2022–2025, with 13 event types and 239,811 objects:
  60,304 `Inspection` objects, 8,341 `FoodLicense` objects, 3,911 `Property`
  objects, and 167,255 `Finding` objects. It supports analysis of inspection
  outcomes together with recorded finding codes, descriptions, severity strings,
  and snapshot statuses.

**The logs overlap and must not be concatenated as independent datasets.** The
detailed log contains the historical log's eligible events for 2022–2025, enriched
with finding objects and relationships. Common events and objects retain the same
identifiers.

The public source does not expose an inspection identifier. Each event is
therefore reconstructed by grouping rows with the same license number and exact
result timestamp. Multiple finding rows become one result event rather than
separate inspections. Activities preserve the source outcome code in the form
`Inspection result: <code>`. Event timestamps are normalized to UTC, retaining
fractional seconds. Qualified event-to-object and object-to-object relationships
express which license was inspected, the recorded property, and which findings
belong to the inspection. Each event and finding retains its contributing source
row identifiers for traceability.

License metadata and finding attributes are explicitly represented as snapshot
observations at extraction time. They are not assumed to describe historical
state at every inspection. Finding objects represent individual recorded
observations; the source provides no stable identifier for linking a violation
episode across inspections. Source row and finding identifiers are specific to
the frozen snapshot.

Quality controls excluded 6,528 source rows (0.72%): 6,398 with missing or unusable
result timestamps, 88 belonging to 20 groups with conflicting outcomes at the
same license and timestamp, and 42 carrying the explicit `DATAERR` result code.
The remaining 900,857 rows form the historical log. Missing property identifiers
do not exclude events; those events retain their license relationships without
an inferred property link.

Validation includes full source-to-export reconciliation, checks of declared
attribute types, timestamps and graph integrity, and PM4Py import and
object-centric directly-follows discovery. Schema validation uses a documented
correction to the legacy OCEL schema's string-only attribute-value constraint.
Independent offline rebuilds produced byte-identical compressed exports.

The logs support outcome-sequence discovery, analysis of intervals to the next
observed result, comparisons of license and property perspectives, and study of
recorded finding composition. Administrative outcomes such as `HE_NotReq` are
retained and include simultaneous batches across licenses. Accordingly, recorded
events should not all be interpreted as on-site visits. Inspection identities
are inferred, observation windows truncate traces, and a subsequent pass does
not establish a remediation episode or repair duration. These data do not
establish food-poisoning incidence or causality.

The [companion repository at the extraction revision](https://github.com/fit-alessandro-berti/chicago-ocel-extraction/tree/ce2ed7c3309f31e0dfcb87e998cec4a0626ce729)
provides extraction and validation code, the checksummed source snapshot,
quarantined-row provenance, reproducibility instructions, and a process-mining
quality report. The frozen source metadata identifies the underlying municipal
dataset's license as the Open Data Commons Public Domain Dedication and License
(PDDL); the repository's software license is separate.

## Acknowledgements

We thank Wil M.P. van der Aalst (wvdaalst@pads.rwth-aachen.de) and
Jean-Christophe Schmitt (jean-christophe.schmitt@rwth-aachen.de) for suggesting
the source data for these event logs. Jean-Christophe Schmitt also performed
an initial extraction.

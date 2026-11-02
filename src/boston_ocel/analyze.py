"""Descriptive process mining with explicit observational denominators."""
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .source import sha256, write_json
from .validate import attrs, check, load


def quantiles(values):
    if not values:
        return {"n": 0}
    v = sorted(values)
    def percentile(p):
        ix = (len(v) - 1) * p
        lo = int(ix)
        return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (ix - lo)
    return {"n": len(v), "median": statistics.median(v),
            "p10": percentile(.1), "p90": percentile(.9), "max": max(v)}


def mine(log):
    by_license = defaultdict(list)
    property_licenses = defaultdict(set)
    property_times = Counter()
    outcomes = Counter()
    codes_by_license = defaultdict(set)
    finding_count = []
    snapshot_status = Counter()
    missing_property = 0
    objects = {o["id"]: o for o in log["objects"]}
    for e in log["events"]:
        a = attrs(e)
        code = a["result_code"]
        outcomes[code] += 1
        license_id = next(r["objectId"] for r in e["relationships"] if r["qualifier"] == "inspected_license")
        by_license[license_id].append(e)
        props = [r["objectId"] for r in e["relationships"] if r["qualifier"] == "recorded_property"]
        missing_property += not props
        for p in props:
            property_licenses[p].add(license_id)
            property_times[(p, e["time"])] += 1
        finding_count.append(a["finding_count"])
        for r in e["relationships"]:
            if r["qualifier"] == "recorded_finding":
                fa = attrs(objects[r["objectId"]])
                codes_by_license[license_id].add(fa["snapshot_violation"])
                snapshot_status[fa.get("snapshot_viol_status", "<missing>")] += 1
    edges = Counter()
    variants = Counter()
    intervals = defaultdict(list)
    next_after_fail = Counter()
    no_next_fail = 0
    pass_next_days = []
    same_day_pairs = 0
    subsecond_pairs = Counter()
    cross_license_batches = defaultdict(set)
    examples = []
    sensitivity_next = Counter()
    sensitivity_days = []
    sensitivity_no_next = 0
    only_notreq = 0
    for lid, events in sorted(by_license.items()):
        events.sort(key=lambda e: (datetime.fromisoformat(e["time"]), e["id"]))
        codes = [attrs(e)["result_code"] for e in events]
        variants[tuple(codes)] += 1
        for e in events:
            cross_license_batches[(e["time"], attrs(e)["result_code"])].add(lid)
        for first, second in zip(events, events[1:]):
            a, b = attrs(first)["result_code"], attrs(second)["result_code"]
            days = (datetime.fromisoformat(second["time"]) - datetime.fromisoformat(first["time"])).total_seconds() / 86400
            check(days > 0, "Nonpositive same-license interval")
            edges[(a, b)] += 1
            intervals[a].append(days)
            same_day_pairs += days < 1
            if days < 1 / 86400:
                subsecond_pairs[(a, b)] += 1
            if a == "HE_Fail":
                next_after_fail[b] += 1
                if b == "HE_Pass":
                    pass_next_days.append(days)
                    if len(examples) < 5:
                        examples.append({"license": lid, "first_event": first["id"], "next_event": second["id"],
                                         "first_time": first["time"], "next_time": second["time"], "gap_days": days})
        if codes[-1] == "HE_Fail":
            no_next_fail += 1
        filtered = [e for e in events if attrs(e)["result_code"] != "HE_NotReq"]
        if not filtered:
            only_notreq += 1
        for first, second in zip(filtered, filtered[1:]):
            if attrs(first)["result_code"] == "HE_Fail":
                outcome = attrs(second)["result_code"]
                sensitivity_next[outcome] += 1
                if outcome == "HE_Pass":
                    sensitivity_days.append((datetime.fromisoformat(second["time"]) -
                                             datetime.fromisoformat(first["time"])).total_seconds() / 86400)
        if filtered and attrs(filtered[-1])["result_code"] == "HE_Fail":
            sensitivity_no_next += 1
    total = len(log["events"])
    return {"events": total, "licenses": len(by_license), "activity_counts": dict(outcomes),
            "events_per_license": quantiles([len(v) for v in by_license.values()]),
            "licenses_with_multiple_events": sum(len(v) > 1 for v in by_license.values()),
            "distinct_license_variants": len(variants),
            "top_variants": [{"activities": list(v), "licenses": n} for v, n in variants.most_common(10)],
            "license_directly_follows": [{"from": a, "to": b, "count": n} for (a, b), n in edges.most_common()],
            "next_observed_result_gap_days_by_current_code": {k: quantiles(v) for k, v in sorted(intervals.items())},
            "HE_Fail_cohort": {"total_events": outcomes["HE_Fail"],
                               "next_observed_outcomes": dict(next_after_fail), "no_next_in_log": no_next_fail,
                               "next_is_HE_Pass_gap_days": quantiles(pass_next_days),
                               "next_is_HE_Pass_within_30_days": sum(d <= 30 for d in pass_next_days)},
            "property_analysis": {"properties": len(property_licenses),
                                  "properties_with_multiple_licenses": sum(len(v) > 1 for v in property_licenses.values()),
                                  "licenses_per_property": quantiles([len(v) for v in property_licenses.values()]),
                                  "events_without_property": missing_property,
                                  "same_property_timestamp_groups_with_ties": sum(n > 1 for n in property_times.values())},
            "finding_count_per_inspection": quantiles(finding_count),
            "finding_snapshot_status_counts": dict(snapshot_status),
            "successive_same_license_events_less_than_one_day_apart": same_day_pairs,
            "subsecond_same_license_pairs": [{"from": a, "to": b, "count": n}
                                             for (a, b), n in subsecond_pairs.most_common()],
            "largest_cross_license_same_timestamp_batches": [
                {"time": t, "result": code, "licenses": len(ids)}
                for (t, code), ids in sorted(cross_license_batches.items(), key=lambda v: (-len(v[1]), v[0]))[:10]],
            "HE_NotReq_removed_sensitivity": {
                "removed_events": outcomes["HE_NotReq"], "remaining_events": total - outcomes["HE_NotReq"],
                "licenses_with_only_HE_NotReq": only_notreq, "remaining_licenses": len(by_license) - only_notreq,
                "HE_Fail_next_observed_outcomes": dict(sensitivity_next),
                "HE_Fail_no_next_in_filtered_log": sensitivity_no_next,
                "HE_Fail_next_is_HE_Pass_gap_days": quantiles(sensitivity_days),
                "interpretation": "Analytical projection only: bridges HE_NotReq entries; original logs retain all source result codes except DATAERR."},
            "auditable_fail_to_next_pass_examples": examples}


def pm4py_check(path, log, stats):
    import pm4py
    ocel = pm4py.read_ocel2_json(str(path))
    check(set(ocel.events["ocel:eid"]) == {e["id"] for e in log["events"]}, "PM4Py event IDs differ")
    check(set(ocel.objects["ocel:oid"]) == {o["id"] for o in log["objects"]}, "PM4Py object IDs differ")
    check(set(ocel.relations[["ocel:eid", "ocel:oid", "ocel:qualifier"]].itertuples(index=False, name=None)) ==
          {(e["id"], r["objectId"], r["qualifier"]) for e in log["events"] for r in e["relationships"]},
          "PM4Py event-object relations differ")
    check(set(ocel.o2o[["ocel:oid", "ocel:oid_2", "ocel:qualifier"]].itertuples(index=False, name=None)) ==
          {(o["id"], r["objectId"], r["qualifier"]) for o in log["objects"] for r in o["relationships"]},
          "PM4Py object-object relations differ")
    for e in log["events"]:
        # Full event attribute checks are performed in vectorized form below.
        check(bool(e["relationships"]), "Objectless event")
    indexed = ocel.events.set_index("ocel:eid")
    check(indexed["finding_count"].to_dict() == {e["id"]: attrs(e)["finding_count"] for e in log["events"]},
          "PM4Py integer attributes differ")
    check({k: v.isoformat().replace("+00:00", "Z") for k, v in indexed["ocel:timestamp"].items()} ==
          {e["id"]: e["time"] for e in log["events"]}, "PM4Py event times differ")
    model = pm4py.discover_ocdfg(ocel, compute_edges_performance=False)
    discovered = model["edges"]["event_couples"]["FoodLicense"]
    expected = {("Inspection result: " + e["from"], "Inspection result: " + e["to"]): e["count"]
                for e in stats["license_directly_follows"]}
    check({k: len(v) for k, v in discovered.items()} == expected, "PM4Py DFG differs from independent analysis")
    return {"version": pm4py.__version__, "status": "pass", "events": len(ocel.events),
            "objects": len(ocel.objects), "event_object_relations": len(ocel.relations),
            "object_object_relations": len(ocel.o2o), "license_dfg_edges": len(discovered),
            "note": "Import and DFG checks; not a lossless temporal-attribute round trip. PM4Py treats first object observations as baseline attributes."}


def analyze_all(output=Path("data/ocel"), reports=Path("reports"), with_pm4py=False):
    output, reports = Path(output), Path(reports)
    manifest = json.loads((output / "manifest.json").read_text())
    results = []
    for artifact in manifest["artifacts"]:
        path = output / artifact["file"]
        print(f"Mining {path.name}…", flush=True)
        check(sha256(path) == artifact["sha256"], "Artifact hash mismatch")
        log = load(path)
        stats = mine(log)
        result = {"file": path.name, "sha256": sha256(path), "statistics": stats}
        if with_pm4py:
            print("Checking PM4Py import and object-centric directly-follows discovery…", flush=True)
            result["pm4py"] = pm4py_check(path, log, stats)
        results.append(result)
        del log
    write_json(reports / "process-mining.json", results)
    return results

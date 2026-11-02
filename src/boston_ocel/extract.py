"""Conservative reconstruction: source result groups, never one event per row."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .source import iter_rows, sha256, write_gzip, write_json

EPOCH = "1970-01-01T00:00:00Z"


def timestamp(value):
    if not value:
        raise ValueError("Missing timestamp")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Naive source timestamp")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def text(value):
    return "" if value is None else str(value).strip()


def property_id(value):
    value = text(value)
    return value if value.isdigit() and int(value) > 0 else None


def inspection_id(license_no, time):
    return "inspection:" + hashlib.sha256(json.dumps([license_no, time]).encode()).hexdigest()[:24]


def attributes(values, at=None):
    return [{"name": k, "value": v, **({"time": at} if at else {})}
            for k, v in sorted(values.items()) if v is not None and v != ""]


def relation(oid, qualifier):
    return {"objectId": oid, "qualifier": qualifier}


def object_record(oid, kind, values, at=EPOCH, relationships=()):
    return {"id": oid, "type": kind, "attributes": attributes(values, at),
            "relationships": list(relationships)}


def types(records):
    declarations = defaultdict(dict)
    for record in records:
        decl = declarations[record["type"]]
        for a in record["attributes"]:
            t = {str: "string", int: "integer", float: "float", bool: "boolean"}[type(a["value"])]
            if a["name"] in decl and decl[a["name"]] != t:
                raise ValueError("Inconsistent attribute types")
            decl[a["name"]] = t
    return [{"name": k, "attributes": [{"name": n, "type": t} for n, t in sorted(v.items())]}
            for k, v in sorted(declarations.items())]


def prepare(rows, snapshot_at):
    groups = defaultdict(list)
    quality = Counter()
    issues = []
    profile = {k: Counter() for k in ["source_result_codes", "source_years",
               "violation_time_vs_result", "status_time_vs_result", "source_violation_status"]}
    snapshot_dt = datetime.fromisoformat(snapshot_at)
    for r in rows:
        quality["source_rows"] += 1
        profile["source_result_codes"][text(r.get("result")) or "<missing>"] += 1
        profile["source_violation_status"][text(r.get("viol_status")) or "<missing>"] += 1
        reason = None
        if not text(r.get("licenseno")):
            reason = "missing_license"
        try:
            time = timestamp(r.get("resultdttm"))
            if datetime.fromisoformat(time) > snapshot_dt:
                reason = "future_result_time"
        except (ValueError, TypeError):
            reason = reason or "missing_or_invalid_result_time"
        if reason:
            quality["excluded_rows"] += 1
            quality[reason] += 1
            issues.append({"source_row_ids": [r["_id"]], "reason": reason})
            continue
        profile["source_years"][time[:4]] += 1
        for field, target in [("violdttm", "violation_time_vs_result"),
                               ("status_date", "status_time_vs_result")]:
            try:
                other = timestamp(r.get(field))
                label = "equal" if other == time else "before" if datetime.fromisoformat(other) < datetime.fromisoformat(time) else "after"
            except (ValueError, TypeError):
                label = "missing_or_invalid"
            profile[target][label] += 1
        groups[(text(r["licenseno"]), time)].append(r)
    accepted = []
    for (license_no, time), source in sorted(groups.items()):
        outcomes = {text(r.get("result")) for r in source}
        reason = "conflicting_results_at_same_license_time" if len(outcomes) > 1 else (
            "missing_result" if not next(iter(outcomes)) else
            "source_result_data_error" if outcomes == {"DATAERR"} else None)
        if reason:
            quality["excluded_rows"] += len(source)
            quality[reason + "_rows"] += len(source)
            quality[reason + "_groups"] += 1
            issues.append({"source_row_ids": sorted(r["_id"] for r in source),
                           "reason": reason, "license": license_no, "time": time,
                           "results": sorted(outcomes)})
            continue
        distinct = {}
        for row in source:
            # Collapse only exact duplicates, ignoring the transport row ID.
            key = json.dumps({k: v for k, v in row.items() if k != "_id"}, sort_keys=True)
            if key not in distinct:
                distinct[key] = {"row": row, "ids": []}
            distinct[key]["ids"].append(row["_id"])
        quality["exact_duplicate_rows"] += len(source) - len(distinct)
        quality["accepted_rows"] += len(source)
        quality["inspection_groups"] += 1
        properties = {property_id(r.get("property_id")) for r in source}
        properties.discard(None)
        prop = next(iter(properties)) if len(properties) == 1 else None
        if len(properties) > 1:
            quality["conflicting_property_groups"] += 1
            issues.append({"source_row_ids": sorted(r["_id"] for r in source),
                           "reason": "property_link_omitted_conflicting_ids"})
        if not prop:
            quality["inspection_groups_without_property"] += 1
        findings = [v for v in distinct.values() if text(v["row"].get("violation"))]
        quality["distinct_finding_rows"] += len(findings)
        quality["distinct_rows_without_finding_code"] += len(distinct) - len(findings)
        accepted.append({"id": inspection_id(license_no, time), "license": license_no,
                         "time": time, "result": next(iter(outcomes)), "property": prop,
                         "source": source, "distinct": list(distinct.values()), "findings": findings})
    if quality["source_rows"] != quality["accepted_rows"] + quality["excluded_rows"]:
        raise ValueError("Row accounting failed")
    return accepted, {"counts": dict(quality), "profile": profile, "issues": issues}


def build_log(groups, snapshot_at, detailed=False):
    objects, events = {}, []
    license_rows = defaultdict(list)
    for g in groups:
        iid = g["id"]
        lid = "license:" + g["license"]
        pid = "property:" + g["property"] if g["property"] else None
        license_rows[lid].extend(g["source"])
        rels = [relation(lid, "inspected_license"), relation(iid, "inspection")]
        orels = [relation(lid, "inspected_license")]
        if pid:
            rels.append(relation(pid, "recorded_property"))
            orels.append(relation(pid, "recorded_property"))
            objects[pid] = object_record(pid, "Property", {"property_id": g["property"]})
        objects[iid] = object_record(iid, "Inspection", {
            "identity_method": "license_number + resultdttm (inferred)",
            "source_result_time": g["source"][0]["resultdttm"]}, relationships=orels)
        if detailed:
            for finding in g["findings"]:
                row, ids = finding["row"], sorted(finding["ids"])
                fid = "finding:" + str(min(ids))
                values = {"source_row_ids": ",".join(map(str, ids))}
                values.update({"snapshot_" + k: row.get(k) for k in [
                    "violation", "viol_level", "violdesc", "violdttm", "viol_status", "status_date"]})
                objects[fid] = object_record(fid, "Finding", values, snapshot_at,
                                             [relation(iid, "finding_of")])
                rels.append(relation(fid, "recorded_finding"))
        events.append({"id": "event:" + iid.split(":")[1],
                       "type": "Inspection result: " + g["result"], "time": g["time"],
                       "attributes": attributes({
                           "result_code": g["result"],
                           "source_row_ids": ",".join(map(str, sorted(r["_id"] for r in g["source"]))),
                           "source_row_count": len(g["source"]),
                           "distinct_row_count": len(g["distinct"]),
                           "finding_count": len(g["findings"]),
                           "snapshot_failing_finding_count": sum(
                               f["row"].get("viol_status") == "Fail" for f in g["findings"]),
                           "snapshot_passing_finding_count": sum(
                               f["row"].get("viol_status") == "Pass" for f in g["findings"]),
                       }), "relationships": rels})
    omitted = Counter()
    for lid, source in sorted(license_rows.items()):
        obj = object_record(lid, "FoodLicense", {"license_number": lid.split(":")[1]})
        values = {}
        for k in ["businessname", "dbaname", "licensecat", "descript", "licstatus",
                  "issdttm", "expdttm", "address", "city", "state", "zip"]:
            vals = {text(r.get(k)) for r in source} - {""}
            if len(vals) == 1:
                values["snapshot_" + k] = next(iter(vals))
            elif len(vals) > 1:
                omitted[k] += 1
        obj["attributes"].extend(attributes(values, snapshot_at))
        objects[lid] = obj
    objs = sorted(objects.values(), key=lambda o: o["id"])
    events.sort(key=lambda e: (datetime.fromisoformat(e["time"]), e["id"]))
    log = {"objectTypes": types(objs), "eventTypes": types(events), "objects": objs, "events": events}
    return log, dict(omitted)


def extract(raw=Path("data/raw"), output=Path("data/ocel"), reports=Path("reports")):
    raw, output, reports = Path(raw), Path(output), Path(reports)
    manifest = json.loads((raw / "manifest.json").read_text())
    at = timestamp(manifest["finished_at"])
    print("Checking source checksums and reconstructing inspections…", flush=True)
    groups, quality = prepare(iter_rows(raw), at)
    issues = quality.pop("issues")
    write_gzip(reports / "source-issues.json.gz", issues)
    quality["snapshot_manifest_sha256"] = sha256(raw / "manifest.json")
    quality["snapshot_at"] = at
    write_json(reports / "source-quality.json", quality)
    specs = [("boston-inspections-history", groups, False),
             ("boston-inspections-findings-2022-2025",
              [g for g in groups if "2022" <= g["time"][:4] <= "2025"], True)]
    artifacts = []
    for name, selected, detailed in specs:
        print(f"Building {name}: {len(selected):,} inspection events…", flush=True)
        log, omitted = build_log(selected, at, detailed)
        path = output / (name + ".json.gz")
        write_gzip(path, log)
        artifacts.append({"file": path.name, "sha256": sha256(path), "bytes": path.stat().st_size,
                          "events": len(log["events"]), "objects": len(log["objects"]),
                          "event_types": len(log["eventTypes"]),
                          "object_counts": dict(Counter(o["type"] for o in log["objects"])),
                          "source_rows": sum(len(g["source"]) for g in selected),
                          "start": log["events"][0]["time"], "end": log["events"][-1]["time"],
                          "conflicting_snapshot_fields_omitted_per_license": omitted})
        del log
    write_json(output / "manifest.json", {"snapshot_manifest_sha256": sha256(raw / "manifest.json"),
                                         "artifacts": artifacts})
    return artifacts

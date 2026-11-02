"""Schema, semantic integrity, and independent source-to-export reconciliation."""
import copy
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker

from .source import iter_rows, sha256, write_json


def attrs(record):
    return {a["name"]: a["value"] for a in record["attributes"]}


def load(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def canonical_time(value):
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() is None:
        raise ValueError("Missing timezone")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def check(condition, message):
    if not condition:
        raise ValueError(message)


def validate_log(log, schema_path=Path("schemas/ocel20-schema-json.json")):
    schema = copy.deepcopy(json.loads(Path(schema_path).read_text()))
    # The upstream legacy schema restricts *all* values to strings despite
    # OCEL 2.0 specifying typed scalar attributes. Correct only these two leaves;
    # check each actual value against its declared type below.
    for kind in ["events", "objects"]:
        schema["properties"][kind]["items"]["properties"]["attributes"]["items"]["properties"]["value"] = {
            "type": ["string", "number", "boolean"]}
    Draft7Validator(schema, format_checker=FormatChecker()).validate(log)
    oids = {o["id"] for o in log["objects"]}
    check(len(oids) == len(log["objects"]), "Duplicate object ID")
    check(len({e["id"] for e in log["events"]}) == len(log["events"]), "Duplicate event ID")
    linked = set()
    relation_counts = Counter()
    for collection, declarations in [("events", "eventTypes"), ("objects", "objectTypes")]:
        declared = {}
        for t in log[declarations]:
            check(t["name"] not in declared, "Duplicate type declaration")
            fields = {a["name"]: a["type"] for a in t["attributes"]}
            check(len(fields) == len(t["attributes"]), "Duplicate attribute declaration")
            check(set(fields.values()) <= {"string", "integer", "float", "boolean", "time"},
                  "Unknown OCEL primitive type")
            declared[t["name"]] = fields
        for r in log[collection]:
            check(r["type"] in declared, "Undeclared record type")
            used = set()
            for a in r["attributes"]:
                key = (a["name"], a.get("time"))
                check(key not in used, "Duplicate attribute observation")
                used.add(key)
                check(a["name"] in declared[r["type"]], "Undeclared attribute")
                dtype = declared[r["type"]][a["name"]]
                v = a["value"]
                valid = {"string": type(v) is str, "integer": type(v) is int,
                         "float": type(v) in (float, int), "boolean": type(v) is bool,
                         "time": type(v) is str}[dtype]
                check(valid, f"Wrong value type: {a['name']}")
                if dtype == "time":
                    canonical_time(v)
            edges = [(edge["objectId"], edge["qualifier"]) for edge in r["relationships"]]
            check(len(edges) == len(set(edges)), "Duplicate relationship")
            for target, qualifier in edges:
                check(target in oids, "Dangling relationship")
                check(bool(qualifier), "Empty qualifier")
                relation_counts[collection] += 1
                if collection == "events":
                    linked.add(target)
    check(linked == oids, "Objects without event relationships")
    check(log["events"] == sorted(log["events"], key=lambda e: (datetime.fromisoformat(e["time"]), e["id"])),
          "Events not deterministically sorted")
    return {"schema": "pass (upstream string-only value constraint corrected to OCEL typed scalars)",
            "semantic_integrity": "pass", "events": len(log["events"]),
            "objects": len(oids), "event_object_relations": relation_counts["events"],
            "object_object_relations": relation_counts["objects"],
            "schema_sha256": sha256(schema_path)}


def validate_source(log, raw, detailed=False):
    """Reconcile every exported row reference and every eligible source group.

    Does not call the extractor's prepare/build functions. Uses original rows,
    independently grouped, to detect both silent omissions and invented records.
    """
    raw = Path(raw)
    manifest = json.loads((raw / "manifest.json").read_text())
    at = canonical_time(manifest["finished_at"])
    objects = {o["id"]: o for o in log["objects"]}
    event_by_row, finding_by_row, event_by_key = {}, {}, {}
    license_snapshots = defaultdict(lambda: defaultdict(set))
    license_fields = ["businessname", "dbaname", "licensecat", "descript", "licstatus",
                      "issdttm", "expdttm", "address", "city", "state", "zip"]
    for event in log["events"]:
        a = attrs(event)
        target_types = {"inspected_license": "FoodLicense", "inspection": "Inspection",
                        "recorded_property": "Property", "recorded_finding": "Finding"}
        for rel in event["relationships"]:
            check(rel["qualifier"] in target_types, "Unexpected event qualifier")
            check(objects[rel["objectId"]]["type"] == target_types[rel["qualifier"]], "Wrong relationship target type")
        ids = [int(i) for i in a["source_row_ids"].split(",")]
        check(len(ids) == a["source_row_count"], "Wrong source row count")
        licenses = [r["objectId"] for r in event["relationships"] if r["qualifier"] == "inspected_license"]
        check(len(licenses) == 1, "Inspection must reference exactly one license")
        key = (attrs(objects[licenses[0]])["license_number"], event["time"])
        check(key not in event_by_key, "Duplicate reconstructed inspection")
        event_by_key[key] = event
        for rid in ids:
            check(rid not in event_by_row, "Row used in multiple events")
            event_by_row[rid] = event
        inspection = [r["objectId"] for r in event["relationships"] if r["qualifier"] == "inspection"]
        check(len(inspection) == 1, "Inspection identity missing")
        iobj = objects[inspection[0]]
        check(iobj["type"] == "Inspection", "Wrong inspection object type")
        check({(r["objectId"], r["qualifier"]) for r in iobj["relationships"]} ==
              {(r["objectId"], r["qualifier"]) for r in event["relationships"]
               if r["qualifier"] in {"inspected_license", "recorded_property"}},
              "Inspection O2O does not agree with event E2O")
        linked_findings = [r["objectId"] for r in event["relationships"] if r["qualifier"] == "recorded_finding"]
        check(len(linked_findings) == (a["finding_count"] if detailed else 0), "Wrong finding count")
        for fid in linked_findings:
            obj = objects[fid]
            check(obj["type"] == "Finding", "Wrong finding object type")
            check(obj["relationships"] == [{"objectId": inspection[0], "qualifier": "finding_of"}],
                  "Finding belongs to wrong inspection")
            for rid in map(int, attrs(obj)["source_row_ids"].split(",")):
                check(rid in ids and rid not in finding_by_row, "Wrong or duplicate finding provenance")
                finding_by_row[rid] = obj
    groups = {}
    seen_ids = set()
    for row in iter_rows(raw):
        rid = row["_id"]
        try:
            t = canonical_time(row["resultdttm"])
            valid = bool(row["licenseno"] and str(row["licenseno"]).strip()) and datetime.fromisoformat(t) <= datetime.fromisoformat(at)
            valid = valid and (not detailed or "2022" <= t[:4] <= "2025")
        except (TypeError, ValueError):
            valid = False
        if not valid:
            check(rid not in event_by_row, "Invalid or out-of-scope source row emitted")
            continue
        key = (str(row["licenseno"]).strip(), t)
        g = groups.setdefault(key, {"results": set(), "ids": set(), "properties": set(),
                                    "unique": set(), "findings": set(), "fail": set(), "pass": set()})
        g["results"].add(str(row["result"] or "").strip())
        g["ids"].add(rid)
        prop = str(row["property_id"] or "").strip()
        if prop.isdigit() and int(prop) > 0:
            g["properties"].add("property:" + prop)
        fingerprint = hashlib.sha256(json.dumps({k: v for k, v in row.items() if k != "_id"},
                                                sort_keys=True).encode()).digest()
        g["unique"].add(fingerprint)
        if str(row["violation"] or "").strip():
            g["findings"].add(fingerprint)
            if row["viol_status"] in ["Fail", "Pass"]:
                g[row["viol_status"].lower()].add(fingerprint)
        if rid in event_by_row:
            event = event_by_row[rid]
            check(event_by_key.get(key) is event, "Source license/time changed")
            check(attrs(event)["result_code"] == row["result"].strip(), "Source outcome changed")
            check(event["type"] == "Inspection result: " + row["result"].strip(), "Activity label changed")
            seen_ids.add(rid)
            for field in license_fields:
                value = str(row.get(field) or "").strip()
                if value:
                    license_snapshots["license:" + key[0]][field].add(value)
            if detailed and str(row["violation"] or "").strip():
                check(rid in finding_by_row, "Finding row omitted")
                obj = finding_by_row[rid]
                fa = attrs(obj)
                for field in ["violation", "viol_level", "violdesc", "violdttm", "viol_status", "status_date"]:
                    check(fa.get("snapshot_" + field, "") == (row[field] or ""), "Finding value changed")
                check(all(a["time"] == at for a in obj["attributes"]), "Finding snapshot backdated")
            else:
                check(rid not in finding_by_row, "Invented finding")
    check(seen_ids == set(event_by_row), "Export references nonexistent source rows")
    expected = 0
    for key, g in groups.items():
        good = len(g["results"]) == 1 and not g["results"] & {"", "DATAERR"}
        check((key in event_by_key) == good, "Missing eligible inspection or ambiguous inspection emitted")
        if not good:
            continue
        expected += 1
        e = event_by_key[key]
        a = attrs(e)
        check(set(map(int, a["source_row_ids"].split(","))) == g["ids"], "Source group not conserved")
        check(a["distinct_row_count"] == len(g["unique"]), "Wrong deduplication")
        check(a["finding_count"] == len(g["findings"]), "Wrong source finding count")
        check(a["snapshot_failing_finding_count"] == len(g["fail"]), "Wrong failing finding count")
        check(a["snapshot_passing_finding_count"] == len(g["pass"]), "Wrong passing finding count")
        actual_properties = {r["objectId"] for r in e["relationships"] if r["qualifier"] == "recorded_property"}
        check(actual_properties == (g["properties"] if len(g["properties"]) == 1 else set()),
              "Invented or missing property link")
    check(expected == len(log["events"]), "Unexpected events")
    for obj in log["objects"]:
        if obj["type"] == "FoodLicense":
            values = {"license_number": obj["id"].split(":")[1]}
            for field, variants in license_snapshots[obj["id"]].items():
                if len(variants) == 1:
                    values["snapshot_" + field] = next(iter(variants))
            check(attrs(obj) == values, "License snapshot differs from source")
            for a in obj["attributes"]:
                check(a["time"] == ("1970-01-01T00:00:00Z" if a["name"] == "license_number" else at),
                      "License snapshot backdated")
        elif obj["type"] == "Property":
            check(attrs(obj) == {"property_id": obj["id"].split(":")[1]}, "Property identifier changed")
    return {"status": "pass", "source_rows_reconciled": len(seen_ids),
            "inspection_groups_reconciled": expected, "finding_rows_reconciled": len(finding_by_row)}


def validate_all(raw=Path("data/raw"), output=Path("data/ocel"), reports=Path("reports")):
    output, reports = Path(output), Path(reports)
    manifest = json.loads((output / "manifest.json").read_text())
    check(manifest["snapshot_manifest_sha256"] == sha256(Path(raw) / "manifest.json"), "Snapshot changed")
    results = []
    for artifact in manifest["artifacts"]:
        path = output / artifact["file"]
        print(f"Validating {path.name}…", flush=True)
        check(sha256(path) == artifact["sha256"], "Artifact checksum mismatch")
        log = load(path)
        result = {"file": path.name, "sha256": artifact["sha256"], **validate_log(log)}
        result["source_reconciliation"] = validate_source(log, raw, "findings" in path.name)
        check(result["events"] == artifact["events"] and result["objects"] == artifact["objects"],
              "Manifest counts differ")
        results.append(result)
        del log
    write_json(reports / "validation.json", results)
    return results

import copy
import gzip
import json

import pytest

from boston_ocel.extract import build_log, prepare, timestamp
from boston_ocel.source import write_gzip, write_json, sha256
from boston_ocel.validate import attrs, validate_log, validate_source

AT = "2026-11-02T07:15:53Z"


def row(rid, **changes):
    data = dict(_id=rid, licenseno="001", resultdttm="2024-03-01 12:30:00+00",
                result="HE_Fail", property_id="42", violation="A", viol_status="Fail",
                violdttm="2024-03-01 12:30:00+00", status_date=None,
                viol_level="**", violdesc="Example", businessname="Test", licensecat="FS")
    data.update(changes)
    return data


def make_log(rows):
    groups, quality = prepare(rows, AT)
    log, _ = build_log(groups, AT, detailed=True)
    return log, quality


def test_source_rows_are_findings_not_repeated_inspections():
    log, quality = make_log([row(1), row(2, violation="B")])
    assert len(log["events"]) == 1
    assert attrs(log["events"][0])["finding_count"] == 2
    assert quality["counts"]["accepted_rows"] == 2
    assert len([o for o in log["objects"] if o["type"] == "Finding"]) == 2
    validate_log(log)


def test_missing_timestamp_never_falls_back_to_finding_or_license_date():
    log, q = make_log([row(1, resultdttm=None), row(2)])
    assert q["counts"]["excluded_rows"] == 1
    assert attrs(log["events"][0])["source_row_ids"] == "2"


def test_timezone_normalization_groups_same_instant_and_preserves_license_zeros():
    log, q = make_log([row(1), row(2, resultdttm="2024-03-01T07:30:00-05:00", violation="B")])
    assert len(log["events"]) == 1
    assert "license:001" in {o["id"] for o in log["objects"]}
    assert timestamp("2024-07-01T09:00:00-04:00") == "2024-07-01T13:00:00Z"
    with pytest.raises(ValueError):
        timestamp("2024-01-01 12:00:00")


def test_fractional_seconds_sorted_chronologically_not_lexicographically():
    log, _ = make_log([row(1, resultdttm="2024-03-01T12:30:00.003Z"), row(2)])
    assert [e["time"] for e in log["events"]] == ["2024-03-01T12:30:00Z", "2024-03-01T12:30:00.003000Z"]
    validate_log(log)


def test_ambiguous_outcomes_quarantined_as_whole_group():
    log, q = make_log([row(1), row(2, result="HE_Pass"), row(3, licenseno="002")])
    assert len(log["events"]) == 1
    assert q["counts"]["conflicting_results_at_same_license_time_rows"] == 2
    assert attrs(log["events"][0])["source_row_ids"] == "3"


def test_zero_missing_and_conflicting_property_ids_do_not_merge_unknown_sites():
    for props in [(None, "0"), ("42", "43")]:
        log, _ = make_log([row(1, property_id=props[0]), row(2, property_id=props[1])])
        assert not any(o["type"] == "Property" for o in log["objects"])


def test_exact_duplicate_finding_retains_all_provenance():
    log, q = make_log([row(1), row(2)])
    assert q["counts"]["exact_duplicate_rows"] == 1
    finding = next(o for o in log["objects"] if o["type"] == "Finding")
    assert attrs(finding)["source_row_ids"] == "1,2"
    assert attrs(log["events"][0])["finding_count"] == 1


def test_null_violation_and_pass_status_are_not_fabricated_violations_or_repairs():
    log, _ = make_log([row(1, violation=None), row(2, viol_status="Pass", status_date="2025-01-01")])
    assert len(log["events"]) == 1
    assert attrs(log["events"][0])["finding_count"] == 1
    finding = next(o for o in log["objects"] if o["type"] == "Finding")
    assert all(a["time"] == AT for a in finding["attributes"])


@pytest.mark.parametrize("field,value", [("resultdttm", "2030-01-01T00:00:00Z"),
                                         ("result", None), ("result", "DATAERR"), ("licenseno", None)])
def test_invalid_rows_are_accounted_for(field, value):
    log, q = make_log([row(1, **{field: value}), row(2, licenseno="002")])
    assert q["counts"]["source_rows"] == 2
    assert q["counts"]["accepted_rows"] == q["counts"]["excluded_rows"] == 1


def test_validator_rejects_dangling_edges_duplicate_ids_and_wrong_types():
    original, _ = make_log([row(1)])
    bad = copy.deepcopy(original)
    bad["events"][0]["relationships"][0]["objectId"] = "missing"
    with pytest.raises(ValueError, match="Dangling"):
        validate_log(bad)
    bad = copy.deepcopy(original)
    bad["objects"].append(bad["objects"][0])
    with pytest.raises(ValueError, match="Duplicate object"):
        validate_log(bad)
    bad = copy.deepcopy(original)
    next(a for a in bad["events"][0]["attributes"] if a["name"] == "finding_count")["value"] = "1"
    with pytest.raises(ValueError, match="Wrong value type"):
        validate_log(bad)


def test_gzip_output_is_byte_reproducible(tmp_path):
    log, _ = make_log([row(1)])
    a, b = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    write_gzip(a, log)
    write_gzip(b, log)
    assert sha256(a) == sha256(b)
    assert json.load(gzip.open(a, "rt")) == log


def test_independent_reconciliation_rejects_silent_omissions_and_changed_findings(tmp_path):
    rows = [row(1), row(2, violation="B"), row(3, licenseno="002"),
            row(4, licenseno="003", resultdttm=None)]
    log, _ = make_log(rows)
    write_json(tmp_path / "food-inspections.package.json", {})
    write_gzip(tmp_path / "page.json.gz", {"result": {"records": rows}})
    write_json(tmp_path / "manifest.json", {
        "finished_at": AT, "total_rows": len(rows),
        "package_sha256": sha256(tmp_path / "food-inspections.package.json"),
        "pages": [{"file": "page.json.gz", "rows": len(rows), "sha256": sha256(tmp_path / "page.json.gz")}]})
    assert validate_source(log, tmp_path, detailed=True)["source_rows_reconciled"] == 3
    bad = copy.deepcopy(log)
    bad["events"].pop()
    with pytest.raises(ValueError, match="Missing eligible inspection"):
        validate_source(bad, tmp_path, detailed=True)
    bad = copy.deepcopy(log)
    f = next(o for o in bad["objects"] if o["type"] == "Finding")
    next(a for a in f["attributes"] if a["name"] == "snapshot_violation")["value"] = "invented"
    with pytest.raises(ValueError, match="Finding value changed"):
        validate_source(bad, tmp_path, detailed=True)

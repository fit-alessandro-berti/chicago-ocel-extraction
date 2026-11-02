"""Rebuild from the frozen source and audit complete row accounting."""
import json
import platform
import tempfile
import zlib
from pathlib import Path

from boston_ocel.extract import extract
from boston_ocel.source import iter_rows, sha256, write_json
from boston_ocel.validate import attrs, check, load


def main():
    pairs = []
    with tempfile.TemporaryDirectory(prefix="boston-ocel-rebuild-") as tmp:
        tmp = Path(tmp)
        extract(output=tmp / "ocel", reports=tmp / "reports")
        manifest = json.loads(Path("data/ocel/manifest.json").read_text())
        for artifact in manifest["artifacts"]:
            path = Path("data/ocel") / artifact["file"]
            rebuilt = tmp / "ocel" / artifact["file"]
            check(sha256(path) == sha256(rebuilt) == artifact["sha256"], "Rebuild differs")
            pairs.append({"file": str(path), "sha256": sha256(path), "independent_rebuild_matches": True})
        for name in ["source-quality.json", "source-issues.json.gz"]:
            check(sha256(Path("reports") / name) == sha256(tmp / "reports" / name), "Source report differs")
    write_json("reports/reproducibility.json", {
        "status": "pass", "method": "Independent full offline extraction into a separate output directory; byte-for-byte SHA-256 comparison of both logs and both source quality reports.",
        "python": platform.python_version(), "zlib": zlib.ZLIB_VERSION, "artifacts": pairs,
        "source_reports_identical": True})
    log = load("data/ocel/boston-inspections-history.json.gz")
    accepted = {int(i) for e in log["events"] for i in attrs(e)["source_row_ids"].split(",")}
    del log
    issues = load("reports/source-issues.json.gz")
    excluded_list = [i for issue in issues for i in issue["source_row_ids"]]
    excluded = set(excluded_list)
    source = {r["_id"] for r in iter_rows()}
    check(not accepted & excluded, "Rows both accepted and quarantined")
    check(len(excluded) == len(excluded_list), "Rows duplicated in quarantine")
    check(accepted | excluded == source, "Source rows not fully accounted for")
    write_json("reports/row-accounting.json", {"status": "pass", "source_rows": len(source),
               "accepted_rows": len(accepted), "quarantined_rows": len(excluded),
               "unaccounted_rows": 0, "overlapping_rows": 0})
    print("Reproducibility and row accounting passed")


if __name__ == "__main__":
    main()

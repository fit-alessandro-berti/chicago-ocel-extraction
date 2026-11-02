"""Freeze complete CKAN API responses, including source row identifiers."""
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RESOURCE = "4582bec6-2b4f-4f9e-bc55-cbaa73117f4c"
API = "https://data.boston.gov/api/3/action/"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_gzip(path, value):
    """Deterministic gzip: no wall-clock timestamp or filename in header."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:
        encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        for chunk in encoder.iterencode(value):
            f.write(chunk.encode("utf-8"))


def fetch(root=Path("data/raw"), page_size=50000):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if (root / "manifest.json").exists():
        raise FileExistsError("Snapshot already exists; choose a new --raw directory to refresh")
    s = requests.Session()
    s.headers["User-Agent"] = "Boston-OCEL-research/0.1 (public municipal data extraction)"
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504])))

    def get(action, params):
        r = s.get(API + action, params=params, timeout=(15, 180))
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(data)
        return data, r.url

    package, package_url = get("package_show", {"id": "food-establishment-inspections"})
    write_json(root / "food-inspections.package.json", package)
    started = datetime.now(timezone.utc).isoformat()
    pages, offset, expected, previous_id = [], 0, None, 0
    while expected is None or offset < expected:
        data, url = get("datastore_search", {"resource_id": RESOURCE,
                         "limit": page_size, "offset": offset, "sort": "_id asc"})
        result = data["result"]
        if result.get("total_was_estimated"):
            raise ValueError("Source total must be exact")
        expected = result["total"] if expected is None else expected
        if result["total"] != expected:
            raise ValueError("Source total changed during extraction")
        rows = result["records"]
        if not rows:
            raise ValueError("Premature end of source pagination")
        for row in rows:
            if row["_id"] <= previous_id:
                raise ValueError("Source row IDs not strictly increasing")
            previous_id = row["_id"]
        name = f"inspections-{offset:07d}.json.gz"
        write_gzip(root / name, data)
        pages.append({"file": name, "url": url, "rows": len(rows),
                      "first_id": rows[0]["_id"], "last_id": previous_id,
                      "sha256": sha256(root / name)})
        offset += len(rows)
        print(f"Fetched {offset:,}/{expected:,} rows", flush=True)
    after, _ = get("package_show", {"id": "food-establishment-inspections"})
    check, _ = get("datastore_search", {"resource_id": RESOURCE, "limit": 0})
    if after["result"]["metadata_modified"] != package["result"]["metadata_modified"]:
        raise ValueError("Package metadata changed during extraction")
    if check["result"]["total"] != expected or offset != expected:
        raise ValueError("Final source count differs")
    write_json(root / "manifest.json", {
        "resource_id": RESOURCE, "package_url": package_url,
        "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": expected, "package_sha256": sha256(root / "food-inspections.package.json"),
        "metadata_modified": package["result"]["metadata_modified"], "pages": pages,
        "consistency": "Exact counts and monotonically increasing row IDs; metadata unchanged. CKAN has no transactional snapshot guarantee."
    })


def iter_rows(root=Path("data/raw")):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    if sha256(root / "food-inspections.package.json") != manifest["package_sha256"]:
        raise ValueError("Package checksum mismatch")
    count, previous = 0, 0
    for page in manifest["pages"]:
        path = root / page["file"]
        if sha256(path) != page["sha256"]:
            raise ValueError(f"Checksum mismatch: {path}")
        with gzip.open(path, "rt") as f:
            rows = json.load(f)["result"]["records"]
        if len(rows) != page["rows"]:
            raise ValueError("Page count mismatch")
        for row in rows:
            if row["_id"] <= previous:
                raise ValueError("Duplicate or out-of-order source ID")
            previous = row["_id"]
            count += 1
            yield row
    if count != manifest["total_rows"]:
        raise ValueError("Snapshot row count mismatch")

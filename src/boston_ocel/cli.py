import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Reproduce Boston inspection OCEL 2.0 logs")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="Freeze a new API snapshot (network)")
    fetch.add_argument("--raw", type=Path, default=Path("data/raw"))
    extract = sub.add_parser("extract", help="Build logs offline from the checked snapshot")
    extract.add_argument("--raw", type=Path, default=Path("data/raw"))
    extract.add_argument("--output", type=Path, default=Path("data/ocel"))
    extract.add_argument("--reports", type=Path, default=Path("reports"))
    validate = sub.add_parser("validate", help="Schema, graph, and full source reconciliation (offline)")
    validate.add_argument("--raw", type=Path, default=Path("data/raw"))
    validate.add_argument("--output", type=Path, default=Path("data/ocel"))
    validate.add_argument("--reports", type=Path, default=Path("reports"))
    analyze = sub.add_parser("analyze", help="Compute descriptive process-mining insights")
    analyze.add_argument("--output", type=Path, default=Path("data/ocel"))
    analyze.add_argument("--reports", type=Path, default=Path("reports"))
    analyze.add_argument("--pm4py", action="store_true", help="Also verify import and DFG in PM4Py")
    args = parser.parse_args()
    if args.command == "fetch":
        from .source import fetch as run
        run(args.raw)
    elif args.command == "extract":
        from .extract import extract as run
        print(json.dumps(run(args.raw, args.output, args.reports), indent=2))
    elif args.command == "validate":
        from .validate import validate_all
        print(json.dumps(validate_all(args.raw, args.output, args.reports), indent=2))
    elif args.command == "analyze":
        from .analyze import analyze_all
        analyze_all(args.output, args.reports, args.pm4py)


if __name__ == "__main__":
    main()

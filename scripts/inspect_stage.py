"""Command-line entry point for the baseline inspector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from openusd_production_inspector.inspector import (
    StageLoadError,
    inspect_composition,
    inspect_dependencies,
    inspect_stage,
    stage_summary,
    validate_stage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and validate a local OpenUSD stage.")
    parser.add_argument("stage", help="Path to a .usd, .usda, or .usdc stage")
    parser.add_argument("command", nargs="?", choices=("summary", "dependencies", "composition", "validate"), default="summary")
    parser.add_argument("prim_path", nargs="?", help="Prim path required by composition")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--name-pattern", help="Optional full-match regex for prim names")
    args = parser.parse_args()
    try:
        if args.command == "summary":
            report = stage_summary(args.stage)
        elif args.command == "dependencies":
            report = inspect_dependencies(args.stage)
        elif args.command == "composition":
            if not args.prim_path:
                parser.error("composition requires a prim path")
            report = inspect_composition(args.stage, args.prim_path)
        else:
            report = validate_stage(args.stage)
    except StageLoadError as error:
        print(str(error), file=sys.stderr)
        return 3
    except Exception as error:
        print(f"Unexpected internal error: {error}", file=sys.stderr)
        return 4
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.command == "validate":
        for check in report["checks"]:
            print(f"{check['status']}  {check['message']}")
        print(f"\nValidation result: {'PASSED' if report['valid'] else 'FAILED'}")
        print(f"{report['error_count']} errors, {report['warning_count']} warnings")
    else:
        print(f"stage: {report['stage']}")
        print(f"default prim: {report.get('default_prim', 'n/a')}")
        print(f"prims: {report.get('prim_count', 'n/a')}")
        findings = report.get("findings", [])
        print(f"findings: {len(findings)}")
        for finding in findings:
            print(f"- {finding['severity']} {finding['code']}: {finding['message']}")
    return 1 if args.command == "validate" and not report["valid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

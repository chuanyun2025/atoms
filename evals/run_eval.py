"""Command-line entrypoint for Atoms offline benchmark suite (FR-029 / NFR-014)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atoms Studio offline generation quality evaluation CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="Execute benchmark suite in an isolated temporary database")
    run_cmd.add_argument("--cases-file", default=str(REPO_ROOT / "evals" / "cases.json"))
    run_cmd.add_argument("--cases", default="", help="Comma-separated case IDs to run")
    run_cmd.add_argument("--category", default=None, help="Filter cases by category")
    run_cmd.add_argument("--limit", type=int, default=None, help="Limit number of cases")
    run_cmd.add_argument("--label", default="atoms-eval", help="Configuration / model label for the report")
    run_cmd.add_argument("--fixture", action="store_true", help="Use deterministic zero-cost fixture model")
    run_cmd.add_argument(
        "--confirm-live-billing",
        action="store_true",
        help="Explicitly confirm live provider token billing when not using --fixture",
    )
    run_cmd.add_argument(
        "--live-validator",
        action="store_true",
        help="Call live @atoms/validator service even when --fixture is enabled",
    )
    run_cmd.add_argument("--output", required=True, help="Output JSON report path")
    run_cmd.add_argument("--markdown", default=None, help="Optional Markdown summary output path")

    cmp_cmd = sub.add_parser("compare", help="Compare baseline and candidate eval JSON reports")
    cmp_cmd.add_argument("baseline", help="Baseline JSON report path")
    cmp_cmd.add_argument("candidate", help="Candidate JSON report path")
    cmp_cmd.add_argument("--output", default=None, help="Optional JSON diff output path")
    cmp_cmd.add_argument("--markdown", default=None, help="Optional Markdown comparison report path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    from atoms.runtime.evals import (
        compare_eval_reports,
        render_comparison_markdown,
        render_eval_markdown,
        run_eval_suite,
    )

    if args.command == "run":
        case_ids = [item.strip() for item in args.cases.split(",") if item.strip()] or None
        report = asyncio.run(
            run_eval_suite(
                label=args.label,
                cases_path=args.cases_file,
                case_ids=case_ids,
                category=args.category,
                limit=args.limit,
                fixture=args.fixture,
                confirm_live_billing=args.confirm_live_billing,
                live_validator=args.live_validator,
            )
        )
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_text = render_eval_markdown(report)
        if args.markdown:
            md_path = Path(args.markdown)
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(md_text, encoding="utf-8")
        else:
            sys.stdout.write(md_text)
        return 0

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    diff = compare_eval_reports(baseline, candidate)
    md_text = render_comparison_markdown(baseline, candidate)
    if args.output:
        diff_path = Path(args.output)
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_text, encoding="utf-8")
    else:
        sys.stdout.write(md_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

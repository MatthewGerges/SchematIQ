#!/usr/bin/env python3
"""
Run 2-LLM electrical review on LLM circuit JSON.

Usage:
  cd ChipChat_Project && source .venv/bin/activate
  python scripts/review_llm_json.py data/llm_output_nRF5340_BaseBoard.json
  python scripts/review_llm_json.py data/board.json --fail-on warning
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_PROJECT, ".env"))

from src.lib.electrical_review_llm import (  # noqa: E402
    run_two_llm_review,
    severity_meets_or_exceeds,
)


def _default_report_path(json_path: str) -> str:
    base = os.path.splitext(os.path.basename(json_path))[0]
    out_dir = os.path.join(_PROJECT, "reports")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{base}_electrical_review.json")


def main() -> int:
    p = argparse.ArgumentParser(description="Run two-LLM electrical review")
    p.add_argument("json_path", help="Path to llm_output JSON")
    p.add_argument("--model-structural", default="gemini-2.5-flash")
    p.add_argument("--model-electrical", default="gemini-2.5-flash")
    p.add_argument(
        "--fail-on",
        choices=("none", "error", "warning"),
        default="error",
        help="Exit nonzero if max severity meets/exceeds this threshold",
    )
    p.add_argument("--report-path", default="")
    args = p.parse_args()

    json_path = os.path.abspath(args.json_path)
    if not os.path.isfile(json_path):
        print(f"File not found: {json_path}", file=sys.stderr)
        return 2

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    report = run_two_llm_review(
        data,
        model_structural=args.model_structural,
        model_electrical=args.model_electrical,
    )

    out_path = args.report_path.strip() or _default_report_path(json_path)
    with open(out_path, "w", encoding="utf-8") as wf:
        json.dump(report, wf, indent=2)
        wf.write("\n")

    merged = report.get("merged", {})
    max_sev = (merged.get("max_severity") or "info").lower()
    gate_sev = (merged.get("gate_severity") or "none").lower()
    fc = merged.get("finding_counts") or {}
    ne = int(fc.get("error") or 0)
    nw = int(fc.get("warning") or 0)
    ni = int(fc.get("info") or 0)
    print(f"Review report: {out_path}")
    hs = merged.get("human_summary") or {}
    if hs.get("headline"):
        print(hs["headline"])
    print(f"Max severity (all): {max_sev}  |  Gate (--fail-on): {gate_sev}")
    print(f"Counts — error / warning / info: {ne} / {nw} / {ni}")

    if args.fail_on != "none" and severity_meets_or_exceeds(gate_sev, args.fail_on):
        print(f"Failing because severity >= {args.fail_on}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


#!/usr/bin/env python3
"""
LLM-assisted tscircuit part mapping (MPN + footprint) into config/tscircuit_part_overrides.json.

Usage:
  cd Code && source .venv/bin/activate
  export GEMINI_API_KEY=...   # or .env

  python scripts/repair_llm_tscircuit_parts.py data/llm_output_MyBoard.json
  python scripts/repair_llm_tscircuit_parts.py data/board.json --dry-run
  python scripts/repair_llm_tscircuit_parts.py data/board.json --model gemini-2.5-flash
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

from src.lib.tscircuit_repair_llm import repair_tscircuit_parts_with_llm  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="LLM tscircuit part → MPN/footprint overrides")
    p.add_argument("json_path", help="Path to llm_output_*.json")
    p.add_argument("--dry-run", action="store_true", help="Do not write tscircuit_part_overrides.json")
    p.add_argument("--model", default="gemini-2.5-flash")
    args = p.parse_args()

    path = os.path.abspath(args.json_path)
    if not os.path.isfile(path):
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    normalized, report = repair_tscircuit_parts_with_llm(
        data, model=args.model, dry_run=args.dry_run
    )

    print(json.dumps({"applied_count": len(normalized), "errors": report.get("errors")}, indent=2))
    if normalized:
        print("Overrides:")
        print(json.dumps(normalized, indent=2)[:6000])
    if args.dry_run:
        print("\n(dry-run: no write. Omit --dry-run to merge into config/tscircuit_part_overrides.json)")
    else:
        print("\nMerged into config/tscircuit_part_overrides.json")

    if report.get("errors") and not normalized:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

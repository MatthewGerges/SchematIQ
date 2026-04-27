#!/usr/bin/env python3
"""
LLM fallback: map unresolved component ``part`` strings to real KiCad ``Library:Symbol`` names.

Uses the same validation rules as ``generate_from_llm.py`` (aliases, normalize, fuzzy + pin count).
Every model suggestion is verified locally before applying.

Usage:
  cd Code && source .venv/bin/activate
  export GEMINI_API_KEY=...   # or use .env

  # Preview (no file write)
  python scripts/repair_llm_symbols.py data/some_board.json --dry-run

  # Write updated JSON in place
  python scripts/repair_llm_symbols.py data/some_board.json --write

  # Also add old→new mappings to config/symbol_aliases.json (helps future runs)
  python scripts/repair_llm_symbols.py data/some_board.json --write --save-aliases

  python scripts/repair_llm_symbols.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_CODE_ROOT, ".env"))

from src.lib.symbol_preflight import find_unresolved_components, validate_components_in_llm_data  # noqa: E402
from src.lib.symbol_repair_llm import merge_symbol_aliases, repair_symbols_with_llm  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="LLM-assisted KiCad symbol repair for LLM JSON")
    p.add_argument("json_path", help="Path to llm_output_*.json")
    p.add_argument("--dry-run", action="store_true", help="Call Gemini but do not write files")
    p.add_argument("--write", action="store_true", help="Write repaired JSON to json_path")
    p.add_argument(
        "--save-aliases",
        action="store_true",
        help="With --write, append old_part → new_part to config/symbol_aliases.json",
    )
    p.add_argument("--model", default="gemini-2.5-flash", help="Gemini model id")
    p.add_argument(
        "--force",
        action="store_true",
        help="Run repair even if validation already passes (re-map parts)",
    )
    args = p.parse_args()

    path = os.path.abspath(args.json_path)
    if not os.path.isfile(path):
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(2)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    failures = find_unresolved_components(data)
    if not failures and not args.force:
        print("All components already resolve. Nothing to repair.")
        print("(Use --force to run LLM anyway.)")
        sys.exit(0)

    if not failures and args.force:
        print("--force: no failures; running LLM on all components is not implemented.")
        sys.exit(0)

    print(f"Unresolved: {len(failures)} component(s)")
    for f in failures:
        print(f"  - {f['ref']}: {f['part']!r} → {f['lookup']!r} ({f['detail']})")

    new_data, report = repair_symbols_with_llm(
        data,
        failures,
        model=args.model,
        dry_run=args.dry_run,
    )

    print("\n--- LLM repair report ---")
    print(json.dumps(report, indent=2)[:8000])
    if len(json.dumps(report)) > 8000:
        print("... (truncated)")

    if args.dry_run or not args.write:
        print("\nDry run: no files written. Use --write to save JSON.")
        sys.exit(0 if report.get("applied") else 1)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2)
        f.write("\n")
    print(f"\nWrote: {path}")

    if args.save_aliases and report.get("applied"):
        adds = {a["old_part"]: a["new_part"] for a in report["applied"] if a.get("old_part") != a.get("new_part")}
        if adds:
            ap = merge_symbol_aliases(adds)
            print(f"Updated symbol aliases: {ap}")

    errs = validate_components_in_llm_data(new_data, print_ok=True)
    if errs:
        print("\nStill failing after repair:")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print("\nAll component symbols resolve.")
    sys.exit(0)


if __name__ == "__main__":
    main()

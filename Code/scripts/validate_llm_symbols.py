#!/usr/bin/env python3
"""
Preflight: verify every component `part` in an LLM project JSON resolves to a KiCad symbol.

Uses the same alias + normalization rules as schematic generation (symbol_aliases +
normalize_symbol_lookup) without writing a schematic.

Usage:
  python scripts/validate_llm_symbols.py [path/to/llm_output.json]
  python scripts/generate_from_llm.py --validate data/board.json
  python scripts/repair_llm_symbols.py data/board.json --dry-run   # Gemini fallback
"""

from __future__ import annotations

import json
import os
import sys

_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from src.lib.symbol_aliases import get_aliases_path  # noqa: E402
from src.lib.symbol_preflight import validate_components_in_llm_data  # noqa: E402


def main():
    default = os.path.join(_CODE_ROOT, "data", "llm_output.json")
    path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else default)
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        sys.exit(2)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Validating components in: {path}")
    print(f"Aliases: {get_aliases_path()}")
    print()
    errs = validate_components_in_llm_data(data, print_ok=True)
    if errs:
        print("\nProblems:")
        for e in errs:
            print(f"  - {e}")
        print(
            "\nFix: add a mapping in config/symbol_aliases.json (preferred), "
            "correct the LLM output, or run:\n"
            "  python scripts/repair_llm_symbols.py \"" + path + "\" --dry-run"
        )
        sys.exit(1)
    print("\nAll component symbols resolve.")
    sys.exit(0)


if __name__ == "__main__":
    main()

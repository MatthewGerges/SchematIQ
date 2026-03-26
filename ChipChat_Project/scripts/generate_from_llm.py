"""
Generate outputs from llm_output JSON (KiCad, tscircuit, or both).

Usage:
    cd ChipChat_Project
    source .venv/bin/activate
    python scripts/generate_from_llm.py
    python scripts/generate_from_llm.py --validate data/board.json
    python scripts/generate_from_llm.py --repair --target both data/board.json

See schematic_commands.md for a short command index.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.lib import project_generator, schematic_generator, tscircuit_generator
from src.lib.electrical_review_llm import run_two_llm_review, severity_meets_or_exceeds
from src.lib.symbol_preflight import find_unresolved_components, validate_components_in_llm_data

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JSON_PATH = os.path.join(PROJECT_DIR, "data", "llm_output.json")
GEN_DIR = os.path.join(PROJECT_DIR, "generated")
REPORT_DIR = os.path.join(PROJECT_DIR, "reports")


def _run_kicad_generation(data: dict, json_path: str, output_dir: str) -> int:
    project_name = data.get("project_name", "LLM_Project")
    sheets = data.get("sheets", [])

    print("\n" + "=" * 60)
    print("  Generating KiCad project from LLM output")
    print(f"  Project: {project_name}")
    print(f"  JSON:    {json_path}")
    print(f"  Output:  {output_dir}")
    print(f"  Sheets:  {[s['name'] for s in sheets]}")
    print("=" * 60)

    print("\n--- Step 1: Root schematic ---")
    _, _, sheet_uuids = project_generator.generate_root_schematic(
        json_path, output_dir, project_name
    )

    print("\n--- Step 2: Project file ---")
    project_generator.generate_project_file(
        project_name, output_dir, sheet_uuids=sheet_uuids
    )

    errors = []
    for sheet_def in sheets:
        sheet_name = sheet_def["name"]
        sheet_file = sheet_def["file"]
        output_path = os.path.join(output_dir, sheet_file)

        print(f"\n--- Step 3: {sheet_name} → {sheet_file} ---")
        try:
            schematic_generator.generate_from_json(
                output_path, json_path, sheet_name=sheet_name
            )
        except Exception as e:
            errors.append((sheet_name, str(e)))
            print(f"  ERROR on {sheet_name}: {e}")

    print("\n" + "=" * 60)
    if errors:
        print(f"  KiCad completed with {len(errors)} error(s):")
        for name, err in errors:
            print(f"    {name}: {err}")
        print("=" * 60)
        return 1

    print("  Done! Open in KiCad:")
    print(f"  {os.path.join(output_dir, f'{project_name}.kicad_pro')}")
    print("=" * 60)
    return 0


def _run_tscircuit_generation(data: dict, output_dir: str) -> int:
    project_name = data.get("project_name", "LLM_Project")
    tsci_dir = os.path.join(output_dir, "tscircuit")
    files = tscircuit_generator.write_tscircuit_project(data, tsci_dir)

    print("\n" + "=" * 60)
    print("  Generated tscircuit project")
    print(f"  Project: {project_name}")
    print(f"  Output:  {tsci_dir}")
    print("  Next:")
    print(f"    cd {tsci_dir}")
    print("    npm install")
    print("    npm run dev")
    print(f"  Entry:   {files['index']}")
    print("=" * 60)
    return 0


def main() -> int:
    load_dotenv(os.path.join(PROJECT_DIR, ".env"))

    parser = argparse.ArgumentParser(description="Generate KiCad and/or tscircuit from LLM JSON.")
    parser.add_argument("json_path", nargs="?", default=DEFAULT_JSON_PATH)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--review", action="store_true", help="Run 2-LLM electrical review before generation")
    parser.add_argument("--review-model-structural", default="gemini-2.5-flash")
    parser.add_argument("--review-model-electrical", default="gemini-2.5-flash")
    parser.add_argument(
        "--review-fail-on",
        choices=("none", "error", "warning"),
        default="error",
        help="When --review is enabled, fail if max severity meets/exceeds this threshold",
    )
    parser.add_argument(
        "--target",
        choices=("kicad", "tscircuit", "both"),
        default="kicad",
        help="Output format target",
    )
    args = parser.parse_args()

    json_path = os.path.abspath(args.json_path)
    if not os.path.exists(json_path):
        print(f"ERROR: {json_path} not found. Run prompt_playground.py first.")
        return 1

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if args.review:
        print("--- Running 2-LLM electrical review ---")
        report = run_two_llm_review(
            data,
            model_structural=args.review_model_structural,
            model_electrical=args.review_model_electrical,
        )
        os.makedirs(REPORT_DIR, exist_ok=True)
        base = os.path.splitext(os.path.basename(json_path))[0]
        report_path = os.path.join(REPORT_DIR, f"{base}_electrical_review.json")
        with open(report_path, "w", encoding="utf-8") as rf:
            json.dump(report, rf, indent=2)
            rf.write("\n")
        merged = report.get("merged", {})
        max_sev = (merged.get("max_severity") or "info").lower()
        gate_sev = (merged.get("gate_severity") or "none").lower()
        fc = merged.get("finding_counts") or {}
        ne = int(fc.get("error") or 0)
        nw = int(fc.get("warning") or 0)
        ni = int(fc.get("info") or 0)
        print(f"(review) report: {report_path}")
        hs = merged.get("human_summary") or {}
        if hs.get("headline"):
            print(f"(review) {hs['headline']}")
        print(
            f"(review) max (all): {max_sev}, gate: {gate_sev}, "
            f"errors/warnings/info: {ne}/{nw}/{ni}"
        )
        if args.review_fail_on != "none" and severity_meets_or_exceeds(gate_sev, args.review_fail_on):
            print(f"(review) blocking generation because severity >= {args.review_fail_on}")
            return 1

    if args.repair:
        failures = find_unresolved_components(data)
        if failures:
            print(
                f"--- LLM symbol repair ({len(failures)} unresolved) — "
                "requires GEMINI_API_KEY in .env ---"
            )
            from src.lib.symbol_repair_llm import repair_symbols_with_llm

            data, report = repair_symbols_with_llm(data, failures, dry_run=False)
            with open(json_path, "w", encoding="utf-8") as wf:
                json.dump(data, wf, indent=2)
                wf.write("\n")
            print("Updated JSON:", json_path)
            print("Applied:", json.dumps(report.get("applied", []), indent=2))
            if report.get("rejected"):
                print("Rejected / not applied:", json.dumps(report["rejected"], indent=2)[:4000])
        else:
            print("(repair) All components already resolve; skipping LLM.")

    if args.validate:
        v_errs = validate_components_in_llm_data(data, print_ok=False)
        if v_errs:
            print("Symbol validation failed (--validate). Fix before generating:\n")
            for e in v_errs:
                print(f"  - {e}")
            print(
                "\nTip: add mappings in config/symbol_aliases.json or run "
                "scripts/validate_llm_symbols.py for details."
            )
            return 1
        print("(validate) All component symbols resolve.\n")

    project_name = data.get("project_name", "LLM_Project")
    output_dir = os.path.join(GEN_DIR, project_name)
    os.makedirs(output_dir, exist_ok=True)

    rc = 0
    if args.target in ("kicad", "both"):
        rc = max(rc, _run_kicad_generation(data, json_path, output_dir))
    if args.target in ("tscircuit", "both"):
        rc = max(rc, _run_tscircuit_generation(data, output_dir))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

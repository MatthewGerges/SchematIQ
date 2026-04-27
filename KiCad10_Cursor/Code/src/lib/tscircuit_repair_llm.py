"""
LLM-assisted mapping of LLM ``part`` strings to tscircuit-friendly fields.

Unlike KiCad symbol repair, there is no local symbol index: the model suggests
``manufacturerPartNumber`` and ``footprint`` strings for tscircuit's footprinter.
Suggestions are merged into ``config/tscircuit_part_overrides.json`` (or previewed).

KiCad ``Library:Symbol`` names in JSON are still used for KiCad generation;
this path only improves tscircuit PCB/BOM fields and MPN labels on chips.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


def _get_gemini_client():
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required. pip install google-genai python-dotenv"
        ) from e
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set (Code/.env)")
    return genai.Client(api_key=api_key)


def _parse_json_object(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return json.loads(t)


def _collect_unique_parts(data: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for comp in data.get("components", []) or []:
        p = (comp.get("part") or "").strip()
        if p and p not in seen:
            seen.add(p)
            ordered.append(p)
    for p in data.get("passives", []) or []:
        part = (p.get("part") or "").strip()
        if part and part not in seen:
            seen.add(part)
            ordered.append(part)
    return ordered


def _repair_prompt(parts: list[str], model_hint: str) -> str:
    parts_json = json.dumps(parts, indent=2)
    return f"""You map electronic part description strings to tscircuit props.

tscircuit uses string footprints for its footprinter (similar to KiCad footprint names but not identical).
Examples of valid-style strings: "0402", "0603", "0805", "soic8", "sot23", "qfn32", "pinrow10_p1.27mm", "usb_c_16pin".
Prefer short common SMD packages when uncertain.

For each DISTINCT part string below, output ONE override object with:
- "part_substrings": array with ONE element = the exact part string from the list (so we can match it)
- "manufacturerPartNumber": realistic MPN or common industry string when known; else a short descriptive label
- "footprint": a single tscircuit-style footprint string

Do not invent JLC/LCSC SKUs unless you are sure.
If the part is clearly a KiCad symbol name like "Device:R" or "Connector:Foo", still suggest a footprint for the physical package if obvious, else "0402" for generic.

Model: {model_hint}

Part strings:
{parts_json}

Reply with ONLY valid JSON (no markdown):
{{
  "overrides": [
    {{
      "part_substrings": ["exact_string_from_list"],
      "manufacturerPartNumber": "...",
      "footprint": "..."
    }}
  ]
}}

Include one entry per input part string, in the same order as the list.
"""


def _normalize_override(row: dict[str, Any]) -> dict[str, Any] | None:
    subs = row.get("part_substrings") or []
    if not isinstance(subs, list) or not subs:
        return None
    subs = [str(s).strip() for s in subs if str(s).strip()]
    if not subs:
        return None
    mpn = (row.get("manufacturerPartNumber") or "").strip()
    fp = (row.get("footprint") or "").strip()
    if not mpn or not fp:
        return None
    return {"part_substrings": subs, "manufacturerPartNumber": mpn, "footprint": fp}


def merge_tscircuit_overrides(
    new_rows: list[dict[str, Any]],
    *,
    overrides_path: str | None = None,
) -> str:
    """Merge *new_rows* into JSON file. Returns path written."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = overrides_path or os.path.join(root, "config", "tscircuit_part_overrides.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
    else:
        blob = {"overrides": []}
    existing = list(blob.get("overrides") or [])

    def key(r: dict[str, Any]) -> tuple[str, ...]:
        return tuple(sorted(str(x) for x in (r.get("part_substrings") or [])))

    seen = {key(r) for r in existing}
    for row in new_rows:
        n = _normalize_override(row)
        if not n:
            continue
        k = key(n)
        if k in seen:
            # Replace earlier with same key
            existing = [r for r in existing if key(r) != k]
        seen.add(k)
        existing.append(n)

    blob["overrides"] = existing
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blob, f, indent=2)
        f.write("\n")
    try:
        from src.lib import tscircuit_generator

        tscircuit_generator._TSC_OVERRIDES_CACHE = None  # type: ignore[attr-defined]
    except Exception:
        pass
    return path


def repair_tscircuit_parts_with_llm(
    data: dict[str, Any],
    *,
    model: str = "gemini-2.5-flash",
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Ask Gemini for tscircuit overrides for each unique component ``part`` string.

    Returns:
        (normalized_overrides, report)
    """
    parts = _collect_unique_parts(data)
    report: dict[str, Any] = {
        "parts_count": len(parts),
        "raw_response": None,
        "normalized": [],
        "errors": [],
    }
    if not parts:
        report["message"] = "No parts to map."
        return [], report

    client = _get_gemini_client()
    prompt = _repair_prompt(parts, model)
    response = client.models.generate_content(model=model, contents=prompt)
    text = (response.text or "").strip()
    report["raw_response"] = text

    try:
        obj = _parse_json_object(text)
    except (json.JSONDecodeError, TypeError) as e:
        report["errors"].append(f"Invalid JSON: {e}")
        return [], report

    raw_list = obj.get("overrides") or []
    if not isinstance(raw_list, list):
        report["errors"].append("overrides is not a list")
        return [], report

    normalized: list[dict[str, Any]] = []
    for row in raw_list:
        n = _normalize_override(row if isinstance(row, dict) else {})
        if n:
            normalized.append(n)
        else:
            report["errors"].append(f"Skipped invalid row: {row!r}")

    report["normalized"] = normalized

    if not dry_run and normalized:
        merge_tscircuit_overrides(normalized)

    return normalized, report

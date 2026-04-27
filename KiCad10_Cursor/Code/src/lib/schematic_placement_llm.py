"""
LLM-assisted schematic placement (minimal version).

Goal: produce stable ref→(x,y,angle) placements per sheet, while keeping wiring
and labels deterministic in `schematic_generator.py`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from google import genai


def _get_client() -> Any:
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set (add to Code/.env)")
    return genai.Client(api_key=api_key)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    # Best-effort: locate the first '{'..last '}'.
    a = text.find("{")
    b = text.rfind("}")
    if a == -1 or b == -1 or b <= a:
        raise ValueError("no json object found")
    return json.loads(text[a : b + 1])


def propose_placements(
    data: dict[str, Any],
    *,
    model: str = "gemini-2.5-flash",
    grid_mm: float = 1.27,
) -> dict[str, Any]:
    """
    Return placement proposal:

    {
      "generated_at": "...",
      "grid_mm": 1.27,
      "sheets": {
        "SheetName": {
          "symbols": {
            "U1": {"x": 120.65, "y": 101.6, "angle": 0},
            "R1": {"x": 76.2, "y": 38.1, "angle": 90}
          }
        }
      }
    }
    """
    sheets = [s.get("name") for s in data.get("sheets", []) if s.get("name")]
    comps = [c for c in data.get("components", []) if c.get("ref") and c.get("sheet") in sheets]
    passives = [p for p in data.get("passives", []) if p.get("ref") and p.get("sheet") in sheets]

    payload = {
        "project_name": data.get("project_name"),
        "sheets": sheets,
        "components": [{"ref": c["ref"], "sheet": c["sheet"], "part": c.get("part")} for c in comps],
        "passives": [{"ref": p["ref"], "sheet": p["sheet"], "type": p.get("type"), "value": p.get("value")} for p in passives],
        "nets": data.get("nets", []),
    }

    prompt = f"""You are a schematic placement assistant for KiCad.

Task: propose XY placements for symbols on each sheet for readability.

Constraints:
- Use mm units.
- Snap all coordinates to a grid of {grid_mm} mm.
- Keep all symbols within an A4 sheet area (roughly x: 20..280, y: 20..190).
- Avoid overlaps: keep at least ~15mm separation between symbol centers.
- Group related items: passives near the IC/connector they belong to if obvious.
- Keep angles to 0/90/180/270 only.

Return STRICT JSON only (no markdown, no commentary) with this schema:
{{
  "sheets": {{
    "SheetName": {{
      "symbols": {{
        "REF": {{"x": number, "y": number, "angle": 0|90|180|270}}
      }}
    }}
  }}
}}

Input project summary JSON:
{json.dumps(payload, indent=2)}
"""

    client = _get_client()
    resp = client.models.generate_content(model=model, contents=prompt)
    parsed = _parse_json_object(resp.text or "")

    out: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "grid_mm": grid_mm,
        "model": model,
        "sheets": parsed.get("sheets") or {},
    }
    return out


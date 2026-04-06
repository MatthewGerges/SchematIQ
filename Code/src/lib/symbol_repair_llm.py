"""
Optional Gemini fallback: map unresolved LLM ``part`` strings to real KiCad symbols.

Deterministic resolution (aliases, fuzzy + pin-count) runs first in normal flow.
When something still fails validation, run ``repair_symbols_with_llm`` (or
``scripts/repair_llm_symbols.py``) to propose replacements, then re-validate
every suggestion against the local library index — no blind trust of the model.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from src.lib import symbol_resolver
from src.lib.symbol_aliases import apply_symbol_alias, normalize_symbol_lookup
from src.lib.symbol_preflight import preview_resolve

# --- Candidate ranking (no LLM): shrink the catalog sent to the model ------------


def _tokenize(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) >= 2}


def rank_symbol_candidates(
    query: str,
    all_symbols: list[str],
    limit: int = 100,
) -> list[str]:
    """Prefer symbols whose names share tokens with *query* (part + lookup + ref)."""
    if not query or not all_symbols:
        return []
    q = query.lower()
    tokens = _tokenize(q)
    if not tokens:
        return all_symbols[:limit]

    scored: list[tuple[int, str]] = []
    for sym in all_symbols:
        sl = sym.lower()
        score = sum(1 for t in tokens if t in sl)
        if score == 0 and len(q) >= 4:
            # weak fallback: prefix of the raw part appears in symbol string
            head = q[: min(8, len(q))].strip(":_")
            if head and head in sl:
                score = 1
        if score > 0:
            scored.append((-score, sym))

    scored.sort()
    out = [s for _, s in scored[:limit]]
    if len(out) < min(20, limit):
        # pad with alphabetically nearby symbols from same first letter (deterministic)
        ch = q[0].lower() if q else "a"
        extra = [s for s in all_symbols if s and s[0].lower() == ch and s not in out]
        out.extend(extra[: limit - len(out)])
    return out[:limit]


def _guess_library_categories(ref: str, part: str) -> list[str]:
    """Guess which KiCad library categories a component likely belongs to."""
    cats: list[str] = []
    r = ref.upper().rstrip("0123456789")
    p = part.lower()

    if ":" in part:
        cats.append(part.split(":")[0])

    if r == "U":
        if any(kw in p for kw in ("ldo", "reg", "117", "78", "79", "linear", "voltage")):
            cats.extend(["Regulator_Linear", "Regulator_Switching"])
        elif any(kw in p for kw in ("mcu", "stm32", "nrf", "esp", "pic", "atm")):
            cats.extend(["MCU_ST", "MCU_Nordic", "MCU_Microchip"])
        elif any(kw in p for kw in ("amp", "opamp", "op_amp", "tl0", "lm3", "mcp6")):
            cats.append("Amplifier_Operational")
        else:
            cats.extend(["Regulator_Linear", "Amplifier_Operational"])
    elif r == "J":
        cats.extend(["Connector_Generic", "Connector"])
    elif r in ("Q", "T"):
        cats.extend(["Transistor_FET", "Transistor_BJT"])
    elif r == "D":
        cats.append("Diode")

    # Voltage suffix hints at a regulator
    if re.search(r"-\d+\.\d+$", part):
        if "Regulator_Linear" not in cats:
            cats.append("Regulator_Linear")

    return cats


def build_candidate_pool(
    failures: list[dict[str, Any]],
    all_symbols: list[str],
    max_per_failure: int = 80,
    max_total: int = 800,
) -> list[str]:
    """Union of ranked lists for each failure, de-duplicated, capped."""
    seen: set[str] = set()
    merged: list[str] = []
    for f in failures:
        q = " ".join(
            str(f.get(k, "") or "")
            for k in ("ref", "part", "lookup", "detail")
        )
        for s in rank_symbol_candidates(q, all_symbols, limit=max_per_failure):
            if s not in seen:
                seen.add(s)
                merged.append(s)

        # When token matching finds too few, pad with symbols from the
        # likely library category (e.g. all Regulator_Linear for an LDO).
        if len(merged) < 60:
            cats = _guess_library_categories(
                str(f.get("ref", "")), str(f.get("part", ""))
            )
            for cat in cats:
                prefix = f"{cat}:"
                for s in all_symbols:
                    if s.startswith(prefix) and s not in seen:
                        seen.add(s)
                        merged.append(s)
                        if len(merged) >= max_total:
                            return merged

        if len(merged) >= max_total:
            return merged
    return merged


# --- Gemini -------------------------------------------------------------------


def _get_gemini_client():
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM symbol repair. "
            "pip install google-genai python-dotenv"
        ) from e

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set (add to Code/.env)")
    return genai.Client(api_key=api_key)


def _repair_prompt(
    failures: list[dict[str, Any]],
    candidates: list[str],
    model_hint: str,
) -> str:
    fail_json = json.dumps(failures, indent=2)
    # Keep candidate list manageable for the prompt
    cand_lines = "\n".join(f"  - {c}" for c in candidates)
    return f"""You are a KiCad librarian. Map each failing component to ONE real symbol from the candidate list below.

CRITICAL: You MUST pick a symbol from the CANDIDATE SYMBOLS list below. Do NOT invent or guess symbol names — if a symbol is not in the list, do NOT use it. Every replacement must come from this list. If nothing fits, return an empty "replacements" array.

Rules:
- Use the exact "ref" from the failure list.
- "part" must be a valid KiCad library symbol string (Lib:Name) copied EXACTLY from the candidate list.
- Respect min_pin_count: choose a symbol with at least that many pins when the design lists that many connections.
- Prefer a functionally equivalent part: same type (e.g. LDO→LDO, not LDO→buck), similar voltage/current rating, compatible pinout.
- If the exact part family doesn't exist in the list, pick the CLOSEST alternative that serves the same circuit function.

Model note: {model_hint}

FAILING COMPONENTS:
{fail_json}

CANDIDATE SYMBOLS (prefer these when one fits):
{cand_lines}

Reply with ONLY a JSON object (no markdown fences), exactly this shape:
{{"replacements":[{{"ref":"J1","part":"Connector:Conn_ARM_JTAG_SWD_10","note":"why"}}]}}
Use "replacements": [] if nothing can be fixed confidently.
"""


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def verify_replacement(
    new_part: str,
    min_pin_count: int,
) -> tuple[bool, str]:
    """Check that *new_part* resolves the same way as schematic generation."""
    after = apply_symbol_alias(new_part.strip())
    lookup = normalize_symbol_lookup(after)
    return preview_resolve(lookup, min_pin_count=min_pin_count or None)


def repair_symbols_with_llm(
    data: dict[str, Any],
    failures: list[dict[str, Any]] | None = None,
    *,
    model: str = "gemini-2.5-flash",
    dry_run: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Call Gemini to propose ``part`` replacements for unresolved components.

    Returns:
        (updated_data_or_original, report_dict with keys: applied, rejected, raw_response)
    """
    from copy import deepcopy

    if failures is None:
        from src.lib.symbol_preflight import find_unresolved_components

        failures = find_unresolved_components(data)

    report: dict[str, Any] = {
        "applied": [],
        "rejected": [],
        "raw_response": None,
        "candidates_sent": 0,
    }

    if not failures:
        report["message"] = "No unresolved components; nothing to repair."
        return data, report

    all_syms = symbol_resolver.list_lib_colon_symbols()
    candidates = build_candidate_pool(failures, all_syms)
    report["candidates_sent"] = len(candidates)

    client = _get_gemini_client()
    prompt = _repair_prompt(
        failures,
        candidates,
        model_hint=model,
    )

    response = client.models.generate_content(model=model, contents=prompt)
    text = (response.text or "").strip()
    report["raw_response"] = text

    try:
        obj = _parse_json_object(text)
    except (json.JSONDecodeError, TypeError) as e:
        report["rejected"].append({"error": f"Invalid JSON from model: {e}", "text": text[:2000]})
        return data, report

    replacements = obj.get("replacements") or []
    if not isinstance(replacements, list):
        report["rejected"].append({"error": "replacements is not a list"})
        return data, report

    ref_to_min = {f["ref"]: int(f.get("min_pin_count") or 0) for f in failures}

    new_data = deepcopy(data)
    comps = new_data.get("components", [])

    for item in replacements:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref")
        part = (item.get("part") or "").strip()
        if not ref or not part:
            report["rejected"].append({"item": item, "error": "missing ref or part"})
            continue

        min_pins = ref_to_min.get(ref, 0)
        ok, detail = verify_replacement(part, min_pins)
        if not ok:
            report["rejected"].append(
                {"ref": ref, "part": part, "error": detail}
            )
            continue

        updated = False
        for c in comps:
            if c.get("ref") == ref:
                old = c.get("part")
                if not dry_run:
                    c["part"] = part
                report["applied"].append(
                    {
                        "ref": ref,
                        "old_part": old,
                        "new_part": part,
                        "note": item.get("note"),
                        "verified": detail,
                    }
                )
                updated = True
                break
        if not updated:
            report["rejected"].append(
                {"ref": ref, "part": part, "error": "ref not found in components"}
            )

    # ── Local fuzzy fallback: for any ref that still has no applied fix, try
    # to find a matching symbol directly from the library index. ──
    applied_refs = {a["ref"] for a in report["applied"]}
    still_failing = [f for f in failures if f["ref"] not in applied_refs]

    if still_failing and not dry_run:
        for f in still_failing:
            ref = f["ref"]
            original = f.get("part", "")
            min_pins = ref_to_min.get(ref, 0)

            # Try direct resolution of the original part name
            result = symbol_resolver.resolve_symbol(original, min_pin_count=min_pins or None)
            if result:
                sym_name, kind, path = result
                if kind == "packed":
                    lib = os.path.splitext(os.path.basename(path))[0]
                    resolved_part = f"{lib}:{sym_name}"
                else:
                    resolved_part = sym_name
                ok, detail = verify_replacement(resolved_part, min_pins)
                if ok:
                    for c in comps:
                        if c.get("ref") == ref:
                            old = c.get("part")
                            c["part"] = resolved_part
                            report["applied"].append({
                                "ref": ref,
                                "old_part": old,
                                "new_part": resolved_part,
                                "note": "local fuzzy fallback (no LLM)",
                                "verified": detail,
                            })
                            break
                    continue

            # Try each rejected LLM suggestion with fuzzy resolve inside its library
            for rej in report["rejected"]:
                if rej.get("ref") != ref:
                    continue
                rej_part = rej.get("part", "")
                if ":" in rej_part:
                    lib_name, sym_hint = rej_part.split(":", 1)
                    packed_path = os.path.join(
                        symbol_resolver.OFFICIAL_SYMBOLS_DIR,
                        f"{lib_name}.kicad_sym",
                    )
                    fuzzy_name = symbol_resolver.resolve_in_packed_library(
                        packed_path, sym_hint,
                    )
                    if fuzzy_name:
                        fpart = f"{lib_name}:{fuzzy_name}"
                        ok, detail = verify_replacement(fpart, min_pins)
                        if ok:
                            for c in comps:
                                if c.get("ref") == ref:
                                    old = c.get("part")
                                    c["part"] = fpart
                                    report["applied"].append({
                                        "ref": ref,
                                        "old_part": old,
                                        "new_part": fpart,
                                        "note": f"fuzzy fallback inside {lib_name}",
                                        "verified": detail,
                                    })
                                    break
                            break

    return new_data, report


def merge_symbol_aliases(additions: dict[str, str]) -> str:
    """Merge key→value mappings into ``config/symbol_aliases.json``. Returns path written."""
    from src.lib.symbol_aliases import get_aliases_path, invalidate_aliases_cache

    ap = get_aliases_path()
    with open(ap, "r", encoding="utf-8") as f:
        blob = json.load(f)
    for k, v in additions.items():
        blob[k] = v
    with open(ap, "w", encoding="utf-8") as f:
        json.dump(blob, f, indent=2)
        f.write("\n")
    invalidate_aliases_cache()
    return ap

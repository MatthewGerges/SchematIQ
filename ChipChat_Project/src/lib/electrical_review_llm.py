"""
Two-LLM electrical review pipeline for LLM-generated circuit JSON.

Reviewer A ("structural"):
- Focuses on netlist structure and obvious topology issues.

Reviewer B ("electrical"):
- Focuses on electrical intent, logic-level compatibility, and risk checks.

Both reviewers return strict JSON. Results are merged into one report.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any


SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}

# For --fail-on / CI: only warning+error count; info-only → gate_severity **none**.
_GATE_ORDER = {"none": 0, "warning": 1, "error": 2}


def _get_gemini_client():
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for electrical review. "
            "Install with: pip install google-genai python-dotenv"
        ) from e

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set (add to ChipChat_Project/.env)")
    return genai.Client(api_key=api_key)


def _parse_json_object(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return json.loads(t)


def _is_intentional_no_connect_net(net: str) -> bool:
    """Nets named NC_* mean intentionally unused / single-stub (no other load)."""
    n = (net or "").strip().upper()
    return n.startswith("NC_") or n == "NC"


def _is_powerish(net: str) -> bool:
    n = (net or "").strip().upper()
    if not n:
        return False
    prefixes = ("VCC", "VDD", "VBAT", "VIN", "VOUT", "3V", "5V", "1V", "2V", "12V")
    return n.startswith(prefixes) or n in {"GND", "GROUND", "VSS"}


def _deterministic_prechecks(data: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    comps = data.get("components", []) or []
    passives = data.get("passives", []) or []

    all_items = list(comps) + list(passives)
    known_nets: set[str] = set()
    for item in all_items:
        for c in item.get("connections", []) or []:
            net = (c.get("net") or "").strip()
            if net:
                known_nets.add(net)

    # Check empty/missing net names.
    for item in all_items:
        ref = item.get("ref", "?")
        for c in item.get("connections", []) or []:
            if not (c.get("net") or "").strip():
                findings.append(
                    {
                        "severity": "error",
                        "code": "MISSING_NET_NAME",
                        "ref": ref,
                        "pin": str(c.get("pin", "")),
                        "message": "Pin connection is missing a net name.",
                        "suggestion": "Assign a valid net for every pin connection.",
                    }
                )

    # Check nets with only one endpoint (often floating).
    endpoint_count: dict[str, int] = {}
    for item in all_items:
        for c in item.get("connections", []) or []:
            net = (c.get("net") or "").strip()
            if net:
                endpoint_count[net] = endpoint_count.get(net, 0) + 1

    for net, count in endpoint_count.items():
        if count == 1 and net.upper() not in {"GND", "GROUND"}:
            if _is_intentional_no_connect_net(net):
                continue
            findings.append(
                {
                    "severity": "warning",
                    "code": "SINGLE_ENDPOINT_NET",
                    "ref": None,
                    "pin": None,
                    "message": f'Net "{net}" has only one connection (possible floating node).',
                    "suggestion": (
                        "Connect the net, or rename it to NC_<purpose> if the pin is intentionally unused "
                        "(single-stub NC_* nets are not flagged)."
                    ),
                }
            )

    # Check obvious resistor unit issues (e.g. 10K vs 10k is okay, 10 with pull-up context may be suspicious).
    for p in passives:
        if (p.get("type") or "").upper() != "R":
            continue
        val = str(p.get("value", "")).strip()
        ref = p.get("ref", "?")
        if re.fullmatch(r"\d+(\.\d+)?", val):
            findings.append(
                {
                    "severity": "warning",
                    "code": "RESISTOR_NO_UNIT",
                    "ref": ref,
                    "pin": None,
                    "message": f'Resistor {ref} value "{val}" has no unit suffix.',
                    "suggestion": 'Use explicit units (e.g. "10k", "100", "1M").',
                }
            )

    # Check for no power nets at all.
    if not any(_is_powerish(n) for n in known_nets):
        findings.append(
            {
                "severity": "error",
                "code": "NO_POWER_NETS_FOUND",
                "ref": None,
                "pin": None,
                "message": "No obvious power/ground nets detected.",
                "suggestion": "Define and connect required rails (e.g., VCC_3V3, GND).",
            }
        )

    return findings


def _review_prompt(
    *,
    reviewer_name: str,
    reviewer_focus: str,
    data: dict[str, Any],
    deterministic_findings: list[dict[str, Any]],
) -> str:
    payload = {
        "project_name": data.get("project_name"),
        "sheets": data.get("sheets", []),
        "components": data.get("components", []),
        "passives": data.get("passives", []),
        "nets": data.get("nets", []),
    }
    return f"""You are Reviewer {reviewer_name} for electronic schematic JSON.

Focus:
{reviewer_focus}

Return STRICT JSON only. No markdown. No extra keys.
Schema:
{{
  "reviewer": "{reviewer_name}",
  "summary": "short summary",
  "findings": [
    {{
      "severity": "error|warning|info",
      "code": "UPPER_SNAKE_CODE",
      "ref": "U1|R1|J1|null",
      "pin": "pin number/name or null",
      "message": "what is wrong or notable",
      "suggestion": "how to fix/check"
    }}
  ],
  "checks_covered": ["bullet-style check names"],
  "assumptions": ["assumptions made due to missing data"]
}}

Hard requirements:
- Be conservative; do not invent datasheet facts.
- If information is missing, add a warning with clear assumption.
- No-connect pins: either use a net name starting with **NC_** (e.g. NC_SWO, NC_TDI, NC_J1_7)
  with only that pin on the net, **or** the pin may be **omitted** from `connections` entirely.
  Do not report floating/single-endpoint issues for nets whose name starts with NC_.
- Severity: use **error** only for likely non-functional or unsafe issues; **warning** for
  risks or missing checks; **info** rarely — only for optional context that does not affect
  pass/fail (prefer omitting info entirely).
- Prioritize practical electrical risks:
  * power rails present and connected
  * rail/value consistency
  * reset/boot/debug pin sanity
  * clock/crystal and load capacitor sanity
  * level compatibility / VIH-VIL risk flags when uncertain
  * missing pull-ups/pull-downs/open-drain issues
  * suspicious or floating nets (except NC_* as above)

Deterministic prechecks (already found):
{json.dumps(deterministic_findings, indent=2)}

Circuit JSON:
{json.dumps(payload, indent=2)}
"""


def _call_reviewer(
    *,
    client: Any,
    model: str,
    reviewer_name: str,
    reviewer_focus: str,
    data: dict[str, Any],
    deterministic_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = _review_prompt(
        reviewer_name=reviewer_name,
        reviewer_focus=reviewer_focus,
        data=data,
        deterministic_findings=deterministic_findings,
    )
    response = client.models.generate_content(model=model, contents=prompt)
    text = (response.text or "").strip()
    try:
        parsed = _parse_json_object(text)
    except Exception as e:  # noqa: BLE001
        parsed = {
            "reviewer": reviewer_name,
            "summary": "Model returned invalid JSON.",
            "findings": [
                {
                    "severity": "error",
                    "code": "INVALID_REVIEW_JSON",
                    "ref": None,
                    "pin": None,
                    "message": f"{reviewer_name} produced non-JSON output: {e}",
                    "suggestion": "Retry review with same input.",
                }
            ],
            "checks_covered": [],
            "assumptions": [],
            "raw_response": text[:4000],
        }

    # Normalize minimal shape.
    parsed["reviewer"] = parsed.get("reviewer") or reviewer_name
    parsed["summary"] = parsed.get("summary") or ""
    parsed["findings"] = parsed.get("findings") or []
    parsed["checks_covered"] = parsed.get("checks_covered") or []
    parsed["assumptions"] = parsed.get("assumptions") or []
    return parsed


def _max_severity(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "info"
    top = max((SEVERITY_ORDER.get((f.get("severity") or "info").lower(), 0) for f in findings), default=0)
    for sev, rank in SEVERITY_ORDER.items():
        if rank == top:
            return sev
    return "info"


def _sort_key_finding(f: dict[str, Any]) -> tuple[str, str, str]:
    code = str(f.get("code") or "")
    msg = str(f.get("message") or "")
    ref = str(f.get("ref") or "")
    return (code, ref, msg)


def _repackage_merged_findings(
    merged_raw: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Errors first, then warnings (sorted); all **info** collapsed into one compact bundle."""
    for f in merged_raw:
        sev = (f.get("severity") or "info")
        if isinstance(sev, str):
            sev = sev.lower()
        if sev not in ("error", "warning", "info"):
            sev = "warning"
        f["severity"] = sev
    errors = [f for f in merged_raw if f.get("severity") == "error"]
    warnings = [f for f in merged_raw if f.get("severity") == "warning"]
    infos = [f for f in merged_raw if f.get("severity") == "info"]

    errors.sort(key=_sort_key_finding)
    warnings.sort(key=_sort_key_finding)

    info_cap = 40
    items = []
    for f in infos[:info_cap]:
        items.append(
            {
                "c": f.get("code"),
                "m": (f.get("message") or "")[:240],
            }
        )
    info_bundle: dict[str, Any] = {
        "count": len(infos),
        "items": items,
    }
    if len(infos) > info_cap:
        info_bundle["truncated_after"] = info_cap

    return errors + warnings, info_bundle


def _human_summary(
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    info_count: int,
) -> dict[str, Any]:
    """Short, scan-friendly text derived from counts (no extra LLM call)."""
    ne, nw = len(errors), len(warnings)

    def _one_line(f: dict[str, Any]) -> str:
        c = f.get("code") or "?"
        m = (f.get("message") or "").strip()
        if len(m) > 140:
            m = m[:137] + "..."
        r = f.get("ref")
        prefix = f"{r}: " if r else ""
        return f"{c} — {prefix}{m}"

    must_fix = [_one_line(f) for f in errors[:8]]
    double_check = [_one_line(f) for f in warnings[:10]]

    if ne > 0:
        headline = (
            f"{ne} error(s) found — treat as must-fix before relying on this netlist."
        )
        tone = "blocking"
    elif nw > 0:
        headline = (
            f"No errors; {nw} warning(s) — design may be OK; double-check the listed items."
        )
        tone = "caution"
    else:
        headline = "No errors or warnings from this review pass."
        tone = "ok"

    if info_count and ne == 0 and nw == 0:
        headline += f" ({info_count} info note(s) bundled below — optional reading.)"

    youre_probably_fine_if = (
        "No errors, few or no warnings, and your assumptions in the JSON match the real board "
        "(rails, part choice, pinouts)."
        if ne == 0
        else "After errors are resolved and warnings reviewed against the datasheet."
    )

    return {
        "tone": tone,
        "headline": headline,
        "must_fix": must_fix,
        "double_check": double_check,
        "youre_probably_fine_if": youre_probably_fine_if,
    }


def _max_gate_severity(findings: list[dict[str, Any]]) -> str:
    """Highest severity ignoring **info** (used for --fail-on; info-only → none)."""
    actionable = [
        f
        for f in findings
        if (f.get("severity") or "").lower() in ("warning", "error")
    ]
    if not actionable:
        return "none"
    if any((f.get("severity") or "").lower() == "error" for f in actionable):
        return "error"
    return "warning"


def run_two_llm_review(
    data: dict[str, Any],
    *,
    model_structural: str = "gemini-2.5-flash",
    model_electrical: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    client = _get_gemini_client()
    deterministic = _deterministic_prechecks(data)

    structural = _call_reviewer(
        client=client,
        model=model_structural,
        reviewer_name="A_STRUCTURAL",
        reviewer_focus=(
            "Netlist structure correctness, connectivity completeness, "
            "naming consistency, floating nets, missing required connections. "
            "Intentionally unused pins: net name **NC_<purpose>** (single pin on that net) "
            "or **omit** the pin from `connections` — do not flag single-endpoint **NC_*** nets."
        ),
        data=data,
        deterministic_findings=deterministic,
    )

    electrical = _call_reviewer(
        client=client,
        model=model_electrical,
        reviewer_name="B_ELECTRICAL",
        reviewer_focus=(
            "Electrical behavior plausibility: rail values, logic-level margins "
            "(VIH/VIL risk checks), reset/boot/debug behavior, oscillator and "
            "load capacitors, pull-up/pull-down sanity, interface compatibility."
        ),
        data=data,
        deterministic_findings=deterministic,
    )

    merged_raw: list[dict[str, Any]] = []
    merged_raw.extend(deterministic)
    merged_raw.extend(structural.get("findings", []))
    merged_raw.extend(electrical.get("findings", []))

    findings_ordered, info_bundle = _repackage_merged_findings(merged_raw)
    err_list = [f for f in findings_ordered if (f.get("severity") or "").lower() == "error"]
    warn_list = [f for f in findings_ordered if (f.get("severity") or "").lower() == "warning"]
    human = _human_summary(err_list, warn_list, info_bundle.get("count") or 0)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_name": data.get("project_name", "LLM_Project"),
        "models": {
            "structural": model_structural,
            "electrical": model_electrical,
        },
        "deterministic_findings": deterministic,
        "reviewer_reports": {
            "structural": structural,
            "electrical": electrical,
        },
        "merged": {
            # Order: scan-friendly summary → severity gate → counts →
            # actionable findings (errors, then warnings) → compact info bundle.
            "human_summary": human,
            "max_severity": _max_severity(merged_raw),
            "gate_severity": _max_gate_severity(merged_raw),
            "finding_counts": {
                "error": len(err_list),
                "warning": len(warn_list),
                "info": info_bundle.get("count", 0),
                "total": len(merged_raw),
            },
            "finding_count": len(merged_raw),
            "findings": findings_ordered,
            "info": info_bundle,
        },
    }
    return report


def severity_meets_or_exceeds(found: str, threshold: str) -> bool:
    """Compare *found* (use gate_severity from report) to *threshold*.

    threshold **none** → never fail. **info** is not used as a threshold (use gate_severity).
    """
    if threshold == "none":
        return False
    f = _GATE_ORDER.get((found or "none").lower(), 0)
    t = _GATE_ORDER.get(threshold.lower(), 99)
    return f >= t


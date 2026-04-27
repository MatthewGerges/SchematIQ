"""
User-editable mapping from LLM part strings to KiCad library:symbol names.

Prefer adding entries in config/symbol_aliases.json over hard-coding in Python.
"""

import json
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
_ALIASES_PATH = os.path.join(_CODE_ROOT, "config", "symbol_aliases.json")
_aliases_cache = None


def invalidate_aliases_cache():
    """Call after editing ``symbol_aliases.json`` on disk (e.g. LLM repair merge)."""
    global _aliases_cache
    _aliases_cache = None


def load_symbol_aliases():
    """Return dict[str, str] of part -> lib:symbol. Missing file => {}."""
    global _aliases_cache
    if _aliases_cache is not None:
        return _aliases_cache
    out = {}
    if os.path.isfile(_ALIASES_PATH):
        try:
            with open(_ALIASES_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                if k.startswith("_") or not isinstance(k, str) or not isinstance(v, str):
                    continue
                out[k.strip()] = v.strip()
        except (json.JSONDecodeError, OSError):
            out = {}
    _aliases_cache = out
    return _aliases_cache


def apply_symbol_alias(part_name):
    """If part_name is a key in symbol_aliases.json, return mapped value; else unchanged."""
    if not part_name:
        return part_name
    aliases = load_symbol_aliases()
    return aliases.get(part_name.strip(), part_name.strip())


def normalize_symbol_lookup(part_after_alias):
    """Built-in remaps (after JSON aliases). Matches schematic_generator logic."""
    p = (part_after_alias or "").strip()
    if not p:
        return p
    if p.startswith("LED_") or p.startswith("LED_TH:"):
        return "Device:LED"
    if p.startswith("Transistor_FET:"):
        return "Transistor_FET:Q_NMOS_GDS"
    if p == "Connector:1x01":
        return "Connector_Generic:Conn_01x01"
    if p == "Connector:1x02":
        return "Connector_Generic:Conn_01x02"
    if p == "Button_Switch_SMD" or "Button_Switch" in p:
        return "Switch:SW_Push"
    if p.startswith("Connector_Generic:"):
        _lib, _sym = p.split(":", 1)
        if _sym.startswith("Connector_"):
            return f"Connector_Generic:Conn_{_sym[len('Connector_'):]}"
    return p


def get_aliases_path():
    return _ALIASES_PATH

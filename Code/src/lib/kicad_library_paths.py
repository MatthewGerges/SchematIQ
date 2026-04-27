"""
Locate official KiCad symbol libraries inside the repo (clone).

Prefer ``<repo>/component_database/kicad-symbols`` (see README clone instructions),
then fall back to ``<repo>/KICAD_Library/kicad-symbols``.

KiCad upstream ships either:
  - legacy **packed** libraries: ``Device.kicad_sym`` (many symbols per file), or
  - **unpacked** git layout: ``Device.kicad_symdir/*.kicad_sym`` (matches KiCad’s
    library names in the symbol chooser).
"""

from __future__ import annotations

import os
import re

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))


def _discover_repo_root() -> str:
    """
    Directory that contains ``component_database/kicad-symbols`` or ``KICAD_Library/kicad-symbols``.

    Supports both ``<repo>/Code/`` and ``<repo>/KiCad10_Cursor/Code/`` layouts by walking parents
    of *Code* until a marker path exists, then defaulting to the parent of *Code*.
    """
    p = os.path.abspath(_CODE_ROOT)
    for _ in range(12):
        for rel in (
            ("component_database", "kicad-symbols"),
            ("KICAD_Library", "kicad-symbols"),
        ):
            root = os.path.join(p, *rel)
            if not os.path.isdir(root):
                continue
            try:
                if os.listdir(root):
                    return p
            except OSError:
                continue
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return os.path.dirname(_CODE_ROOT)


_REPO_ROOT = _discover_repo_root()


def repo_root() -> str:
    """Repository root containing official KiCad library trees (see ``_discover_repo_root``)."""
    return _REPO_ROOT


def official_kicad_symbols_root() -> str | None:
    """Return the first existing official symbol tree, or None."""
    for rel in (
        ("component_database", "kicad-symbols"),
        ("KICAD_Library", "kicad-symbols"),
    ):
        p = os.path.join(_REPO_ROOT, *rel)
        if os.path.isdir(p):
            try:
                if os.listdir(p):
                    return p
            except OSError:
                continue
    return None


def official_library_packed_path(lib_name: str) -> str | None:
    """Path to ``LibName.kicad_sym`` if present (packed layout)."""
    root = official_kicad_symbols_root()
    if not root:
        return None
    p = os.path.join(root, f"{lib_name}.kicad_sym")
    return p if os.path.isfile(p) else None


def official_library_symdir_path(lib_name: str) -> str | None:
    """Path to ``LibName.kicad_symdir`` if present (unpacked GitLab layout)."""
    root = official_kicad_symbols_root()
    if not root:
        return None
    d = os.path.join(root, f"{lib_name}.kicad_symdir")
    return d if os.path.isdir(d) else None


def find_unpacked_symbol_file(symdir: str, symbol_name: str) -> str | None:
    """Return path to a ``.kicad_sym`` file inside *symdir* for *symbol_name*."""
    direct = os.path.join(symdir, f"{symbol_name}.kicad_sym")
    if os.path.isfile(direct):
        return direct
    try:
        for fn in os.listdir(symdir):
            if not fn.endswith(".kicad_sym"):
                continue
            fp = os.path.join(symdir, fn)
            if not os.path.isfile(fp):
                continue
            if _file_defines_symbol(fp, symbol_name):
                return fp
    except OSError:
        pass
    return None


def _file_defines_symbol(sym_path: str, symbol_name: str) -> bool:
    needle = f'(symbol "{symbol_name}"'
    try:
        with open(sym_path, "r", encoding="utf-8") as f:
            chunk = f.read(65536)
        return needle in chunk
    except OSError:
        return False


def lib_prefix_from_unpacked_symbol_file(sym_path: str) -> str:
    """Derive ``Connector_Generic`` from ``.../Connector_Generic.kicad_symdir/Conn_01x02.kicad_sym``."""
    parent = os.path.basename(os.path.dirname(sym_path))
    if parent.endswith(".kicad_symdir"):
        return parent[: -len(".kicad_symdir")]
    return "SchematIQ"


def sym_lib_uri_base_for_generated_project(output_dir: str) -> str:
    """``${KIPRJMOD}/...`` path to official symbols for ``sym-lib-table`` (no trailing slash)."""
    sym_root = official_kicad_symbols_root()
    if sym_root:
        rel = os.path.relpath(sym_root, os.path.abspath(output_dir))
        return "${KIPRJMOD}/" + rel.replace(os.sep, "/")
    # Legacy layout string if nothing cloned yet
    return "${KIPRJMOD}/../../KICAD_Library/kicad-symbols"


def official_symbol_uri_for_table(lib_nick: str, kiprjmod_base: str) -> tuple[str, bool]:
    """
    Return (uri, ok) for one row in sym-lib-table.

    *ok* is False if neither packed nor symdir exists (caller may skip or use app fallback).
    """
    packed = official_library_packed_path(lib_nick)
    if packed:
        return f"{kiprjmod_base}/{lib_nick}.kicad_sym", True
    symdir = official_library_symdir_path(lib_nick)
    if symdir:
        return f"{kiprjmod_base}/{lib_nick}.kicad_symdir", True
    return f"{kiprjmod_base}/{lib_nick}.kicad_sym", False

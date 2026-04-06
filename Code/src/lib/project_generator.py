"""Generate KiCad project files (.kicad_pro and root .kicad_sch) from project JSON."""

import json
import math
import uuid
import os


# ─── Layout constants for root schematic ─────────────────────────────────────
BOX_W = 45.0             # sheet box width  (mm)
BOX_H = 15.0             # sheet box height (mm)
X_MARGIN = 25.0          # left margin
Y_MARGIN = 25.0          # top margin
X_SPACING = 60.0         # center-to-center horizontal distance between boxes
Y_SPACING = 30.0         # center-to-center vertical distance between boxes
# A4 landscape usable width ≈ 297 - 2*25 = 247 mm
PAGE_W = 297.0


def generate_root_schematic(json_path, output_dir, project_name=None):
    """Generate root .kicad_sch with clean sheet boxes (no hier pins) from JSON.

    Sheet boxes are laid out in an adaptive grid that scales to the
    number of pages.

    Returns (output_path, root_uuid, sheet_uuids)
      sheet_uuids: list of (uuid_str, sheet_name) for .kicad_pro
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if project_name is None:
        project_name = data.get("project_name", "Project")

    sheets_def = data["sheets"]
    n = len(sheets_def)
    if n == 0:
        raise ValueError("No sheets found in JSON. Ensure the project JSON includes a non-empty 'sheets' list.")

    # Compute grid dimensions
    max_cols = max(1, int((PAGE_W - 2 * X_MARGIN) / X_SPACING))
    cols = min(n, max_cols)
    rows = math.ceil(n / cols)

    root_uuid = str(uuid.uuid4())
    sheet_items = []

    for idx, s_def in enumerate(sheets_def):
        col = idx % cols
        row = idx // cols
        sx = round(X_MARGIN + col * X_SPACING, 2)
        sy = round(Y_MARGIN + row * Y_SPACING, 2)

        sheet_items.append({
            "uuid": str(uuid.uuid4()),
            "at": (sx, sy),
            "size": (BOX_W, BOX_H),
            "name": s_def["name"],
            "file": s_def["file"],
            "page": s_def["page"],
        })

    # ── Build KiCad s-expression ──────────────────────────────────────────
    t = '(kicad_sch\n'
    t += '\t(version 20250114)\n'
    t += '\t(generator "SchematIQ")\n'
    t += '\t(generator_version "9.0")\n'
    t += f'\t(uuid "{root_uuid}")\n'
    t += '\t(paper "A4")\n'
    t += '\t(lib_symbols)\n\n'

    for sh in sheet_items:
        sx, sy = sh["at"]
        sw, sh_h = sh["size"]

        t += '\t(sheet\n'
        t += f'\t\t(at {sx} {sy})\n'
        t += f'\t\t(size {sw} {sh_h})\n'
        t += '\t\t(exclude_from_sim no)\n'
        t += '\t\t(in_bom yes)\n'
        t += '\t\t(on_board yes)\n'
        t += '\t\t(dnp no)\n'
        t += '\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type solid)\n\t\t)\n'
        t += '\t\t(fill\n\t\t\t(color 0 0 0 0.0000)\n\t\t)\n'
        t += f'\t\t(uuid "{sh["uuid"]}")\n'

        # Sheetname — above the box
        t += f'\t\t(property "Sheetname" "{sh["name"]}"\n'
        t += f'\t\t\t(at {sx} {round(sy - 0.68, 2)} 0)\n'
        t += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
        t += '\t\t\t\t)\n\t\t\t\t(justify left bottom)\n\t\t\t)\n'
        t += '\t\t)\n'

        # Sheetfile — below the box
        t += f'\t\t(property "Sheetfile" "{sh["file"]}"\n'
        t += f'\t\t\t(at {sx} {round(sy + sh_h + 0.2, 2)} 0)\n'
        t += '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
        t += '\t\t\t\t)\n\t\t\t\t(justify left top)\n\t\t\t)\n'
        t += '\t\t)\n'

        t += '\t)\n\n'

    # Sheet instances (page numbering)
    t += '\t(sheet_instances\n'
    t += '\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n'
    for sh in sheet_items:
        t += f'\t\t(path "/{sh["uuid"]}"\n'
        t += f'\t\t\t(page "{sh["page"]}")\n'
        t += '\t\t)\n'
    t += '\t)\n'
    t += '\t(embedded_fonts no)\n'
    t += ')\n'

    # Write
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{project_name}.kicad_sch")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(t)
    print(f"Generated root schematic: {output_path}")

    sheet_uuids = [(root_uuid, "Root")] + [(sh["uuid"], sh["name"]) for sh in sheet_items]
    return output_path, root_uuid, sheet_uuids


def generate_project_file(project_name, output_dir, sheet_uuids=None):
    """Generate a minimal .kicad_pro file."""
    project_data = {
        "meta": {"filename": f"{project_name}.kicad_pro", "version": 2},
        "schematic": {
            "annotate_start_num": 0,
            "bom_fmt_settings": {"field_delimiter": ",", "name": "CSV",
                                 "ref_delimiter": ",", "string_delimiter": "\""},
            # Match our schematic snapping (50 mil).
            "connection_grid_size": 50.0,
            "drawing": {},
            "page_layout_descr_file": ""
        },
        "sheets": [],
        "text_variables": {}
    }

    if sheet_uuids:
        for uid, name in sheet_uuids:
            project_data["sheets"].append([uid, name])

    output_path = os.path.join(output_dir, f"{project_name}.kicad_pro")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project_data, f, indent=2)
    print(f"Generated project file: {output_path}")
    _write_sym_lib_table(output_dir)
    return output_path


def _write_sym_lib_table(output_dir: str) -> None:
    """Write a project-local sym-lib-table that includes the `SchematIQ` nickname.

    Even though we embed symbols in schematics, KiCad/ERC still warns if a lib_id
    uses a nickname that isn't in the current symbol library table.
    """
    os.makedirs(output_dir, exist_ok=True)
    lib_path = os.path.join(output_dir, "_schematiq_embedded.kicad_sym")
    if not os.path.exists(lib_path):
        # Minimal valid KiCad symbol library file.
        with open(lib_path, "w", encoding="utf-8") as f:
            f.write('(kicad_symbol_lib (version 20211014) (generator "SchematIQ"))\n')

    table_path = os.path.join(output_dir, "sym-lib-table")

    # Compute relative path from output_dir to KICAD_Library/kicad-symbols.
    # output_dir is e.g. .../Code/generated/<ProjectName>/
    # KICAD_Library lives at the repo root: .../<repo>/KICAD_Library/
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _repo_root = os.path.dirname(_project_root)
    _kicad_lib = os.path.join(_repo_root, "KICAD_Library", "kicad-symbols")
    try:
        _rel = os.path.relpath(_kicad_lib, os.path.abspath(output_dir))
    except ValueError:
        _rel = _kicad_lib
    # Use ${KIPRJMOD} + computed relative path so it works regardless of nesting depth.
    repo_libs = "${KIPRJMOD}/" + _rel.replace(os.sep, "/")

    # Also try KiCad's bundled symbols as a fallback.
    kicad_app_syms = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"

    libs: list[tuple[str, str, str]] = [
        ("SchematIQ", "${KIPRJMOD}/_schematiq_embedded.kicad_sym", "SchematIQ embedded symbols"),
    ]
    # Prefer repo-local if the directory exists; otherwise fall back to KiCad.app.
    if os.path.isdir(_kicad_lib):
        base = repo_libs
    elif os.path.isdir(kicad_app_syms):
        base = kicad_app_syms
    else:
        base = repo_libs  # best-effort

    for nick in ("power", "Connector_Generic", "Regulator_Linear", "Device"):
        libs.append((nick, f"{base}/{nick}.kicad_sym", f"KiCad {nick} symbols"))

    lines = ["(sym_lib_table\n"]
    for name, uri, descr in libs:
        lines.append(f'  (lib (name "{name}") (type "KiCad") (uri "{uri}") (options "") (descr "{descr}"))\n')
    lines.append(")\n")

    with open(table_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

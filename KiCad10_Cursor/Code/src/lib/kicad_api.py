import re
import uuid
import os
from pathlib import Path

# Repo root is parent of the `Code/` application directory (sibling: KICAD_Library/).
_CODE_ROOT = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _CODE_ROOT.parent
DEFAULT_SYMBOL_PATH = str((_REPO_ROOT / "KICAD_Library" / "Symbols").resolve()) + os.sep

# KiCad 10 fields that KiCad 9 doesn't understand — stripped during embedding.
# Each pattern matches an entire line (leading whitespace through newline).
_V10_ONLY_PATTERNS = [
    re.compile(r'^[ \t]*\(in_pos_files\s+(yes|no)\)[ \t]*\n', re.MULTILINE),
    re.compile(r'^[ \t]*\(duplicate_pin_numbers_are_jumpers\s+(yes|no)\)[ \t]*\n', re.MULTILINE),
    re.compile(r'^[ \t]*\(show_name\s+(yes|no)\)[ \t]*\n', re.MULTILINE),
    re.compile(r'^[ \t]*\(do_not_autoplace\s+(yes|no)\)[ \t]*\n', re.MULTILINE),
]


def _sanitize_v10_symbol(symbol_def):
    """Strip KiCad-10-only S-expression fields so the symbol loads in KiCad 9."""
    for pat in _V10_ONLY_PATTERNS:
        symbol_def = pat.sub('', symbol_def)
    return symbol_def

def create_schematic_data(project_name, sheet_uuid):
    """Initializes a new schematic data structure."""
    return {
        "version": "20250114",
        "generator": "SchematIQ",
        "uuid": sheet_uuid,
        "paper": "A4",
        "lib_symbols": [],
        "items": []
    }

def _extract_symbol_from_lib(lib_content):
    """
    A simple, non-robust parser to extract the main (symbol...) block
    from a .kicad_sym file.
    """
    start = lib_content.find("(symbol")
    if start == -1: return None, None
    balance = 0
    end = -1
    for i in range(start, len(lib_content)):
        if lib_content[i] == '(' : balance += 1
        elif lib_content[i] == ')': balance -= 1
        if balance == 0:
            end = i + 1
            break
    if end == -1: return None, None
    symbol_def = lib_content[start:end]
    id_start = symbol_def.find('"') + 1
    id_end = symbol_def.find('"', id_start)
    lib_id = symbol_def[id_start:id_end]
    return lib_id, symbol_def


def _rename_symbol_id(symbol_def: str, new_id: str) -> str:
    """Rename the top-level `(symbol "<id>" ...)` to `new_id` (single replacement)."""
    # Replace only the first occurrence (top-level symbol name).
    return re.sub(r'^\(symbol\s+"[^"]+"', f'(symbol "{new_id}"', symbol_def, count=1, flags=re.MULTILINE)

def _extract_named_symbol(lib_content, target_name):
    """Extract a specific top-level symbol by name from a packed library file.

    In packed KiCad 9 libraries, one .kicad_sym contains many symbols.
    Sub-symbols (e.g. "NE555D_0_1") are nested inside the parent and are
    captured automatically by the balanced-paren extraction.

    The closing quote + newline in the search pattern guarantees we won't
    match sub-symbols whose names are longer (e.g. searching "NE555D"
    won't match "NE555D_0_1" because the quote closes the name exactly).

    Returns (lib_id, symbol_def) or (None, None).
    """
    search_for = f'(symbol "{target_name}"\n'
    idx = lib_content.find(search_for)
    if idx == -1:
        return None, None

    start = idx
    balance = 0
    end = -1
    for i in range(start, len(lib_content)):
        if lib_content[i] == '(':
            balance += 1
        elif lib_content[i] == ')':
            balance -= 1
        if balance == 0:
            end = i + 1
            break
    if end == -1:
        return None, None
    return target_name, lib_content[start:end]


def get_symbol_block(content, symbol_name):
    """Return the (symbol ...) block for a named symbol from library content, or None.
    Used e.g. to parse pin positions from a packed .kicad_sym file."""
    _, block = _extract_named_symbol(content, symbol_name)
    return block


def embed_symbol_from_file(schematic_data, symbol_name, library_path=None, *, lib_prefix: str = "SchematIQ"):
    """
    Reads a .kicad_sym file, extracts the symbol definition, and adds it
    to the schematic data's embedded library.
    Returns the lib_id of the embedded symbol.

    Supports both:
      - Single-symbol files (custom library, one symbol per .kicad_sym)
      - Packed library files (official KiCad 9, many symbols per .kicad_sym)
    """
    if library_path is None:
        library_path = DEFAULT_SYMBOL_PATH
    symbol_filepath = os.path.join(library_path, f"{symbol_name}.kicad_sym")
    try:
        with open(symbol_filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: Symbol file not found at {symbol_filepath}")
        return None
    lib_id, symbol_definition = _extract_symbol_from_lib(content)
    # Unpacked official symbols may use cross-file `(extends "Parent")` in
    # `.kicad_symdir`; flatten from sibling files so KiCad renders correctly.
    if lib_id and symbol_definition and '(extends "' in symbol_definition:
        flat = _resolve_full_symbol_from_symdir(library_path, lib_id)
        if flat:
            symbol_definition = flat
    if lib_id and symbol_definition:
        symbol_definition = _sanitize_v10_symbol(symbol_definition)
        # Use Lib:Sym form so KiCad doesn't treat this as library "" (ERC warning).
        full_id = f"{lib_prefix}:{lib_id}" if ":" not in lib_id else lib_id
        symbol_definition = _rename_symbol_id(symbol_definition, full_id)
        schematic_data["lib_symbols"].append(symbol_definition)
        print(f"Embedded symbol '{full_id}' from {symbol_filepath}")
        return full_id
    else:
        print(f"Error: Could not extract symbol from {symbol_filepath}")
        return None


def _extract_sub_symbols(symbol_def, symbol_name):
    """Extract nested ``(symbol "name_N_N" ...)`` blocks from a parent definition."""
    blocks = []
    pattern = rf'\(symbol\s+"{re.escape(symbol_name)}_\d+_\d+"'
    for m in re.finditer(pattern, symbol_def):
        start = m.start()
        balance = 0
        end = start
        for i in range(start, len(symbol_def)):
            if symbol_def[i] == '(':
                balance += 1
            elif symbol_def[i] == ')':
                balance -= 1
            if balance == 0:
                end = i + 1
                break
        blocks.append(symbol_def[start:end])
    return blocks


def _resolve_full_symbol(content, symbol_name):
    """Resolve a symbol from packed library content, flattening ``(extends ...)``
    recursively so the result is fully self-contained (graphics + pins inlined).

    This matches what KiCad eeschema does when it saves an embedded symbol.
    """
    _, child_def = _extract_named_symbol(content, symbol_name)
    if not child_def:
        return None

    extends_m = re.search(r'\(extends\s+"([^"]+)"\)', child_def)
    if not extends_m:
        return child_def

    parent_name = extends_m.group(1)
    parent_def = _resolve_full_symbol(content, parent_name)
    if not parent_def:
        return child_def

    # Remove the (extends ...) line from child
    result = re.sub(r'\n?\s*\(extends\s+"[^"]+"\)', '', child_def, count=1)

    # Add (exclude_from_sim no) (in_bom yes) (on_board yes) if child doesn't have them
    if '(exclude_from_sim' not in result:
        result = re.sub(
            rf'(\(symbol\s+"{re.escape(symbol_name)}")',
            r'\1\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)',
            result,
            count=1,
        )

    # Copy (embedded_fonts no) from parent if present and child lacks it
    if '(embedded_fonts' not in result and '(embedded_fonts' in parent_def:
        ef_m = re.search(r'\(embedded_fonts\s+\w+\)', parent_def)
        if ef_m:
            close = result.rfind(')')
            result = result[:close] + f'\t\t{ef_m.group(0)}\n\t' + result[close:]

    # Extract graphical + pin sub-symbols from the (resolved) parent
    sub_blocks = _extract_sub_symbols(parent_def, parent_name)
    renamed_subs = []
    for sub in sub_blocks:
        renamed = sub.replace(f'"{parent_name}_', f'"{symbol_name}_')
        renamed_subs.append(renamed)

    if renamed_subs:
        close = result.rfind(')')
        sub_text = '\n\t\t'.join([''] + renamed_subs) + '\n\t'
        result = result[:close] + sub_text + result[close:]

    return result


def _resolve_full_symbol_from_symdir(symdir: str, symbol_name: str, _seen: set[str] | None = None):
    """Resolve one symbol from an unpacked ``*.kicad_symdir`` tree.

    KiCad-10 libraries often store one symbol per file where children use
    ``(extends "Parent")`` across files. Flatten those parent graphics/pins.
    """
    if _seen is None:
        _seen = set()
    if symbol_name in _seen:
        return None
    _seen.add(symbol_name)

    fp = os.path.join(symdir, f"{symbol_name}.kicad_sym")
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    _, child_def = _extract_symbol_from_lib(content)
    if not child_def:
        return None

    extends_m = re.search(r'\(extends\s+"([^"]+)"\)', child_def)
    if not extends_m:
        return child_def

    parent_name = extends_m.group(1)
    parent_def = _resolve_full_symbol_from_symdir(symdir, parent_name, _seen)
    if not parent_def:
        return child_def

    result = re.sub(r'\n?\s*\(extends\s+"[^"]+"\)', '', child_def, count=1)
    if '(exclude_from_sim' not in result:
        result = re.sub(
            rf'(\(symbol\s+"{re.escape(symbol_name)}")',
            r'\1\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)',
            result,
            count=1,
        )
    if '(embedded_fonts' not in result and '(embedded_fonts' in parent_def:
        ef_m = re.search(r'\(embedded_fonts\s+\w+\)', parent_def)
        if ef_m:
            close = result.rfind(')')
            result = result[:close] + f'\t\t{ef_m.group(0)}\n\t' + result[close:]

    sub_blocks = _extract_sub_symbols(parent_def, parent_name)
    renamed_subs = []
    for sub in sub_blocks:
        renamed_subs.append(sub.replace(f'"{parent_name}_', f'"{symbol_name}_'))
    if renamed_subs:
        close = result.rfind(')')
        sub_text = '\n\t\t'.join([''] + renamed_subs) + '\n\t'
        result = result[:close] + sub_text + result[close:]
    return result


def embed_symbol_from_packed_lib(schematic_data, symbol_name, library_file):
    """Extract and embed a named symbol from a packed (multi-symbol) .kicad_sym.

    If the symbol uses ``(extends "ParentName")``, the parent's graphical and
    pin sub-symbols are copied into the child (flattened) so the embedded
    definition is fully self-contained — matching what KiCad eeschema produces.
    The parent symbol is NOT embedded separately.

    Args:
        symbol_name: e.g. "LM1117DT-3.3"
        library_file: full path to the packed .kicad_sym, e.g. Regulator_Linear.kicad_sym
    """
    lib_nick = os.path.splitext(os.path.basename(library_file))[0]
    full_name = f"{lib_nick}:{symbol_name}"

    if full_name in _get_embedded_names(schematic_data):
        return full_name

    try:
        with open(library_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: Library file not found at {library_file}")
        return None

    resolved = _resolve_full_symbol(content, symbol_name)
    if not resolved:
        print(f"Error: Symbol '{symbol_name}' not found in {library_file}")
        return None

    resolved = _sanitize_v10_symbol(resolved)
    resolved = _rename_symbol_id(resolved, full_name)
    schematic_data["lib_symbols"].append(resolved)
    print(f"Embedded symbol '{full_name}' from {library_file}")
    return full_name


def _get_embedded_names(schematic_data):
    """Return set of symbol names already in the embedded library."""
    names = set()
    for sym_def in schematic_data["lib_symbols"]:
        match = re.search(r'\(symbol\s+"([^"]+)"', sym_def)
        if match:
            names.add(match.group(1))
    return names

def extract_symbol_properties(schematic_data, lib_id):
    """Extract Footprint, Datasheet, Description from an already-embedded symbol.

    Searches lib_symbols for a definition matching *lib_id* and returns a dict
    with any properties it finds.  Falls back to an empty dict.
    """
    for sym_def in schematic_data["lib_symbols"]:
        m = re.search(r'\(symbol\s+"([^"]+)"', sym_def)
        if m and m.group(1) == lib_id:
            props = {}
            for prop_name in ("Footprint", "Datasheet", "Description"):
                pm = re.search(rf'\(property\s+"{prop_name}"\s+"([^"]*)"', sym_def)
                if pm:
                    props[prop_name] = pm.group(1)
            return props
    return {}


def place_component(schematic_data, lib_id, reference, value, position,
                    angle=0, footprint="", pins=None,
                    datasheet="~", description=""):
    """Adds a component instance to the schematic data.

    Args:
        pins: list of pin numbers (e.g. ["1", "2"]) for pin instance UUIDs.
              If None, no pin instances are added.
    """
    component = {
        "type": "symbol",
        "lib_id": lib_id,
        "at": (position[0], position[1], angle),
        "uuid": str(uuid.uuid4()),
        "properties": {
            "Reference": reference,
            "Value": value,
            "Footprint": footprint,
            "Datasheet": datasheet,
            "Description": description,
        },
        "pins": pins or []
    }
    schematic_data["items"].append(component)
    print(f"Placed {reference} ({lib_id}) at {position}")
    return schematic_data

def _format_properties(properties, parent_at):
    """Formats the properties block for a symbol."""
    prop_text = ""
    ref_at_y = parent_at[1] + 2.54 
    val_at_y = parent_at[1] - 2.54
    
    if "Reference" in properties:
        prop_text += f'\n\t\t(property "Reference" "{properties["Reference"]}" (at {parent_at[0]} {ref_at_y} 0) (effects (font (size 1.27 1.27))))'
    if "Value" in properties:
        prop_text += f'\n\t\t(property "Value" "{properties["Value"]}" (at {parent_at[0]} {val_at_y} 0) (effects (font (size 1.27 1.27))))'
    
    footprint = properties.get("Footprint", "")
    prop_text += f'\n\t\t(property "Footprint" "{footprint}" (at {parent_at[0]} {parent_at[1]} 0) (effects (font (size 1.27 1.27)) (hide yes)))'
    prop_text += f'\n\t\t(property "Datasheet" "" (at {parent_at[0]} {parent_at[1]} 0) (effects (font (size 1.27 1.27)) (hide yes)))'
    return prop_text

def generate_schematic_text(schematic_data):
    """Generates the full .kicad_sch file content from the data structure."""
    text = f'(kicad_sch (version {schematic_data["version"]}) (generator "{schematic_data["generator"]}")\n'
    text += f'\t(uuid "{schematic_data["uuid"]}")\n'
    text += f'\t(paper "{schematic_data["paper"]}")\n\n'

    if schematic_data["lib_symbols"]:
        text += "\t(lib_symbols\n"
        for symbol_def in schematic_data["lib_symbols"]:
            text += f"\t{symbol_def}\n"
        text += "\t)\n\n"

    for item in schematic_data["items"]:
        if item["type"] == "symbol":
            text += "\t(symbol\n"
            text += f'\t\t(lib_id "{item["lib_id"]}")\n'
            text += f'\t\t(at {item["at"][0]} {item["at"][1]} {item["at"][2]})\n'
            text += f'\t\t(uuid "{item["uuid"]}")'
            text += _format_properties(item["properties"], item["at"])
            text += "\n\t)\n"
            
    text += ")\n"
    return text

def save_schematic(schematic_data, file_path):
    """Generates the text and saves it to a file."""
    content = generate_schematic_text(schematic_data)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Schematic saved to {file_path}")

import uuid
import os

# Set a default path for the symbol library. This can be changed in the main script.
DEFAULT_SYMBOL_PATH = "/Users/matthewgerges/Documents/AI-PCB/ChipChat_Gemini/KICAD_Library/Symbols/"

def create_schematic_data(project_name, sheet_uuid):
    """Initializes a new schematic data structure."""
    return {
        "version": "20250114",
        "generator": "ChipChat_Gemini",
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
    # Find the first opening parenthesis of the symbol definition
    start = lib_content.find("(symbol")
    if start == -1:
        return None, None # Symbol not found

    # Find the matching closing parenthesis
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
        return None, None # Malformed symbol file

    symbol_def = lib_content[start:end]
    
    # Extract the lib_id
    id_start = symbol_def.find('"') + 1
    id_end = symbol_def.find('"', id_start)
    lib_id = symbol_def[id_start:id_end]

    return lib_id, symbol_def


def embed_symbol_from_file(schematic_data, symbol_name, library_path=None):
    """
    Reads a .kicad_sym file, extracts the symbol definition, and adds it
    to the schematic data's embedded library.
    Returns the lib_id of the embedded symbol.
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

    if lib_id and symbol_definition:
        schematic_data["lib_symbols"].append(symbol_definition)
        print(f"Embedded symbol '{lib_id}' from {symbol_filepath}")
        return lib_id
    else:
        print(f"Error: Could not extract symbol from {symbol_filepath}")
        return None


def place_component(schematic_data, lib_id, reference, value, position, angle=0):
    """Adds a component instance to the schematic data."""
    component = {
        "type": "symbol",
        "lib_id": lib_id,
        "at": (position[0], position[1], angle),
        "uuid": str(uuid.uuid4()),
        "properties": { "Reference": reference, "Value": value }
    }
    schematic_data["items"].append(component)
    print(f"Placed {reference} ({lib_id}) at {position}")
    return schematic_data

def _format_properties(properties, parent_at):
    """Formats the properties block for a symbol."""
    prop_text = ""
    ref_at_x = parent_at[0]
    ref_at_y = parent_at[1] + 2.54 
    val_at_x = parent_at[0]
    val_at_y = parent_at[1] - 2.54
    
    if "Reference" in properties:
        prop_text += f'\n\t\t(property "Reference" "{properties["Reference"]}" (at {ref_at_x} {ref_at_y} 0) (effects (font (size 1.27 1.27))))'
    if "Value" in properties:
        prop_text += f'\n\t\t(property "Value" "{properties["Value"]}" (at {val_at_x} {val_at_y} 0) (effects (font (size 1.27 1.27))))'

    prop_text += '\n\t\t(property "Footprint" "" (at {} {} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(parent_at[0], parent_at[1])
    prop_text += '\n\t\t(property "Datasheet" "" (at {} {} 0) (effects (font (size 1.27 1.27)) (hide yes)))'
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
    content = content.replace("\\n", "\n")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Schematic saved to {file_path}")

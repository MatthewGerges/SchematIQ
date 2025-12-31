import uuid

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

def add_symbol_definition(schematic_data, symbol_def):
    """Adds a symbol definition to the library symbols."""
    schematic_data["lib_symbols"].append(symbol_def)
    return schematic_data

def place_component(schematic_data, lib_id, reference, value, position, angle=0):
    """Adds a component instance to the schematic data."""
    component = {
        "type": "symbol",
        "lib_id": lib_id,
        "at": (position[0], position[1], angle),
        "uuid": str(uuid.uuid4()),
        "properties": {
            "Reference": reference,
            "Value": value,
        }
    }
    schematic_data["items"].append(component)
    print(f"Placed {reference} ({lib_id}) at {position}")
    return schematic_data

def _format_properties(properties, parent_at):
    """Formats the properties block for a symbol."""
    prop_text = ""
    # Place reference and value relative to the component's origin
    ref_at_x = parent_at[0]
    ref_at_y = parent_at[1] + 2.54 
    val_at_x = parent_at[0]
    val_at_y = parent_at[1] - 2.54
    
    if "Reference" in properties:
        prop_text += f'\n\t\t(property "Reference" "{properties["Reference"]}"\n'
        prop_text += f'\t\t\t(at {ref_at_x} {ref_at_y} 0)\n'
        prop_text += f'\t\t\t(effects (font (size 1.27 1.27)))\n\t\t)\n'

    if "Value" in properties:
        prop_text += f'\t\t(property "Value" "{properties["Value"]}"\n'
        prop_text += f'\t\t\t(at {val_at_x} {val_at_y} 0)\n'
        prop_text += f'\t\t\t(effects (font (size 1.27 1.27)))\n\t\t)\n'

    # Add other default hidden properties
    prop_text += '\t\t(property "Footprint" "" (at {} {} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'.format(parent_at[0], parent_at[1])
    prop_text += '\t\t(property "Datasheet" "" (at {} {} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'.format(parent_at[0], parent_at[1])
    return prop_text

def generate_schematic_text(schematic_data):
    """Generates the full .kicad_sch file content from the data structure."""
    
    # Header
    text = f'(kicad_sch (version {schematic_data["version"]}) (generator "{schematic_data["generator"]}")\n'
    text += f'\t(uuid "{schematic_data["uuid"]}")\n'
    text += f'\t(paper "{schematic_data["paper"]}")\n\n'

    # Library Symbols
    if schematic_data["lib_symbols"]:
        text += "\t(lib_symbols\n"
        for symbol_def in schematic_data["lib_symbols"]:
            text += f"{symbol_def}\n"
        text += "\t)\n\n"

    # Items (Symbols, Wires, etc.)
    for item in schematic_data["items"]:
        if item["type"] == "symbol":
            text += "\t(symbol\n"
            text += f'\t\t(lib_id "{item["lib_id"]}")\n'
            text += f'\t\t(at {item["at"][0]} {item["at"][1]} {item["at"][2]})\n'
            text += f'\t\t(uuid "{item["uuid"]}")'
            text += _format_properties(item["properties"], item["at"])
            text += "\t)\n"
            
    # Footer
    text += ")\n"
    return text

def save_schematic(schematic_data, file_path):
    """Generates the text and saves it to a file."""
    content = generate_schematic_text(schematic_data)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Schematic saved to {file_path}")
import uuid
import kicad_api

def generate_sheet(symbol_name, reference, value, footprint_name, output_filename, lib_path=None):
    """
    Generates a complete .kicad_sch file for a single component.

    Args:
        symbol_name (str): The name of the symbol (and .kicad_sym file).
        reference (str): The component reference (e.g., "U1").
        value (str): The component value.
        footprint_name (str): The footprint to be linked (e.g., "BME280.kicad_mod").
        output_filename (str): The name of the .kicad_sch file to generate.
        lib_path (str, optional): Path to the symbol library. Defaults to None.
    """
    print(f"--- Generating sheet: {output_filename} ---")
    # Page layout constants
    page_center_x = 297 / 2
    page_center_y = 210 / 2
    sheet_uuid = str(uuid.uuid4())

    # 1. Create the basic data structure for the sheet.
    schematic_data = kicad_api.create_schematic_data(output_filename, sheet_uuid)

    # 2. Embed the symbol from its .kicad_sym file.
    lib_id = kicad_api.embed_symbol_from_file(
        schematic_data,
        symbol_name,
        library_path=lib_path
    )

    # 3. If the symbol was found and embedded, place it with the footprint.
    if lib_id:
        kicad_api.place_component(
            schematic_data=schematic_data,
            lib_id=lib_id,
            reference=reference,
            value=value,
            position=(page_center_x, page_center_y),
            footprint=footprint_name
        )

    # 4. Save the generated schematic to its file.
    file_path = f"ChipChat_Project/{output_filename}"
    kicad_api.save_schematic(schematic_data, file_path)
    print(f"--- Finished sheet: {output_filename} ---\n")

def main():
    """
    Main function to generate all schematic files for the project.
    """
    # --- Generate BME280 Sensor Sheet ---
    generate_sheet(
        symbol_name="BME280",
        reference="U1",
        value="BME280",
        footprint_name="BME280.kicad_mod",
        output_filename="BME280_Sensor.kicad_sch"
    )

    # --- Generate MCP2210 USB to SPI Sheet ---
    generate_sheet(
        symbol_name="MCP2210-I_SO",
        reference="U1",
        value="MCP2210-I/SO",
        footprint_name="MCP2210-I_SO.kicad_mod",
        output_filename="MCP2210_USB_TO_SPI.kicad_sch"
    )

if __name__ == "__main__":
    main()
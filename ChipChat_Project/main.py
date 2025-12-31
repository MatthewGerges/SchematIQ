
import uuid
import kicad_api

def main(symbol_library_path=None):
    """
    Main function to generate the schematic.
    An optional path to a symbol library can be provided.
    """
    
    # --- Schematic Generation ---
    
    # A4 paper size is 297 x 210 mm. Let's place the component in the middle.
    page_center_x = 297 / 2
    page_center_y = 210 / 2
    
    # Each sheet needs a unique UUID.
    sheet_uuid = str(uuid.uuid4())
    
    # 1. Create the basic data structure for the sheet.
    schematic_data = kicad_api.create_schematic_data("MainSheet", sheet_uuid)
    
    # 2. Embed the desired symbol from a local file.
    # The function will use the default path from the API if symbol_library_path is None.
    lib_id = kicad_api.embed_symbol_from_file(
        schematic_data, 
        "MCP2210-I_SO", 
        library_path=symbol_library_path
    )
    
    # 3. If the symbol was embedded successfully, place it.
    if lib_id:
        kicad_api.place_component(
            schematic_data=schematic_data,
            lib_id=lib_id,
            reference="U1",
            value="MCP2210-I_SO",
            position=(page_center_x, page_center_y)
        )
    
    # 4. Save the generated schematic to a file.
    # The original request was to create BME280_Sheet.kicad_sch, we'll overwrite it.
    file_path = "ChipChat_Project/BME280_Sheet.kicad_sch"
    kicad_api.save_schematic(schematic_data, file_path)


if __name__ == "__main__":
    # You can override the default library path here if you want, for example:
    # main(symbol_library_path="/path/to/your/custom/library")
    main()

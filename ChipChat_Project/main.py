import uuid
import kicad_api

def main():
    """Main function to generate the schematic."""
    
    # --- BME280 Sensor Sheet ---
    
    # A4 paper size is 297 x 210 mm. Let's place the component in the middle.
    page_center_x = 297 / 2
    page_center_y = 210 / 2
    
    # Each sheet needs a unique UUID.
    bme_sheet_uuid = str(uuid.uuid4())
    
    # 1. Create the basic data structure for the BME280 sheet.
    bme_schematic = kicad_api.create_schematic_data("BME280_Sheet", bme_sheet_uuid)
    
    # 2. Place the BME280 component.
    #    This now relies on KiCad finding "Sensor:BME280" in its libraries.
    kicad_api.place_component(
        schematic_data=bme_schematic,
        lib_id="Sensor:BME280",
        reference="U1",
        value="BME280",
        position=(page_center_x, page_center_y)
    )
    
    # 3. Save the generated schematic to a file.
    file_path = "ChipChat_Project/BME280_Sheet.kicad_sch"
    kicad_api.save_schematic(bme_schematic, file_path)


if __name__ == "__main__":
    main()
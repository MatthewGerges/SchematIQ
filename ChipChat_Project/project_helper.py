import json
import os
import copy

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT_DB_PATH = os.path.join(BASE_DIR, "component_database", "components.json")


def load_component_database():
    """Loads the master component database."""
    with open(COMPONENT_DB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_project(project_name, part_names, output_path=None):
    """
    Creates a project JSON by looking up each part name in the master database
    and copying its specs into the project file.

    Args:
        project_name: Name of the project (e.g., "ChipChat_Project")
        part_names: List of part name strings that match keys in components.json
                    (e.g., ["BME280", "TPS628438DRL", "MCP2221A-I_SL", ...])
        output_path: Where to save project.json. Defaults to current directory.

    Returns:
        The project dict that was saved.
    """
    db = load_component_database()

    components = []
    not_found = []

    for part_name in part_names:
        if part_name in db:
            # Deep copy so we don't mutate the master database in memory
            part_data = copy.deepcopy(db[part_name])
            components.append(part_data)
            print(f"  Found: {part_name}")
        else:
            not_found.append(part_name)
            print(f"  NOT FOUND: {part_name}")

    if not_found:
        print(f"\nWarning: {len(not_found)} part(s) not found in database: {not_found}")

    project = {
        "project_name": project_name,
        "version": "1.0",
        "components": components
    }

    # Save to file
    if output_path is None:
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project.json")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project, f, indent=2)

    print(f"\nProject saved to {output_path}")
    print(f"  {len(components)} component(s) added")

    return project


def list_available_parts():
    """Prints all parts available in the master database."""
    db = load_component_database()
    print(f"Master database: {len(db)} component(s)")
    for name, data in db.items():
        pin_count = len(data.get("pins", []))
        print(f"  {name} ({data['type']}) - {pin_count} pins - {data['description'][:60]}")


def get_part(part_name):
    """Looks up a single part from the master database. Returns None if not found."""
    db = load_component_database()
    return copy.deepcopy(db.get(part_name))

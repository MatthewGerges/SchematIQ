import json
import os

from src.lib.kicad_library_paths import repo_root

# Optional master parts list (legacy). Prefer official KiCad ``Library:Symbol`` in JSON.
COMPONENT_DB_PATH = os.path.join(repo_root(), "component_database", "components.json")

# Map component types to reference designator prefixes
REF_PREFIX = {
    "connector": "J",
    "sensor": "U",
    "regulator": "U",
    "bridge": "U",
}


def _load_database():
    """Loads the master component database if present; otherwise empty dict."""
    if not os.path.isfile(COMPONENT_DB_PATH):
        return {}
    with open(COMPONENT_DB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _assign_references(parts, db):
    """Auto-assigns reference designators (J1, U1, U2...) based on component type."""
    counters = {}  # e.g. {"J": 1, "U": 1}
    assignments = []

    for part_name in parts:
        comp_type = db[part_name].get("type", "unknown")
        prefix = REF_PREFIX.get(comp_type, "U")

        count = counters.get(prefix, 1)
        ref = f"{prefix}{count}"
        counters[prefix] = count + 1

        assignments.append({"ref": ref, "part": part_name})

    return assignments


def build_project(project_name, parts, description="", output_path=None):
    """
    Creates a project.json that references parts from the master database.

    Args:
        project_name: Name of the project
        parts: List of part name strings (keys in components.json)
        description: Text describing the design and how things connect
        output_path: Where to save. Defaults to project.json in the same directory.

    Returns:
        The project dict that was saved.
    """
    db = _load_database()

    # Validate all parts exist
    not_found = [p for p in parts if p not in db]
    if not_found:
        print(f"ERROR: Parts not found in database: {not_found}")
        return None

    # Assign reference designators
    components = _assign_references(parts, db)

    project = {
        "project_name": project_name,
        "description": description,
        "components": components
    }

    # Save
    if output_path is None:
        # Save to data/ folder (go up from src/lib/ -> src/ -> Code/ -> data/)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        output_path = os.path.join(base_dir, "data", "project.json")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project, f, indent=2)

    print(f"Project saved to {output_path}")
    for comp in components:
        print(f"  {comp['ref']} -> {comp['part']}")

    return project


def get_part_info(part_name):
    """Query the master database for a part's full spec."""
    db = _load_database()
    return db.get(part_name)

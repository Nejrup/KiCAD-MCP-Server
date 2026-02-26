import importlib.util
from pathlib import Path


ROOT = Path(__file__).parent.parent
JLCPCB_PARTS_PATH = ROOT / "python" / "commands" / "jlcpcb_parts.py"


def _load_parts_manager_class():
    spec = importlib.util.spec_from_file_location("jlcpcb_parts", JLCPCB_PARTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.JLCPCBPartsManager


def test_search_parts_defaults_to_basic_first(tmp_path):
    manager_cls = _load_parts_manager_class()
    manager = manager_cls(str(tmp_path / "parts.db"))

    cursor = manager.conn.cursor()
    rows = [
        (
            "C_EXT",
            "Resistors",
            "Chip Resistor",
            "R-EXT",
            "0603",
            2,
            "X",
            "Extended",
            "ext",
            "",
            100,
            "[]",
            1,
        ),
        (
            "C_BAS",
            "Resistors",
            "Chip Resistor",
            "R-BASIC",
            "0603",
            2,
            "X",
            "Basic",
            "basic",
            "",
            100,
            "[]",
            1,
        ),
        (
            "C_PREF",
            "Resistors",
            "Chip Resistor",
            "R-PREF",
            "0603",
            2,
            "X",
            "Preferred",
            "pref",
            "",
            100,
            "[]",
            1,
        ),
    ]
    cursor.executemany(
        """
        INSERT OR REPLACE INTO components (
          lcsc, category, subcategory, mfr_part, package,
          solder_joints, manufacturer, library_type, description,
          datasheet, stock, price_json, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    manager.conn.commit()

    parts = manager.search_parts(category="Resistors", in_stock=True, limit=10)
    assert [p["library_type"] for p in parts[:3]] == ["Basic", "Preferred", "Extended"]

    only_extended = manager.search_parts(
        category="Resistors",
        library_type="Extended",
        in_stock=True,
        limit=10,
    )
    assert len(only_extended) == 1
    assert only_extended[0]["library_type"] == "Extended"

    manager.close()

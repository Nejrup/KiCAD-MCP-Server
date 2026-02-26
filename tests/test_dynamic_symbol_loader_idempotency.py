import re
import sys
import importlib.util
from pathlib import Path


def _load_dynamic_symbol_loader():
    module_path = (
        Path(__file__).parent.parent
        / "python"
        / "commands"
        / "dynamic_symbol_loader.py"
    )
    spec = importlib.util.spec_from_file_location("dynamic_symbol_loader", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DynamicSymbolLoader


DynamicSymbolLoader = _load_dynamic_symbol_loader()


def _write_minimal_schematic(path: Path, reference: str = "R1") -> str:
    content = (
        "(kicad_sch\n"
        "  (version 20231120)\n"
        '  (generator "test")\n'
        '  (paper "A4")\n'
        "  (lib_symbols)\n"
        '  (symbol (lib_id "Device:R") (at 10 10 0) (unit 1)\n'
        "    (in_bom yes) (on_board yes) (dnp no)\n"
        '    (uuid "11111111-1111-1111-1111-111111111111")\n'
        f'    (property "Reference" "{reference}" (at 10 7.46 0))\n'
        '    (property "Value" "10k" (at 10 12.54 0))\n'
        '    (property "Footprint" "" (at 10 10 0))\n'
        '    (property "Datasheet" "~" (at 10 10 0))\n'
        "  )\n"
        "  (sheet_instances)\n"
        ")\n"
    )
    path.write_text(content, encoding="utf-8")
    return content


def test_create_component_instance_skips_existing_reference(tmp_path):
    sch_path = tmp_path / "existing_ref.kicad_sch"
    original = _write_minimal_schematic(sch_path, reference="R1")

    loader = DynamicSymbolLoader()
    ok = loader.create_component_instance(
        sch_path,
        library_name="Device",
        symbol_name="R",
        reference="R1",
        value="10k",
        x=50,
        y=50,
    )

    assert ok is True
    assert sch_path.read_text(encoding="utf-8") == original


def test_create_component_instance_is_idempotent_for_new_reference(tmp_path):
    sch_path = tmp_path / "idempotent_ref.kicad_sch"
    _write_minimal_schematic(sch_path, reference="R1")

    loader = DynamicSymbolLoader()
    ok_first = loader.create_component_instance(
        sch_path,
        library_name="Device",
        symbol_name="C",
        reference="C1",
        value="100n",
        x=20,
        y=20,
    )
    ok_second = loader.create_component_instance(
        sch_path,
        library_name="Device",
        symbol_name="C",
        reference="C1",
        value="100n",
        x=20,
        y=20,
    )

    text = sch_path.read_text(encoding="utf-8")
    ref_count = len(re.findall(r'\(property "Reference" "C1"', text))

    assert ok_first is True
    assert ok_second is True
    assert ref_count == 1

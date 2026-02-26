import sys
import types
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONNECTION_PATH = ROOT / "python" / "commands" / "connection_schematic.py"


def _ensure_import_stubs():
    if "commands" not in sys.modules:
        sys.modules["commands"] = types.ModuleType("commands")

    if "skip" not in sys.modules:
        skip_module = types.ModuleType("skip")
        setattr(skip_module, "Schematic", object)
        sys.modules["skip"] = skip_module

    if "commands.wire_manager" not in sys.modules:
        wm = types.ModuleType("commands.wire_manager")

        class WireManager:
            @staticmethod
            def add_wire(*_args, **_kwargs):
                return True

            @staticmethod
            def add_polyline_wire(*_args, **_kwargs):
                return True

            @staticmethod
            def add_label(*_args, **_kwargs):
                return True

            @staticmethod
            def create_orthogonal_path(start, end, prefer_horizontal_first=True):
                return [start, end]

        setattr(wm, "WireManager", WireManager)
        sys.modules["commands.wire_manager"] = wm

    if "commands.pin_locator" not in sys.modules:
        pl = types.ModuleType("commands.pin_locator")

        class PinLocator:
            def get_pin_location(self, *_args, **_kwargs):
                return [0.0, 0.0]

            def get_pin_info(self, *_args, **_kwargs):
                return {"x": 0.0, "y": 0.0, "effective_angle": 0.0}

            def get_symbol_pins(self, *_args, **_kwargs):
                return {}

        setattr(pl, "PinLocator", PinLocator)
        sys.modules["commands.pin_locator"] = pl


def _load_connection_manager():
    _ensure_import_stubs()
    spec = importlib.util.spec_from_file_location(
        "commands.connection_schematic", CONNECTION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ConnectionManager


class _Obj:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_generate_netlist_filters_templates_by_default():
    manager = _load_connection_manager()
    regular = _Obj(
        property=_Obj(
            Reference=_Obj(value="R1"),
            Value=_Obj(value="10k"),
            Footprint=_Obj(value="Resistor_SMD:R_0603_1608Metric"),
        )
    )
    template = _Obj(
        property=_Obj(
            Reference=_Obj(value="_TEMPLATE_Device_R"),
            Value=_Obj(value="R"),
            Footprint=_Obj(value=""),
        )
    )
    fake = _Obj(symbol=[regular, template])

    netlist_default = manager.generate_netlist(fake)
    assert [c["reference"] for c in netlist_default["components"]] == ["R1"]

    netlist_with_templates = manager.generate_netlist(fake, include_templates=True)
    assert sorted(c["reference"] for c in netlist_with_templates["components"]) == [
        "R1",
        "_TEMPLATE_Device_R",
    ]

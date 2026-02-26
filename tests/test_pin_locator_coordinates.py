import sys
import types
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
PIN_LOCATOR_PATH = ROOT / "python" / "commands" / "pin_locator.py"


def _load_pin_locator_module():
    if "skip" not in sys.modules:
        skip_module = types.ModuleType("skip")
        setattr(skip_module, "Schematic", object)
        sys.modules["skip"] = skip_module

    spec = importlib.util.spec_from_file_location(
        "commands.pin_locator", PIN_LOCATOR_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pin_locator_inverts_symbol_y_for_schematic_space(monkeypatch, tmp_path):
    module = _load_pin_locator_module()
    PinLocator = module.PinLocator

    class _Obj:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class _FakeSchematic:
        def __init__(self, _path):
            self.symbol = [
                _Obj(
                    property=_Obj(Reference=_Obj(value="R1")),
                    at=_Obj(value=[100.0, 100.0, 0.0]),
                    lib_id=_Obj(value="Device:R"),
                )
            ]

    monkeypatch.setattr(module, "Schematic", _FakeSchematic)

    locator = PinLocator()
    monkeypatch.setattr(
        locator,
        "get_symbol_pins",
        lambda *_args, **_kwargs: {
            "1": {"x": 0.0, "y": 3.81, "angle": 270.0, "name": "~"}
        },
    )

    sch_path = tmp_path / "coord.kicad_sch"
    sch_path.write_text("(kicad_sch)", encoding="utf-8")

    pin = locator.get_pin_info(sch_path, "R1", "1")
    assert pin is not None
    assert round(pin["x"], 2) == 100.0
    assert round(pin["y"], 2) == 96.19

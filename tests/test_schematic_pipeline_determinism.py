import sys
import types
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCHEMATIC_QUALITY_PATH = ROOT / "python" / "commands" / "schematic_quality.py"

if "commands" not in sys.modules:
    commands_pkg = types.ModuleType("commands")
    sys.modules["commands"] = commands_pkg


class _FakeConnectionManager:
    @staticmethod
    def generate_netlist(*_args, **_kwargs):
        return {"nets": []}

    @staticmethod
    def connect_to_net(*_args, **_kwargs):
        return True


if "commands.connection_schematic" not in sys.modules:
    connection_module = types.ModuleType("commands.connection_schematic")
    setattr(connection_module, "ConnectionManager", _FakeConnectionManager)
    sys.modules["commands.connection_schematic"] = connection_module

if "skip" not in sys.modules:
    skip_module = types.ModuleType("skip")
    setattr(skip_module, "Schematic", object)
    sys.modules["skip"] = skip_module


def _load_schematic_quality():
    spec = importlib.util.spec_from_file_location(
        "commands.schematic_quality", SCHEMATIC_QUALITY_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sq = _load_schematic_quality()
ConnectionManager = sq.ConnectionManager


class _Obj:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeSchematic:
    def __init__(self, _path):
        symbol = _Obj(
            property=_Obj(Reference=_Obj(value="R1")),
            at=_Obj(value=[10.0, 10.0, 0]),
        )
        self.symbol = [symbol]
        self.wire = []

    def write(self, _path):
        return None


def test_auto_layout_refuses_unsafe_when_connectivity_exists(tmp_path, monkeypatch):
    sch_path = tmp_path / "guard.kicad_sch"
    sch_path.write_text("(kicad_sch)", encoding="utf-8")

    monkeypatch.setattr(sq, "Schematic", _FakeSchematic)
    monkeypatch.setattr(
        ConnectionManager,
        "generate_netlist",
        lambda *_args, **_kwargs: {
            "nets": [{"name": "VCC", "connections": [{"component": "R1", "pin": "1"}]}]
        },
    )

    result = sq.SchematicQualityManager.auto_layout(
        sch_path,
        preserve_connectivity=False,
        allow_unsafe=False,
    )

    assert result["success"] is False
    assert result["guard"] == "connectivity_present"


def test_auto_layout_preserves_membership_and_reports_rebuild(tmp_path, monkeypatch):
    sch_path = tmp_path / "preserve.kicad_sch"
    sch_path.write_text("(kicad_sch)", encoding="utf-8")

    monkeypatch.setattr(sq, "Schematic", _FakeSchematic)

    netlist_calls = {"count": 0}

    def _fake_generate_netlist(*_args, **_kwargs):
        netlist_calls["count"] += 1
        return {
            "nets": [
                {
                    "name": "VCC",
                    "connections": [{"component": "R1", "pin": "1"}],
                }
            ]
        }

    monkeypatch.setattr(ConnectionManager, "generate_netlist", _fake_generate_netlist)
    monkeypatch.setattr(
        ConnectionManager, "connect_to_net", lambda *_args, **_kwargs: True
    )

    result = sq.SchematicQualityManager.auto_layout(
        sch_path,
        preserve_connectivity=True,
        allow_unsafe=False,
    )

    assert result["success"] is True
    assert result["connectivityPreserved"] is True
    assert result["rebuiltConnections"] == 1
    assert netlist_calls["count"] >= 2


def test_auto_layout_rebuilds_after_clearing_wires(tmp_path, monkeypatch):
    sch_path = tmp_path / "wires_guard.kicad_sch"
    sch_path.write_text("(kicad_sch)", encoding="utf-8")

    class _WireSchematic(_FakeSchematic):
        def __init__(self, _path):
            super().__init__(_path)
            self.wire = [object()]

    monkeypatch.setattr(sq, "Schematic", _WireSchematic)
    monkeypatch.setattr(
        ConnectionManager,
        "generate_netlist",
        lambda *_args, **_kwargs: {
            "nets": [{"name": "VCC", "connections": [{"component": "R1", "pin": "1"}]}]
        },
    )
    monkeypatch.setattr(
        ConnectionManager, "connect_to_net", lambda *_args, **_kwargs: True
    )

    clear_calls = {"count": 0}

    def _fake_clear(_path):
        clear_calls["count"] += 1
        return {"wire": 1}

    monkeypatch.setattr(
        sq.SchematicQualityManager, "_clear_connectivity_primitives", _fake_clear
    )

    result = sq.SchematicQualityManager.auto_layout(
        sch_path,
        preserve_connectivity=True,
        allow_unsafe=False,
    )

    assert result["success"] is True
    assert result["rebuiltConnections"] == 1
    assert clear_calls["count"] == 1

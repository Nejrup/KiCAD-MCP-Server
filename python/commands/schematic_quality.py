import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import sexpdata
from sexpdata import Symbol
from skip import Schematic

from commands.connection_schematic import ConnectionManager

logger = logging.getLogger("kicad_interface")


class SchematicQualityManager:
    @staticmethod
    def _is_template_ref(reference: str) -> bool:
        return reference.startswith("_TEMPLATE_")

    @staticmethod
    def _component_bucket(reference: str) -> str:
        ref = reference.upper()
        if ref.startswith("#PWR"):
            return "power"
        if ref.startswith("J"):
            return "connector"
        if ref.startswith("U"):
            return "ic"
        if ref.startswith(("R", "C", "L", "D", "Q", "Y", "SW", "FB")):
            return "passive"
        return "other"

    @staticmethod
    def _grid_snap(value: float, grid: float) -> float:
        if grid <= 0:
            return value
        return round(value / grid) * grid

    @staticmethod
    def _extract_membership(netlist: Dict[str, Any]) -> Dict[str, Set[Tuple[str, str]]]:
        memberships: Dict[str, Set[Tuple[str, str]]] = {}
        for net in netlist.get("nets", []):
            net_name = str(net.get("name", ""))
            if not net_name:
                continue
            members: Set[Tuple[str, str]] = set()
            for conn in net.get("connections", []):
                comp = str(conn.get("component", ""))
                pin = str(conn.get("pin", ""))
                if comp and pin and pin != "unknown":
                    members.add((comp, pin))
            memberships[net_name] = members
        return memberships

    @staticmethod
    def _membership_equal(
        before: Dict[str, Set[Tuple[str, str]]],
        after: Dict[str, Set[Tuple[str, str]]],
    ) -> Tuple[bool, List[str]]:
        mismatches: List[str] = []
        for net_name, before_members in before.items():
            after_members = after.get(net_name, set())
            if before_members != after_members:
                mismatches.append(net_name)
        return len(mismatches) == 0, mismatches

    @staticmethod
    def _rebuild_connectivity_from_netlist(
        schematic_path: Path, membership: Dict[str, Set[Tuple[str, str]]]
    ) -> Tuple[bool, List[str]]:
        failures: List[str] = []
        for net_name in sorted(membership.keys()):
            for component, pin in sorted(membership[net_name]):
                ok = ConnectionManager.connect_to_net(
                    schematic_path,
                    component,
                    pin,
                    net_name,
                )
                if not ok:
                    failures.append(
                        f"{component}/{pin} -> {net_name}: {ConnectionManager.get_last_error()}"
                    )
        return len(failures) == 0, failures

    @staticmethod
    def _clear_connectivity_primitives(schematic_path: Path) -> Dict[str, int]:
        content = schematic_path.read_text(encoding="utf-8")
        data = sexpdata.loads(content)

        removable = {
            "wire",
            "junction",
            "no_connect",
            "label",
            "global_label",
            "hierarchical_label",
        }
        counts: Dict[str, int] = {k: 0 for k in removable}
        kept = []

        for item in data:
            if isinstance(item, list) and item:
                head = item[0]
                if isinstance(head, Symbol):
                    head_name = str(head)
                    if head_name in removable:
                        counts[head_name] = counts.get(head_name, 0) + 1
                        continue
            kept.append(item)

        schematic_path.write_text(sexpdata.dumps(kept), encoding="utf-8")
        return counts

    @staticmethod
    def auto_layout(
        schematic_path: Path,
        grid: float = 2.54,
        x_origin: float = 20.0,
        y_origin: float = 20.0,
        row_spacing: float = 15.24,
        column_spacing: float = 45.72,
        preserve_connectivity: bool = True,
        allow_unsafe: bool = False,
    ) -> Dict[str, Any]:
        original_text = schematic_path.read_text(encoding="utf-8")
        sch = Schematic(str(schematic_path))
        has_wires = hasattr(sch, "wire") and len(list(getattr(sch, "wire"))) > 0

        baseline_netlist = ConnectionManager.generate_netlist(
            sch,
            schematic_path=schematic_path,
            include_templates=False,
        )
        baseline_membership = SchematicQualityManager._extract_membership(
            baseline_netlist
        )
        had_connectivity = any(len(v) > 0 for v in baseline_membership.values())

        if had_connectivity and (not preserve_connectivity) and (not allow_unsafe):
            return {
                "success": False,
                "message": "Layout refused: schematic has existing connectivity. Use preserveConnectivity=true or allowUnsafeLayout=true.",
                "guard": "connectivity_present",
            }

        symbols: List[Any] = []
        for symbol in sch.symbol:
            try:
                ref = symbol.property.Reference.value
            except Exception:
                continue
            if SchematicQualityManager._is_template_ref(ref):
                continue
            symbols.append(symbol)

        buckets: Dict[str, List[Any]] = {
            "power": [],
            "connector": [],
            "ic": [],
            "passive": [],
            "other": [],
        }
        for symbol in symbols:
            ref = symbol.property.Reference.value
            buckets[SchematicQualityManager._component_bucket(ref)].append(symbol)

        for key in buckets:
            buckets[key].sort(key=lambda s: s.property.Reference.value)

        ordered_buckets = ["power", "connector", "ic", "passive", "other"]
        moved: List[Dict[str, Any]] = []

        for col_idx, bucket in enumerate(ordered_buckets):
            x = SchematicQualityManager._grid_snap(
                x_origin + col_idx * column_spacing,
                grid,
            )
            for row_idx, symbol in enumerate(buckets[bucket]):
                y = SchematicQualityManager._grid_snap(
                    y_origin + row_idx * row_spacing,
                    grid,
                )
                ref = symbol.property.Reference.value
                old_at = list(symbol.at.value)
                rot = old_at[2] if len(old_at) > 2 else 0

                if bucket == "connector":
                    rot = 0
                elif bucket == "power":
                    rot = 90
                elif bucket == "passive":
                    rot = 0
                elif bucket == "ic":
                    rot = 0

                symbol.at.value = [x, y, rot]
                moved.append(
                    {
                        "reference": ref,
                        "from": old_at,
                        "to": [x, y, rot],
                        "bucket": bucket,
                    }
                )

        sch.write(str(schematic_path))

        rebuilt_count = 0
        cleared: Dict[str, int] = {}
        if preserve_connectivity and had_connectivity:
            if has_wires:
                cleared = SchematicQualityManager._clear_connectivity_primitives(
                    schematic_path
                )
            rebuilt_ok, failures = (
                SchematicQualityManager._rebuild_connectivity_from_netlist(
                    schematic_path,
                    baseline_membership,
                )
            )
            if not rebuilt_ok:
                schematic_path.write_text(original_text, encoding="utf-8")
                return {
                    "success": False,
                    "message": "Failed to rebuild connectivity after layout. Reverted schematic.",
                    "errors": failures,
                }

            rebuilt_count = sum(len(v) for v in baseline_membership.values())
            after_sch = Schematic(str(schematic_path))
            after_netlist = ConnectionManager.generate_netlist(
                after_sch,
                schematic_path=schematic_path,
                include_templates=False,
            )
            after_membership = SchematicQualityManager._extract_membership(
                after_netlist
            )
            membership_ok, mismatched_nets = SchematicQualityManager._membership_equal(
                baseline_membership,
                after_membership,
            )
            if not membership_ok:
                schematic_path.write_text(original_text, encoding="utf-8")
                return {
                    "success": False,
                    "message": "Connectivity changed after layout. Reverted schematic.",
                    "mismatchedNets": mismatched_nets,
                }

        return {
            "success": True,
            "movedCount": len(moved),
            "moved": moved,
            "grid": grid,
            "strategy": "deterministic_bucket_layout",
            "connectivityPreserved": preserve_connectivity and had_connectivity,
            "rebuiltConnections": rebuilt_count,
            "clearedPrimitives": cleared,
        }

    @staticmethod
    def validate(
        schematic_path: Path, overlap_distance_mm: float = 5.08
    ) -> Dict[str, Any]:
        sch = Schematic(str(schematic_path))

        issues: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []

        components: List[Dict[str, Any]] = []
        ref_counts: Dict[str, int] = {}

        for symbol in sch.symbol:
            try:
                ref = str(symbol.property.Reference.value)
            except Exception:
                continue
            if SchematicQualityManager._is_template_ref(ref):
                continue

            at = list(symbol.at.value)
            x = float(at[0]) if len(at) > 0 else 0.0
            y = float(at[1]) if len(at) > 1 else 0.0
            value = (
                str(symbol.property.Value.value)
                if hasattr(symbol.property, "Value")
                else ""
            )
            footprint = (
                str(symbol.property.Footprint.value)
                if hasattr(symbol.property, "Footprint")
                else ""
            )

            components.append(
                {
                    "reference": ref,
                    "x": x,
                    "y": y,
                    "value": value,
                    "footprint": footprint,
                }
            )
            ref_counts[ref] = ref_counts.get(ref, 0) + 1

        for ref, count in ref_counts.items():
            if count > 1:
                issues.append(
                    {
                        "type": "duplicate_reference",
                        "message": f"Reference {ref} appears {count} times",
                    }
                )

        for i in range(len(components)):
            for j in range(i + 1, len(components)):
                a = components[i]
                b = components[j]
                dist = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                if dist < overlap_distance_mm:
                    warnings.append(
                        {
                            "type": "possible_overlap",
                            "message": f"{a['reference']} and {b['reference']} are {dist:.2f}mm apart",
                        }
                    )

        netlist = ConnectionManager.generate_netlist(
            sch,
            schematic_path=schematic_path,
            include_templates=False,
        )
        nets = netlist.get("nets", [])

        for net in nets:
            conns = net.get("connections", [])
            if len(conns) < 2:
                warnings.append(
                    {
                        "type": "weak_net_connectivity",
                        "message": f"Net {net.get('name', '<unnamed>')} has only {len(conns)} connection(s)",
                    }
                )

        connected_component_refs = set()
        for net in nets:
            for conn in net.get("connections", []):
                ref = conn.get("component")
                if ref:
                    connected_component_refs.add(ref)

        for c in components:
            ref = c["reference"]
            if ref not in connected_component_refs:
                warnings.append(
                    {
                        "type": "unconnected_component",
                        "message": f"{ref} does not appear in any discovered net connection",
                    }
                )
            if not c["footprint"]:
                warnings.append(
                    {
                        "type": "missing_footprint",
                        "message": f"{ref} has no footprint assigned",
                    }
                )

        power_regex = re.compile(r"^(GND|VSS|VDD|VCC|3V3|5V|12V)$", re.IGNORECASE)
        for c in components:
            ref = c["reference"]
            if not ref.upper().startswith("U"):
                continue
            has_power_net = False
            for net in nets:
                net_name = str(net.get("name", ""))
                if not power_regex.match(net_name):
                    continue
                for conn in net.get("connections", []):
                    if conn.get("component") == ref:
                        has_power_net = True
                        break
                if has_power_net:
                    break
            if not has_power_net:
                warnings.append(
                    {
                        "type": "ic_power_uncertain",
                        "message": f"{ref} has no obvious connection to power/ground nets",
                    }
                )

        return {
            "success": True,
            "valid": len(issues) == 0,
            "errors": issues,
            "warnings": warnings,
            "summary": {
                "componentCount": len(components),
                "netCount": len(nets),
                "errorCount": len(issues),
                "warningCount": len(warnings),
            },
        }

"""
Design rules command implementations for KiCAD interface
"""

import os
import pcbnew
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("kicad_interface")


class DesignRuleCommands:
    """Handles design rule checking and configuration"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def _get_drc_history_file(self, board_file: str) -> str:
        """Get path to persistent DRC history JSON file for a board."""
        board_dir = os.path.dirname(board_file)
        board_name = os.path.splitext(os.path.basename(board_file))[0]
        return os.path.join(board_dir, f"{board_name}_drc_history.json")

    def _read_drc_history(self, history_file: str) -> List[Dict[str, Any]]:
        """Read DRC history from disk, returning an empty list on failure."""
        try:
            if not os.path.exists(history_file):
                return []

            import json

            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get("history"), list):
                return data["history"]

            return []
        except Exception as e:
            logger.warning(f"Failed to read DRC history from {history_file}: {e}")
            return []

    def _write_drc_history(
        self, history_file: str, history: List[Dict[str, Any]]
    ) -> None:
        """Persist DRC history to disk."""
        import json

        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    def _calculate_drc_trend(
        self,
        previous: Optional[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate DRC trend between two snapshots."""
        if not previous:
            return {
                "status": "baseline",
                "delta": {
                    "total": 0,
                    "errors": 0,
                    "warnings": 0,
                    "info": 0,
                },
            }

        prev_severity = previous.get("severity_counts", {})
        curr_severity = current.get("severity_counts", {})

        total_delta = int(current.get("total_violations", 0)) - int(
            previous.get("total_violations", 0)
        )
        error_delta = int(curr_severity.get("error", 0)) - int(
            prev_severity.get("error", 0)
        )
        warning_delta = int(curr_severity.get("warning", 0)) - int(
            prev_severity.get("warning", 0)
        )
        info_delta = int(curr_severity.get("info", 0)) - int(
            prev_severity.get("info", 0)
        )

        if total_delta < 0:
            status = "improving"
        elif total_delta > 0:
            status = "degrading"
        else:
            status = "stable"

        return {
            "status": status,
            "delta": {
                "total": total_delta,
                "errors": error_delta,
                "warnings": warning_delta,
                "info": info_delta,
            },
        }

    def _build_violation_signature(self, violation: Dict[str, Any]) -> str:
        location = violation.get("location", {})
        x = float(location.get("x", 0) or 0)
        y = float(location.get("y", 0) or 0)
        xq = round(x, 3)
        yq = round(y, 3)
        vtype = str(violation.get("type", "unknown"))
        message = str(violation.get("message", ""))
        return f"{vtype}|{xq}|{yq}|{message}"

    def _calculate_violation_diff(
        self,
        previous: Optional[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Dict[str, Any]:
        prev_signatures = previous.get("signature_counts", {}) if previous else {}
        curr_signatures = current.get("signature_counts", {})

        new_count = 0
        resolved_count = 0
        persisting_count = 0

        for signature, curr_qty in curr_signatures.items():
            prev_qty = int(prev_signatures.get(signature, 0))
            curr_qty_int = int(curr_qty)
            if curr_qty_int > prev_qty:
                new_count += curr_qty_int - prev_qty
            if prev_qty > 0:
                persisting_count += min(prev_qty, curr_qty_int)

        for signature, prev_qty in prev_signatures.items():
            curr_qty = int(curr_signatures.get(signature, 0))
            prev_qty_int = int(prev_qty)
            if prev_qty_int > curr_qty:
                resolved_count += prev_qty_int - curr_qty

        return {
            "new": new_count,
            "resolved": resolved_count,
            "persisting": persisting_count,
        }

    def set_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set design rules for the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            design_settings = self.board.GetDesignSettings()

            # Convert mm to nanometers for KiCAD internal units
            scale = 1000000  # mm to nm

            # Set clearance
            if "clearance" in params:
                design_settings.m_MinClearance = int(params["clearance"] * scale)

            # KiCAD 9.0: Use SetCustom* methods instead of SetCurrent* (which were removed)
            # Track if we set any custom track/via values
            custom_values_set = False

            if "trackWidth" in params:
                design_settings.SetCustomTrackWidth(int(params["trackWidth"] * scale))
                custom_values_set = True

            # Via settings
            if "viaDiameter" in params:
                design_settings.SetCustomViaSize(int(params["viaDiameter"] * scale))
                custom_values_set = True
            if "viaDrill" in params:
                design_settings.SetCustomViaDrill(int(params["viaDrill"] * scale))
                custom_values_set = True

            # KiCAD 9.0: Activate custom track/via values so they become the current values
            if custom_values_set:
                design_settings.UseCustomTrackViaSize(True)

            # Set micro via settings (use properties - methods removed in KiCAD 9.0)
            if "microViaDiameter" in params:
                design_settings.m_MicroViasMinSize = int(
                    params["microViaDiameter"] * scale
                )
            if "microViaDrill" in params:
                design_settings.m_MicroViasMinDrill = int(
                    params["microViaDrill"] * scale
                )

            # Set minimum values
            if "minTrackWidth" in params:
                design_settings.m_TrackMinWidth = int(params["minTrackWidth"] * scale)
            if "minViaDiameter" in params:
                design_settings.m_ViasMinSize = int(params["minViaDiameter"] * scale)

            # KiCAD 9.0: m_ViasMinDrill removed - use m_MinThroughDrill instead
            if "minViaDrill" in params:
                design_settings.m_MinThroughDrill = int(params["minViaDrill"] * scale)

            if "minMicroViaDiameter" in params:
                design_settings.m_MicroViasMinSize = int(
                    params["minMicroViaDiameter"] * scale
                )
            if "minMicroViaDrill" in params:
                design_settings.m_MicroViasMinDrill = int(
                    params["minMicroViaDrill"] * scale
                )

            # KiCAD 9.0: m_MinHoleDiameter removed - use m_MinThroughDrill
            if "minHoleDiameter" in params:
                design_settings.m_MinThroughDrill = int(
                    params["minHoleDiameter"] * scale
                )

            # KiCAD 9.0: Added hole clearance settings
            if "holeClearance" in params:
                design_settings.m_HoleClearance = int(params["holeClearance"] * scale)
            if "holeToHoleMin" in params:
                design_settings.m_HoleToHoleMin = int(params["holeToHoleMin"] * scale)

            # Build response with KiCAD 9.0 compatible properties
            # After UseCustomTrackViaSize(True), GetCurrent* returns the custom values
            response_rules = {
                "clearance": design_settings.m_MinClearance / scale,
                "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                "viaDrill": design_settings.GetCurrentViaDrill() / scale,
                "microViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "microViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "minTrackWidth": design_settings.m_TrackMinWidth / scale,
                "minViaDiameter": design_settings.m_ViasMinSize / scale,
                "minThroughDrill": design_settings.m_MinThroughDrill / scale,
                "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "holeClearance": design_settings.m_HoleClearance / scale,
                "holeToHoleMin": design_settings.m_HoleToHoleMin / scale,
                "viasMinAnnularWidth": design_settings.m_ViasMinAnnularWidth / scale,
            }

            return {
                "success": True,
                "message": "Updated design rules",
                "rules": response_rules,
            }

        except Exception as e:
            logger.error(f"Error setting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set design rules",
                "errorDetails": str(e),
            }

    def get_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current design rules - KiCAD 9.0 compatible"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            design_settings = self.board.GetDesignSettings()
            scale = 1000000  # nm to mm

            # Build rules dict with KiCAD 9.0 compatible properties
            rules = {
                # Core clearance and track settings
                "clearance": design_settings.m_MinClearance / scale,
                "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                "minTrackWidth": design_settings.m_TrackMinWidth / scale,
                # Via settings (current values from methods)
                "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                "viaDrill": design_settings.GetCurrentViaDrill() / scale,
                # Via minimum values
                "minViaDiameter": design_settings.m_ViasMinSize / scale,
                "viasMinAnnularWidth": design_settings.m_ViasMinAnnularWidth / scale,
                # Micro via settings
                "microViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "microViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,
                # KiCAD 9.0: Hole and drill settings (replaces removed m_ViasMinDrill and m_MinHoleDiameter)
                "minThroughDrill": design_settings.m_MinThroughDrill / scale,
                "holeClearance": design_settings.m_HoleClearance / scale,
                "holeToHoleMin": design_settings.m_HoleToHoleMin / scale,
                # Other constraints
                "copperEdgeClearance": design_settings.m_CopperEdgeClearance / scale,
                "silkClearance": design_settings.m_SilkClearance / scale,
            }

            return {"success": True, "rules": rules}

        except Exception as e:
            logger.error(f"Error getting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get design rules",
                "errorDetails": str(e),
            }

    def run_drc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Design Rule Check using kicad-cli"""
        import subprocess
        import json
        import tempfile
        import platform
        import shutil

        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            report_path = params.get("reportPath")

            # Get the board file path
            board_file = self.board.GetFileName()
            if not board_file or not os.path.exists(board_file):
                return {
                    "success": False,
                    "message": "Board file not found",
                    "errorDetails": "Cannot run DRC without a saved board file",
                }

            # Find kicad-cli executable
            kicad_cli = self._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "KiCAD CLI tool not found in system. Install KiCAD 8.0+ or set PATH.",
                }

            # Create temporary JSON output file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                json_output = tmp.name

            try:
                # Build command
                cmd = [
                    kicad_cli,
                    "pcb",
                    "drc",
                    "--format",
                    "json",
                    "--output",
                    json_output,
                    "--units",
                    "mm",
                    board_file,
                ]

                logger.info(f"Running DRC command: {' '.join(cmd)}")

                # Run DRC
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 minute timeout for large boards (21MB PCB needs time)
                )

                if result.returncode != 0:
                    logger.error(f"DRC command failed: {result.stderr}")
                    return {
                        "success": False,
                        "message": "DRC command failed",
                        "errorDetails": result.stderr,
                    }

                # Read JSON output
                with open(json_output, "r", encoding="utf-8") as f:
                    drc_data = json.load(f)

                # Parse violations from kicad-cli output
                violations = []
                violation_counts = {}
                severity_counts = {"error": 0, "warning": 0, "info": 0}
                signature_counts: Dict[str, int] = {}

                for violation in drc_data.get("violations", []):
                    vtype = violation.get("type", "unknown")
                    vseverity = violation.get("severity", "error")

                    violations.append(
                        {
                            "type": vtype,
                            "severity": vseverity,
                            "message": violation.get("description", ""),
                            "location": {
                                "x": violation.get("x", 0),
                                "y": violation.get("y", 0),
                                "unit": "mm",
                            },
                        }
                    )

                    # Count violations by type
                    violation_counts[vtype] = violation_counts.get(vtype, 0) + 1

                    # Count by severity
                    if vseverity in severity_counts:
                        severity_counts[vseverity] += 1

                    signature = self._build_violation_signature(violations[-1])
                    signature_counts[signature] = signature_counts.get(signature, 0) + 1

                # Determine where to save the violations file
                board_dir = os.path.dirname(board_file)
                board_name = os.path.splitext(os.path.basename(board_file))[0]
                violations_file = os.path.join(
                    board_dir, f"{board_name}_drc_violations.json"
                )

                # Always save violations to JSON file (for large result sets)
                with open(violations_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "board": board_file,
                            "timestamp": drc_data.get("date", "unknown"),
                            "total_violations": len(violations),
                            "violation_counts": violation_counts,
                            "severity_counts": severity_counts,
                            "violations": violations,
                        },
                        f,
                        indent=2,
                    )

                # Save text report if requested
                if report_path:
                    report_path = os.path.abspath(os.path.expanduser(report_path))
                    cmd_report = [
                        kicad_cli,
                        "pcb",
                        "drc",
                        "--format",
                        "report",
                        "--output",
                        report_path,
                        "--units",
                        "mm",
                        board_file,
                    ]
                    subprocess.run(cmd_report, capture_output=True, timeout=600)

                # Track DRC history and trend
                history_file = self._get_drc_history_file(board_file)
                history = self._read_drc_history(history_file)

                current_snapshot = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "board": board_file,
                    "total_violations": len(violations),
                    "severity_counts": severity_counts,
                    "violation_counts": violation_counts,
                    "signature_counts": signature_counts,
                    "violations_file": violations_file,
                }

                previous_snapshot = history[-1] if history else None
                trend = self._calculate_drc_trend(previous_snapshot, current_snapshot)
                diff = self._calculate_violation_diff(
                    previous_snapshot, current_snapshot
                )

                history.append(current_snapshot)
                self._write_drc_history(history_file, history)

                # Return summary only (not full violations list)
                return {
                    "success": True,
                    "message": f"Found {len(violations)} DRC violations",
                    "summary": {
                        "total": len(violations),
                        "by_severity": severity_counts,
                        "by_type": violation_counts,
                    },
                    "violationsFile": violations_file,
                    "reportPath": report_path if report_path else None,
                    "history": {
                        "historyFile": history_file,
                        "runCount": len(history),
                        "trend": trend,
                        "diff": diff,
                    },
                }

            finally:
                # Clean up temp JSON file
                if os.path.exists(json_output):
                    os.unlink(json_output)

        except subprocess.TimeoutExpired:
            logger.error("DRC command timed out")
            return {
                "success": False,
                "message": "DRC command timed out",
                "errorDetails": "Command took longer than 600 seconds (10 minutes)",
            }
        except Exception as e:
            logger.error(f"Error running DRC: {str(e)}")
            return {
                "success": False,
                "message": "Failed to run DRC",
                "errorDetails": str(e),
            }

    def _find_kicad_cli(self) -> Optional[str]:
        """Find kicad-cli executable"""
        import platform
        import shutil

        # Try system PATH first
        cli_name = "kicad-cli.exe" if platform.system() == "Windows" else "kicad-cli"
        cli_path = shutil.which(cli_name)
        if cli_path:
            return cli_path

        # Try common installation paths (version-specific)
        if platform.system() == "Windows":
            common_paths = [
                r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\10.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\bin\kicad-cli.exe",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path
        elif platform.system() == "Darwin":  # macOS
            common_paths = [
                "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path
        else:  # Linux
            common_paths = [
                "/usr/bin/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path

        return None

    def get_drc_violations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get list of DRC violations"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            severity = params.get("severity", "all")

            # Get DRC markers
            violations = []
            for marker in self.board.GetDRCMarkers():
                violation = {
                    "type": marker.GetErrorCode(),
                    "severity": "error",  # KiCAD DRC markers are always errors
                    "message": marker.GetDescription(),
                    "location": {
                        "x": marker.GetPos().x / 1000000,
                        "y": marker.GetPos().y / 1000000,
                        "unit": "mm",
                    },
                }

                # Filter by severity if specified
                if severity == "all" or severity == violation["severity"]:
                    violations.append(violation)

            return {"success": True, "violations": violations}

        except Exception as e:
            logger.error(f"Error getting DRC violations: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get DRC violations",
                "errorDetails": str(e),
            }

    def get_drc_history(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get persisted DRC run history and trend information."""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            board_file = self.board.GetFileName()
            if not board_file or not os.path.exists(board_file):
                return {
                    "success": False,
                    "message": "Board file not found",
                    "errorDetails": "Cannot read DRC history without a saved board file",
                }

            limit = params.get("limit", 20)
            if not isinstance(limit, int) or limit <= 0:
                limit = 20

            history_file = self._get_drc_history_file(board_file)
            history = self._read_drc_history(history_file)

            if not history:
                return {
                    "success": True,
                    "historyFile": history_file,
                    "runCount": 0,
                    "history": [],
                    "trend": {
                        "status": "no_data",
                        "delta": {
                            "total": 0,
                            "errors": 0,
                            "warnings": 0,
                            "info": 0,
                        },
                    },
                }

            window = history[-limit:]
            previous_snapshot = window[-2] if len(window) >= 2 else None
            latest_snapshot = window[-1]
            trend = self._calculate_drc_trend(previous_snapshot, latest_snapshot)
            diff = self._calculate_violation_diff(previous_snapshot, latest_snapshot)

            return {
                "success": True,
                "historyFile": history_file,
                "runCount": len(history),
                "history": window,
                "trend": trend,
                "diff": diff,
            }

        except Exception as e:
            logger.error(f"Error getting DRC history: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get DRC history",
                "errorDetails": str(e),
            }

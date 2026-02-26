import glob
import os
import platform
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple


def _expand_candidate(path_pattern: str) -> List[str]:
    if "*" not in path_pattern:
        return [path_pattern]
    matches = glob.glob(path_pattern)
    matches.sort(reverse=True)
    return matches


def _is_executable_file(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _validate_kicad_cli(path: str, timeout_seconds: int = 5) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode == 0:
            return True, ""
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        return False, stderr or stdout or f"exit code {result.returncode}"
    except Exception as exc:
        return False, str(exc)


def _platform_fallbacks() -> List[str]:
    system = platform.system()
    if system == "Windows":
        return [
            r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
            r"C:\Program Files (x86)\KiCad\9.0\bin\kicad-cli.exe",
            r"C:\Program Files (x86)\KiCad\8.0\bin\kicad-cli.exe",
        ]
    if system == "Darwin":
        return [
            "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            "/Applications/KiCad/KiCad 9.app/Contents/MacOS/kicad-cli",
            "/Applications/KiCad/KiCad 8.app/Contents/MacOS/kicad-cli",
            "/Applications/KiCAD/KiCad.app/Contents/MacOS/kicad-cli",
            "/opt/homebrew/Caskroom/kicad/*/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            "/usr/local/Caskroom/kicad/*/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            "/opt/homebrew/bin/kicad-cli",
            "/usr/local/bin/kicad-cli",
        ]
    return ["/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"]


def resolve_kicad_cli() -> Dict[str, Any]:
    searched: List[str] = []

    env_candidates: List[Tuple[str, str]] = []
    for var_name in ("KICAD_CLI", "KICAD_CLI_PATH"):
        value = os.environ.get(var_name)
        if not value:
            continue
        candidate = os.path.abspath(os.path.expanduser(value))
        env_candidates.append((candidate, f"env:{var_name}"))

    path_candidate = shutil.which("kicad-cli")
    if path_candidate:
        env_candidates.append((path_candidate, "PATH"))

    for fallback in _platform_fallbacks():
        for expanded in _expand_candidate(fallback):
            env_candidates.append((expanded, "fallback"))

    seen = set()
    for candidate, source in env_candidates:
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        searched.append(normalized)

        if not _is_executable_file(normalized):
            continue

        ok, error = _validate_kicad_cli(normalized)
        if ok:
            return {
                "found": True,
                "path": normalized,
                "source": source,
                "searched": searched,
                "validationError": "",
            }

        continue

    return {
        "found": False,
        "path": None,
        "source": None,
        "searched": searched,
        "validationError": "kicad-cli was not found or failed '--version' validation",
    }

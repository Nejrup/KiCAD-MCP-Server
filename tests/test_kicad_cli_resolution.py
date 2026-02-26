import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import utils.kicad_cli as kicad_cli


def _make_fake_cli(tmp_path: Path, name: str = "kicad-cli") -> str:
    cli_path = tmp_path / name
    cli_path.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then\n  echo "KiCad CLI 9.0"\n  exit 0\nfi\nexit 0\n',
        encoding="utf-8",
    )
    cli_path.chmod(cli_path.stat().st_mode | stat.S_IXUSR)
    return str(cli_path)


def test_resolve_uses_env_override_first(tmp_path, monkeypatch):
    env_cli = _make_fake_cli(tmp_path, "env-kicad-cli")
    fallback_cli = _make_fake_cli(tmp_path, "fallback-kicad-cli")

    monkeypatch.setenv("KICAD_CLI_PATH", env_cli)
    monkeypatch.delenv("KICAD_CLI", raising=False)
    monkeypatch.setattr(kicad_cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(kicad_cli, "_platform_fallbacks", lambda: [fallback_cli])

    result = kicad_cli.resolve_kicad_cli()
    assert result["found"] is True
    assert result["path"] == env_cli
    assert result["source"] == "env:KICAD_CLI_PATH"


def test_resolve_falls_back_when_env_invalid(tmp_path, monkeypatch):
    fallback_cli = _make_fake_cli(tmp_path, "fallback-kicad-cli")

    monkeypatch.setenv("KICAD_CLI_PATH", str(tmp_path / "does-not-exist"))
    monkeypatch.setattr(kicad_cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(kicad_cli, "_platform_fallbacks", lambda: [fallback_cli])

    result = kicad_cli.resolve_kicad_cli()
    assert result["found"] is True
    assert result["path"] == fallback_cli
    assert fallback_cli in result["searched"]


def test_resolve_reports_searched_paths_on_failure(tmp_path, monkeypatch):
    missing_a = str(tmp_path / "missing-a")
    missing_b = str(tmp_path / "missing-b")

    monkeypatch.delenv("KICAD_CLI", raising=False)
    monkeypatch.delenv("KICAD_CLI_PATH", raising=False)
    monkeypatch.setattr(kicad_cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        kicad_cli, "_platform_fallbacks", lambda: [missing_a, missing_b]
    )

    result = kicad_cli.resolve_kicad_cli()
    assert result["found"] is False
    assert missing_a in result["searched"]
    assert missing_b in result["searched"]

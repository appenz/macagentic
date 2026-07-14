from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("noteheader_tool", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
noteheader_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(noteheader_tool)


def test_main_runs_geoloc_in_its_directory(monkeypatch, tmp_path) -> None:
    geoloc_dir = tmp_path / "geoloc"
    geoloc_dir.mkdir()
    (geoloc_dir / "geoloc.py").write_text("print('ok')\n")
    monkeypatch.setattr(noteheader_tool, "GEOLOC_DIR", geoloc_dir)
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/parent-venv")

    calls: list[dict[str, object]] = []

    def fake_run(command, cwd=None, env=None, check=False):
        calls.append(
            {"command": command, "cwd": cwd, "env": env, "check": check}
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(noteheader_tool.subprocess, "run", fake_run)

    assert noteheader_tool.main() == 0
    assert len(calls) == 1
    assert calls[0]["command"] == ["uv", "run", "geoloc.py"]
    assert calls[0]["cwd"] == geoloc_dir
    assert calls[0]["check"] is False
    assert "VIRTUAL_ENV" not in calls[0]["env"]


def test_main_errors_when_geoloc_missing(monkeypatch, tmp_path, capsys) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(noteheader_tool, "GEOLOC_DIR", missing)

    assert noteheader_tool.main() == 1
    assert "geoloc not found" in capsys.readouterr().err

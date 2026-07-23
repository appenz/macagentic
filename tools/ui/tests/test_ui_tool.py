from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


TOOL_PATH = Path(__file__).parents[1] / "main.py"
SPEC = __import__("importlib").util.spec_from_file_location("ui_tool", TOOL_PATH)
assert SPEC and SPEC.loader
ui_tool = __import__("importlib").util.module_from_spec(SPEC)
SPEC.loader.exec_module(ui_tool)

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000


def _mock_screencapture(args, **kwargs):
    """screencapture writes the arg after '-o' (or last positional) to a fake PNG file."""
    output = args[-1]
    Path(output).write_bytes(FAKE_PNG)
    return SimpleNamespace(returncode=0)


def _mock_osascript(args, **kwargs):
    """osascript just returns success."""
    return SimpleNamespace(returncode=0)


def test_screenshot_stdout_returns_base64(tmp_path, monkeypatch, capsys) -> None:
    def capture_write(args, **kw):
        Path(args[-1]).write_bytes(FAKE_PNG)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ui_tool.subprocess, "run", capture_write)

    result = ui_tool.main(["screenshot"])
    assert result == 0
    output = capsys.readouterr().out
    assert "<MSWEA_MULTIMODAL_CONTENT>" in output
    assert "<CONTENT_TYPE>image_url</CONTENT_TYPE>" in output
    assert "data:image/png;base64," in output
    assert "</MSWEA_MULTIMODAL_CONTENT>" in output


def test_screenshot_save_to_file(tmp_path, monkeypatch) -> None:
    output = tmp_path / "shot.png"

    def capture_write(args, **kw):
        Path(args[-1]).write_bytes(FAKE_PNG)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ui_tool.subprocess, "run", capture_write)

    assert ui_tool.main(["screenshot", "-o", str(output)]) == 0
    data = output.read_bytes()
    assert len(data) > 1000
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_screenshot_window_name_raises() -> None:
    with patch.object(ui_tool.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
        assert ui_tool.main(["screenshot", "Finder"]) == 1


def test_click_calls_osascript(monkeypatch) -> None:
    captured: list[str] = []

    def record(args, **kw):
        captured.append(args[2])  # the script string (index 2 after "osascript" and "-e")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ui_tool.subprocess, "run", record)

    assert ui_tool.main(["click", "500", "200"]) == 0

    assert "System Events" in captured[0]
    assert "{500, 200}" in captured[0]


def test_type_calls_osascript(monkeypatch) -> None:
    captured: list[str] = []

    def record(args, **kw):
        captured.append(args[2])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ui_tool.subprocess, "run", record)

    assert ui_tool.main(["type", "hello world"]) == 0

    assert 'keystroke "hello world"' in captured[0]


def test_type_escapes_quotes_and_backslashes(monkeypatch) -> None:
    captured: list[str] = []

    def record(args, **kw):
        captured.append(args[2])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ui_tool.subprocess, "run", record)

    # Input with quotes and backslash — ui_type strips them from the text
    assert ui_tool.main(["type", 'say "hi" \\back']) == 0

    # The script template wraps keystroke in "...", so '"' will appear as part of
    # System Events' name. Check that the *input* quotes/backslashes are stripped
    # from the keystroke content.
    assert 'keystroke "say hi back"' in captured[0]  # quotes and backslash removed from input


def test_click_rejects_non_int() -> None:
    """argparse raises SystemExit(2) for invalid int — caught by the try/except chain."""
    with pytest.raises(SystemExit) as exc_info:
        ui_tool.main(["click", "abc", "100"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Integration tests (run real macOS commands — skipped by default)
# ---------------------------------------------------------------------------

import subprocess as _sp


def test_screenshot_multimodal_expandable(tmp_path, monkeypatch) -> None:
    """Verify screenshot output is parseable by the multimodal pipeline."""
    from minisweagent.models.utils.openai_multimodal import (
        DEFAULT_MULTIMODAL_REGEX,
        _expand_content_string,
    )

    def capture_write(args, **kw):
        Path(args[-1]).write_bytes(FAKE_PNG)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ui_tool.subprocess, "run", capture_write)

    import io
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    try:
        ui_tool.main(["screenshot"])
    finally:
        sys.stdout = old

    expanded = _expand_content_string(content=buf.getvalue(), pattern=DEFAULT_MULTIMODAL_REGEX)
    assert len(expanded) == 1
    assert expanded[0]["type"] == "image_url"
    assert expanded[0]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.hardware
def test_screenshot_integration() -> None:
    """Real screencapture produces valid multimodal-wrapped output."""
    result = _sp.run(
        [sys.executable, str(TOOL_PATH), "screenshot"],
        capture_output=True,
    )
    assert result.returncode == 0
    text = result.stdout.decode()
    assert "<MSWEA_MULTIMODAL_CONTENT>" in text
    # Extract base64 from the tag wrapper and verify it's valid PNG
    import re
    m = re.search(r"data:image/png;base64,([^<]+)", text)
    assert m is not None
    decoded = base64.b64decode(m.group(1))
    assert len(decoded) > 1000
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.hardware
def test_click_integration() -> None:
    """Real osascript click command runs without Python errors.

    Note: the actual click may still be blocked by macOS Accessibility
    permissions — we only verify the tool itself doesn't crash.
    """
    result = _sp.run(
        [sys.executable, str(TOOL_PATH), "click", "500", "300"],
        capture_output=True,
    )
    # Return code 0 means osascript succeeded fully.
    # Non-zero is also acceptable if it's only an AppleScript permission error
    # (osascript exit code 1 from System Events denial).
    if result.returncode != 0:
        err = result.stderr.decode()
        assert "osascript" in err, f"unexpected error: {err}"


@pytest.mark.hardware
def test_type_integration() -> None:
    """Real osascript type command succeeds."""
    result = _sp.run(
        [sys.executable, str(TOOL_PATH), "type", "test"],
        capture_output=True,
    )
    assert result.returncode == 0

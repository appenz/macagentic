import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("read_file_tool", TOOL_PATH)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def run(monkeypatch, root: Path, path: Path) -> int:
    monkeypatch.setenv("AGENT_ROOT", str(root))
    monkeypatch.setattr(sys, "argv", ["macagentic-read-file", str(path)])
    return tool.main()


def test_stages_numbered_image_and_pdf(monkeypatch, tmp_path, capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    image = tmp_path / "chart.png"
    pdf = tmp_path / "report.pdf"
    image.write_bytes(b"png")
    pdf.write_bytes(b"%PDF")

    assert run(monkeypatch, root, image) == 0
    first = json.loads(capsys.readouterr().out)["macagentic_context_file"]
    assert run(monkeypatch, root, pdf) == 0
    second = json.loads(capsys.readouterr().out)["macagentic_context_file"]

    assert first == "context/001-chart.png"
    assert second == "context/002-report.pdf"
    assert (root / first).read_bytes() == b"png"
    assert (root / second).read_bytes() == b"%PDF"


@pytest.mark.parametrize("name,size", [("note.txt", 1), ("big.png", tool.MAX_BYTES + 1)])
def test_rejects_unsupported_or_large_files(
    monkeypatch, tmp_path, name, size
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = tmp_path / name
    source.write_bytes(b"x")
    if size > 1:
        source.write_bytes(b"")
        source.open("wb").truncate(size)

    with pytest.raises(SystemExit):
        run(monkeypatch, root, source)
    assert not (root / "context").exists()

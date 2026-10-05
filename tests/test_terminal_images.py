import io
import sys

import pytest

pytest.importorskip("Cocoa", reason="image rendering requires macOS")
from AppKit import NSBitmapImageRep, NSPNGFileType

from macagentic.ui.terminal_images import inline_images


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def _write_png(path, width: int, height: int) -> None:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, width, height, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    path.write_bytes(bytes(rep.representationUsingType_properties_(NSPNGFileType, None)))


def _use_kitty_tty(monkeypatch) -> None:
    # Must run inside the test body: pytest's capture reinstalls sys.stdout
    # after fixture setup.
    monkeypatch.setattr(sys, "stdout", _Tty())
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)


def test_inline_images_untouched_without_terminal_support(tmp_path, monkeypatch) -> None:
    _write_png(tmp_path / "a.png", 4, 4)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    assert inline_images("![a](a.png)", tmp_path) == "![a](a.png)"

    monkeypatch.setattr(sys, "stdout", _Tty())
    monkeypatch.delenv("KITTY_WINDOW_ID")
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    assert inline_images("![a](a.png)", tmp_path) == "![a](a.png)"


def test_inline_images_replaces_only_valid_standalone_lines(tmp_path, monkeypatch) -> None:
    _use_kitty_tty(monkeypatch)
    _write_png(tmp_path / "a.png", 4, 4)
    (tmp_path / "b.jpg").write_bytes(b"\xff\xd8\xff")
    markdown = "![a](a.png)\n![b](b.jpg)\n![c](missing.png)\nsee ![a](a.png)\n![r](https://x/a.png)"
    lines = inline_images(markdown, tmp_path).split("\n")
    assert lines[0].startswith("\033_Ga=T,f=100,q=2,m=0;") and lines[0].endswith("\033\\")
    assert lines[1:] == ["![b](b.jpg)", "![c](missing.png)", "see ![a](a.png)", "![r](https://x/a.png)"]


def test_inline_images_chunks_large_payloads(tmp_path, monkeypatch) -> None:
    _use_kitty_tty(monkeypatch)
    _write_png(tmp_path / "big.png", 400, 400)
    sequence = inline_images("![big](big.png)", tmp_path)
    parts = sequence.split("\033\\")[:-1]
    assert len(parts) > 1
    assert parts[0].startswith("\033_Ga=T,f=100,q=2,m=1;")
    assert parts[-1].startswith("\033_Gm=0;")

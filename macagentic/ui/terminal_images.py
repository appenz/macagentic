"""Inline images for the CLI via the Kitty graphics protocol.

Public API: `inline_images()` (see `specs/markdown_cli.md`).
"""

from __future__ import annotations

import base64
import fcntl
import os
import re
import struct
import sys
import termios
from pathlib import Path

from macagentic.ui.image_render import ImageError, generate_render_image

_IMAGE_LINE_RE = re.compile(r"^\s*!\[[^\]]*\]\((?P<source>[^()\s]+)\)\s*$")
_CHUNK_SIZE = 4096
_FALLBACK_CELL_PX = (10, 20)
_MAX_ROWS = 24


def inline_images(markdown: str, base_directory: Path) -> str:
    """Replace standalone image lines with Kitty graphics sequences.

    Returns `markdown` unchanged unless stdout is a TTY in a Kitty-protocol
    terminal (kitty or Ghostty).
    """
    if not _terminal_supports_images():
        return markdown
    max_pixels = _max_pixels()
    lines = []
    for line in markdown.split("\n"):
        match = _IMAGE_LINE_RE.match(line)
        if match is None:
            lines.append(line)
            continue
        try:
            png = generate_render_image(
                match.group("source"),
                base_directory=base_directory,
                max_pixels=max_pixels,
                card=False,
            ).read_bytes()
        except (ImageError, OSError):
            lines.append(line)
            continue
        lines.append(_kitty_graphics(png))
    return "\n".join(lines)


def _terminal_supports_images() -> bool:
    if not getattr(sys.stdout, "isatty", lambda: False)():
        return False
    return bool(os.environ.get("KITTY_WINDOW_ID")) or (
        os.environ.get("TERM_PROGRAM") == "ghostty"
    )


def _max_pixels() -> tuple[int, int]:
    """Terminal width and `_MAX_ROWS` rows, in pixels."""
    try:
        packed = fcntl.ioctl(
            sys.stdout.fileno(), termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0)
        )
        rows, columns, xpixel, ypixel = struct.unpack("HHHH", packed)
    except (OSError, ValueError, AttributeError):
        rows, columns, xpixel, ypixel = 24, 80, 0, 0
    columns, rows = columns or 80, rows or 24
    cell_width = xpixel // columns if xpixel else _FALLBACK_CELL_PX[0]
    cell_height = ypixel // rows if ypixel else _FALLBACK_CELL_PX[1]
    return columns * cell_width, min(rows, _MAX_ROWS) * cell_height


def _kitty_graphics(png: bytes) -> str:
    """Transmit-and-display at native size; q=2 suppresses terminal replies."""
    payload = base64.standard_b64encode(png).decode("ascii")
    chunks = [payload[i : i + _CHUNK_SIZE] for i in range(0, len(payload), _CHUNK_SIZE)]
    parts = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        control = f"a=T,f=100,q=2,m={more}" if index == 0 else f"m={more}"
        parts.append(f"\033_G{control};{chunk}\033\\")
    return "".join(parts)

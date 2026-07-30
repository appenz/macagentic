#!/usr/bin/env python3
"""Manual math render debug helper.

Renders sample LaTeX through the same path as the Cocoa UI and writes
artifacts under /tmp/macagentic-math-debug/ for visual inspection.

Usage:
    uv run python -m scripts.manual_math_render
    uv run python -m scripts.manual_math_render "E=mc^2" --inline
    uv run python -m scripts.manual_math_render "\\nabla \\cdot \\mathbf{E} = \\frac{\\rho}{\\varepsilon_0}"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from AppKit import NSBitmapImageRep, NSColor, NSPNGFileType

from macagentic.ui.math_render import MathBitmap, MathCacheKey, lookup_or_render_math_bitmap

OUTPUT_DIR = Path("/tmp/macagentic-math-debug")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}")


def _save_nsimage(path: Path, image) -> bool:
    rep = NSBitmapImageRep.alloc().initWithData_(image.TIFFRepresentation())
    if rep is None:
        print(f"FAILED to rasterize PNG for {path.name}", file=sys.stderr)
        return False
    data = rep.representationUsingType_properties_(NSPNGFileType, None)
    if data is None:
        print(f"FAILED to encode PNG for {path.name}", file=sys.stderr)
        return False
    png_bytes = bytes(data)
    path.write_bytes(png_bytes)
    print(f"wrote {path} ({len(png_bytes)} bytes)")
    return True


def inspect_formula(
    latex: str,
    *,
    inline: bool,
    font_size: float,
    scale_factor: float,
) -> int:
    slug = latex.replace("\\", "").replace(" ", "_")[:40] or "expr"
    case_dir = OUTPUT_DIR / slug
    case_dir.mkdir(parents=True, exist_ok=True)
    _write_text(case_dir / "latex.txt", latex)

    cache: dict[MathCacheKey, MathBitmap] = {}
    bitmap = lookup_or_render_math_bitmap(
        cache,
        latex,
        inline=inline,
        color=NSColor.blackColor(),
        font_size=font_size,
        scale_factor=scale_factor,
    )
    _write_text(
        case_dir / "mathbitmap.txt",
        "\n".join(
            [
                f"inline={inline}",
                f"font_size={font_size}",
                f"scale_factor={scale_factor}",
                f"size={bitmap.size}",
                f"baseline={bitmap.baseline}",
                f"cache_entries={len(cache)}",
            ]
        ),
    )
    ok = _save_nsimage(case_dir / "mathbitmap.png", bitmap.image)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "latex",
        nargs="?",
        default=r"\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}",
    )
    parser.add_argument("--inline", action="store_true")
    parser.add_argument("--font-size", type=float, default=14.0)
    parser.add_argument("--scale-factor", type=float, default=2.0)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    status = inspect_formula(
        args.latex,
        inline=args.inline,
        font_size=args.font_size,
        scale_factor=args.scale_factor,
    )
    print(f"\nArtifacts in {OUTPUT_DIR}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())

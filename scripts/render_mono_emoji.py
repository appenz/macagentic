#!/usr/bin/env python3
"""Render emoji as monochrome template PNGs for macOS menus."""

from __future__ import annotations

from pathlib import Path

from AppKit import (
    NSBitmapImageRep,
    NSColor,
    NSDeviceRGBColorSpace,
    NSFont,
    NSGraphicsContext,
    NSPNGFileType,
)
from Foundation import NSMakePoint, NSString
from Quartz import CGContextClearRect, CGRectMake

OUT = Path(__file__).resolve().parents[1] / "macagentic" / "ui" / "assets"
SIZE = 64
EMOJI = {
    "model_fast": "⚡",
    "model_medium": "⚖\ufe0f",
    "model_slow": "⏳",
}


def _new_rgba_rep(size: int) -> NSBitmapImageRep:
    return NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None,
        size,
        size,
        8,
        4,
        True,
        False,
        NSDeviceRGBColorSpace,
        0,
        0,
    )


def render_mono_emoji(emoji: str, size: int = SIZE) -> NSBitmapImageRep:
    src = _new_rgba_rep(size)
    NSGraphicsContext.saveGraphicsState()
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(src)
    NSGraphicsContext.setCurrentContext_(context)
    context.setShouldAntialias_(True)
    CGContextClearRect(context.CGContext(), CGRectMake(0, 0, size, size))

    font = NSFont.systemFontOfSize_(size * 0.72)
    attrs = {"NSFont": font}
    text = NSString.stringWithString_(emoji)
    drawn = text.sizeWithAttributes_(attrs)
    point = NSMakePoint((size - drawn.width) / 2, (size - drawn.height) / 2)
    text.drawAtPoint_withAttributes_(point, attrs)
    NSGraphicsContext.restoreGraphicsState()

    out = _new_rgba_rep(size)
    for y in range(size):
        for x in range(size):
            color = src.colorAtX_y_(x, y)
            r = float(color.redComponent())
            g = float(color.greenComponent())
            b = float(color.blueComponent())
            a = float(color.alphaComponent())
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            alpha = min(1.0, lum * a * 1.35)
            if alpha < 0.04:
                alpha = 0.0
            out.setColor_atX_y_(
                NSColor.colorWithDeviceRed_green_blue_alpha_(1.0, 1.0, 1.0, alpha),
                x,
                y,
            )
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, emoji in EMOJI.items():
        rep = render_mono_emoji(emoji)
        data = rep.representationUsingType_properties_(NSPNGFileType, None)
        path = OUT / f"{name}.png"
        if not data.writeToFile_atomically_(str(path), True):
            raise SystemExit(f"failed to write {path}")
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

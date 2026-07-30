"""Render the source-run Dock icon with Apple's Icon Composer tooling."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
import subprocess
import tempfile

from AppKit import (
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSCompositingOperationSourceOver,
    NSDeviceRGBColorSpace,
    NSGraphicsContext,
    NSImage,
    NSWorkspace,
)


ROOT = Path(__file__).resolve().parents[1]
ICON_DOCUMENT = ROOT / "macagentic/ui/assets/AppIcon.icon"
OUTPUT = ROOT / "macagentic/ui/assets/icon.png"
CANVAS_SIZE = 1024
DEFAULT_ICTOOL = Path(
    "/Applications/Xcode.app/Contents/Applications/"
    "Icon Composer.app/Contents/Executables/ictool"
)
REFERENCE_APPS = (
    Path("/System/Applications/System Settings.app"),
    Path("/System/Applications/App Store.app"),
    Path("/System/Applications/Calculator.app"),
    Path("/System/Applications/Calendar.app"),
    Path("/System/Applications/Utilities/Activity Monitor.app"),
)


def _blank_bitmap() -> NSBitmapImageRep:
    bitmap = (
        NSBitmapImageRep.alloc()
        .initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None,
            CANVAS_SIZE,
            CANVAS_SIZE,
            8,
            4,
            True,
            False,
            NSDeviceRGBColorSpace,
            CANVAS_SIZE * 4,
            32,
        )
    )
    pixels = memoryview(bitmap.bitmapData()).cast("B")
    pixels[:] = b"\0" * len(pixels)
    return bitmap


def _draw(image: NSImage, bitmap: NSBitmapImageRep, frame: tuple[int, ...]) -> None:
    x, y, width, height = frame
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
    NSGraphicsContext.saveGraphicsState()
    try:
        NSGraphicsContext.setCurrentContext_(context)
        image.drawInRect_fromRect_operation_fraction_(
            ((x, y), (width, height)),
            ((0, 0), image.size()),
            NSCompositingOperationSourceOver,
            1.0,
        )
    finally:
        NSGraphicsContext.restoreGraphicsState()


def _opaque_frame(bitmap: NSBitmapImageRep) -> tuple[int, int, int, int]:
    pixels = memoryview(bitmap.bitmapData()).cast("B")
    row_bytes = bitmap.bytesPerRow()
    min_x = min_y = CANVAS_SIZE
    max_x = max_y = -1
    for y in range(CANVAS_SIZE):
        row = y * row_bytes
        for x in range(CANVAS_SIZE):
            if pixels[row + x * 4 + 3] == 255:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < 0:
        raise RuntimeError("Reference app icon has no opaque pixels")
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def _system_icon_frame() -> tuple[int, int, int, int]:
    workspace = NSWorkspace.sharedWorkspace()
    frames = []
    for app_path in REFERENCE_APPS:
        if not app_path.is_dir():
            continue
        image = workspace.iconForFile_(str(app_path))
        bitmap = _blank_bitmap()
        _draw(image, bitmap, (0, 0, CANVAS_SIZE, CANVAS_SIZE))
        frame = _opaque_frame(bitmap)
        if frame[2] == frame[3]:
            frames.append(frame)
    if not frames:
        raise RuntimeError("Could not measure a standard macOS app icon")
    return Counter(frames).most_common(1)[0][0]


def _fit_to_system_icon_frame(source: Path, destination: Path) -> None:
    image = NSImage.alloc().initWithContentsOfFile_(str(source))
    if image is None or image.size().width <= 0 or image.size().height <= 0:
        raise RuntimeError(f"Could not load rendered icon: {source}")
    frame = _system_icon_frame()
    bitmap = _blank_bitmap()
    _draw(image, bitmap, frame)
    png = bitmap.representationUsingType_properties_(
        NSBitmapImageFileTypePNG,
        {},
    )
    destination.write_bytes(bytes(png))
    print(f"Measured system app icon frame: {frame}")


def main() -> None:
    ictool = Path(os.environ.get("ICTOOL", DEFAULT_ICTOOL))
    if not ictool.is_file():
        raise SystemExit(
            f"Icon Composer renderer not found at {ictool}. "
            "Install Xcode 26 or set ICTOOL."
        )

    with tempfile.TemporaryDirectory(
        dir=OUTPUT.parent,
        prefix=f".{OUTPUT.stem}-",
    ) as temporary:
        temporary_dir = Path(temporary)
        rendered = temporary_dir / "rendered.png"
        fitted = temporary_dir / OUTPUT.name
        subprocess.run(
            [
                str(ictool),
                str(ICON_DOCUMENT),
                "--export-image",
                "--output-file",
                str(rendered),
                "--platform",
                "macOS",
                "--rendition",
                "Default",
                "--width",
                "1024",
                "--height",
                "1024",
                "--scale",
                "1",
            ],
            check=True,
        )
        _fit_to_system_icon_frame(rendered, fitted)
        fitted.replace(OUTPUT)

    print(f"Rendered {OUTPUT.relative_to(ROOT)} with {ictool}")


if __name__ == "__main__":
    main()

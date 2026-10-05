"""Markdown image files for display.

Public API: `generate_render_image()` and `image_attachment()`
(see `specs/markdown_images.md` and `specs/markdown_cocoa.md`).
"""

from __future__ import annotations

import re
import tempfile
from hashlib import sha1
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageRep,
    NSCompositingOperationSourceOver,
    NSGraphicsContext,
    NSPNGFileType,
    NSTextAttachment,
)
from Cocoa import NSColor, NSImage

_CACHE_DIR = Path(tempfile.gettempdir()) / "macagentic-images"
_REMOTE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

_CARD_PADDING_PX = 12
_CARD_RADIUS_PX = 12.0
_CARD_BORDER_PX = 2.0
_CARD_FILL = NSColor.colorWithCalibratedWhite_alpha_(0.97, 1.0)
_CARD_BORDER = NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.12)


class ImageError(RuntimeError):
    pass


def generate_render_image(
    source: str,
    *,
    base_directory: Path,
    max_pixels: tuple[int, int],
    card: bool,
) -> Path:
    """Return a display-ready PNG for a Markdown image source.

    Resolves `source` against `base_directory`, rejects URLs, scales down
    (never up) to fit `max_pixels`, and optionally draws a light card around
    the image. Output is content-addressed and reused.
    """
    if _REMOTE_RE.match(source):
        raise ImageError(f"Remote image sources are not fetched: {source}")
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = base_directory / path
    try:
        stat = path.stat()
    except OSError as error:
        raise ImageError(f"Cannot read image: {path}") from error

    key = sha1(
        f"image|{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{max_pixels}|{card}".encode()
    ).hexdigest()
    output = _CACHE_DIR / f"{key}.png"
    if output.exists():
        return output

    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None or not image.isValid():
        raise ImageError(f"Unsupported or corrupt image: {path}")
    width, height = _pixel_size(image)
    if width <= 0 or height <= 0:
        raise ImageError(f"Image has no size: {path}")

    pad = _CARD_PADDING_PX if card else 0
    scale = min(1.0, (max_pixels[0] - 2 * pad) / width, (max_pixels[1] - 2 * pad) / height)
    width = max(1, int(round(width * scale)))
    height = max(1, int(round(height * scale)))

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_draw_png(image, width, height, pad))
    return output


def image_attachment(
    path: Path,
    *,
    scale_factor: float,
    baseline: float = 0.0,
) -> NSTextAttachment:
    """Wrap a PNG as a text attachment sized at pixels ÷ `scale_factor`."""
    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None or not image.isValid():
        raise ImageError(f"Cannot load rendered image: {path}")
    width, height = _pixel_size(image)
    size = (width / scale_factor, height / scale_factor)
    image.setSize_(size)
    attachment = NSTextAttachment.alloc().init()
    attachment.setImage_(image)
    attachment.setBounds_(((0.0, baseline), size))
    return attachment


def _pixel_size(image: NSImage) -> tuple[int, int]:
    best = (0, 0)
    for rep in image.representations():
        best = max(best, (int(rep.pixelsWide()), int(rep.pixelsHigh())))
    if best == (0, 0):  # Vector images such as PDF report no pixels.
        size = image.size()
        best = (int(size.width), int(size.height))
    return best


def _draw_png(image: NSImage, width: int, height: int, pad: int) -> bytes:
    total_width, total_height = width + 2 * pad, height + 2 * pad
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, total_width, total_height, 8, 4, True, False,
        "NSCalibratedRGBColorSpace", 0, 0,
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(
        NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    )
    try:
        if pad:
            inset = _CARD_BORDER_PX / 2
            frame = ((inset, inset), (total_width - 2 * inset, total_height - 2 * inset))
            outline = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                frame, _CARD_RADIUS_PX, _CARD_RADIUS_PX
            )
            _CARD_FILL.setFill()
            outline.fill()
        image.drawInRect_fromRect_operation_fraction_(
            ((pad, pad), (width, height)),
            ((0.0, 0.0), (0.0, 0.0)),
            NSCompositingOperationSourceOver,
            1.0,
        )
        if pad:
            _CARD_BORDER.setStroke()
            outline.setLineWidth_(_CARD_BORDER_PX)
            outline.stroke()
    finally:
        NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))

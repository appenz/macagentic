"""LaTeX math rendering via ziamath and WebKit.

Public API: `render_math()` (see `specs/markdown_cocoa.md`).
"""

from __future__ import annotations

import tempfile
import time
from hashlib import sha1
from pathlib import Path

from AppKit import NSApplication, NSBitmapImageRep, NSColorSpace, NSPNGFileType
from Cocoa import NSColor, NSImage
from Foundation import NSDate, NSMakeRect, NSRunLoop, NSURL, NSThread
from WebKit import WKSnapshotConfiguration, WKWebView

import ziamath as zm

_WEBVIEW: WKWebView | None = None
_CACHE_DIR = Path(tempfile.gettempdir()) / "macagentic-images"

# STIX (ziamath) glyphs measure ~10% shorter than SF Pro at the same
# nominal point size; scale so inline math matches surrounding text.
_ZIAMATH_SIZE_SCALE = 1.1


class MathRenderError(RuntimeError):
    pass


def render_math(
    latex: str,
    *,
    inline: bool,
    font_size: float,
    color: NSColor,
    scale_factor: float,
) -> tuple[Path, float]:
    """Render LaTeX to a PNG at `scale_factor` pixels per point.

    Returns the PNG path and the baseline offset in points (0 for display
    math). Output is content-addressed and reused.
    """
    if not latex.strip():
        raise MathRenderError("Empty LaTeX expression")
    color_hex = _color_hex(color)
    expr = _latex(latex, inline=inline, font_size=font_size, color_hex=color_hex)
    baseline = float(expr.getyofst()) if inline else 0.0
    key = sha1(
        f"math|{latex}|{inline}|{font_size}|{color_hex}|{scale_factor}".encode()
    ).hexdigest()
    path = _CACHE_DIR / f"{key}.png"
    if not path.exists():
        width, height = expr.getsize()
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        png = _on_main_thread(
            lambda: _svg_to_png(expr.svg(), width, height, scale_factor=scale_factor)
        )
        path.write_bytes(png)
    return path, baseline


def _latex(latex: str, *, inline: bool, font_size: float, color_hex: str) -> zm.Latex:
    try:
        # margin=0 so SVG width/height match getsize(); default margin=1
        # would pad the SVG and shrink glyphs when scaled into getsize bounds.
        return zm.Latex(
            latex,
            size=font_size * _ZIAMATH_SIZE_SCALE,
            inline=inline,
            color=color_hex,
            margin=0,
        )
    except (ValueError, TypeError, SyntaxError, KeyError, AttributeError) as error:
        raise MathRenderError(f"Invalid LaTeX: {latex!r}") from error


def _on_main_thread(work):
    if NSThread.isMainThread():
        return work()

    from dispatch import dispatch_get_main_queue, dispatch_sync

    result: dict[str, object] = {}

    def wrapper() -> None:
        result["value"] = work()

    dispatch_sync(dispatch_get_main_queue(), wrapper)
    return result["value"]


def _color_hex(color: NSColor) -> str:
    rgb = color.colorUsingColorSpace_(NSColorSpace.genericRGBColorSpace())
    if rgb is None:
        return "#333333"
    return "#{:02x}{:02x}{:02x}".format(
        int(rgb.redComponent() * 255),
        int(rgb.greenComponent() * 255),
        int(rgb.blueComponent() * 255),
    )


def _ensure_application() -> None:
    app = NSApplication.sharedApplication()
    if app.delegate() is None:
        from AppKit import NSApplicationActivationPolicyAccessory

        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def _run_loop_until(timeout: float, predicate) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.01)
        )
    return predicate()


def _webview() -> WKWebView:
    global _WEBVIEW
    if _WEBVIEW is None:
        _WEBVIEW = WKWebView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
    return _WEBVIEW


def _bitmap_has_content(rep: NSBitmapImageRep) -> bool:
    data = rep.bitmapData()
    if data is None:
        return False
    width = rep.pixelsWide()
    height = rep.pixelsHigh()
    if width <= 0 or height <= 0:
        return False
    row_bytes = rep.bytesPerRow()
    samples = rep.samplesPerPixel()
    for y in range(height):
        row = y * row_bytes
        for x in range(width):
            offset = row + x * samples
            if offset + 2 >= len(data):
                continue
            if data[offset] < 250 or data[offset + 1] < 250 or data[offset + 2] < 250:
                return True
    return False


def _svg_to_png(
    svg: str,
    width: float,
    height: float,
    *,
    scale_factor: float,
) -> bytes:
    _ensure_application()
    # WebKit snapshots at 1x are blank for small ziamath SVGs; rasterize at 2x min.
    # CSS-scale the SVG to fill the snapshot so glyphs match font_size points.
    scale = max(scale_factor, 2.0)
    pixel_width = max(1, int(round(width * scale)))
    pixel_height = max(1, int(round(height * scale)))
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        "html,body{margin:0;padding:0;background:transparent;overflow:hidden;}"
        f"svg{{display:block;width:{pixel_width}px;height:{pixel_height}px;}}"
        "</style></head><body>"
        f"{svg}</body></html>"
    )

    view = _webview()
    view.setFrame_(NSMakeRect(0, 0, pixel_width, pixel_height))
    view.loadHTMLString_baseURL_(html, NSURL.URLWithString_("about:blank"))
    if not _run_loop_until(5.0, lambda: not view.isLoading()):
        raise MathRenderError("WebKit timed out loading math SVG")

    snapshot: dict[str, object] = {"image": None, "error": None}

    def handler(image, error) -> None:
        snapshot["error"] = error
        snapshot["image"] = image

    config = WKSnapshotConfiguration.alloc().init()
    config.setSnapshotWidth_(pixel_width)
    view.takeSnapshotWithConfiguration_completionHandler_(config, handler)
    if not _run_loop_until(
        5.0,
        lambda: snapshot["image"] is not None or snapshot["error"] is not None,
    ):
        raise MathRenderError("WebKit timed out taking math snapshot")

    if snapshot["error"] is not None:
        raise MathRenderError(f"WebKit snapshot failed: {snapshot['error']}")

    snap_image = snapshot["image"]
    if snap_image is None:
        raise MathRenderError("WebKit returned no math snapshot image")

    rep = NSBitmapImageRep.alloc().initWithData_(snap_image.TIFFRepresentation())
    if rep is None:
        raise MathRenderError("Failed to rasterize math snapshot")
    if not _bitmap_has_content(rep):
        raise MathRenderError("WebKit produced a blank math snapshot")

    if scale != scale_factor:
        rep = _resample(rep, int(round(width * scale_factor)), int(round(height * scale_factor)))
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))


def _resample(rep: NSBitmapImageRep, pixel_width: int, pixel_height: int) -> NSBitmapImageRep:
    from AppKit import NSGraphicsContext, NSCompositingOperationCopy

    source = NSImage.alloc().initWithSize_((rep.pixelsWide(), rep.pixelsHigh()))
    source.addRepresentation_(rep)
    target = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, max(1, pixel_width), max(1, pixel_height), 8, 4, True, False,
        "NSCalibratedRGBColorSpace", 0, 0,
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(
        NSGraphicsContext.graphicsContextWithBitmapImageRep_(target)
    )
    source.drawInRect_fromRect_operation_fraction_(
        ((0, 0), (pixel_width, pixel_height)), ((0, 0), (0, 0)),
        NSCompositingOperationCopy, 1.0,
    )
    NSGraphicsContext.restoreGraphicsState()
    return target

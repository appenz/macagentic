"""LaTeX math rendering via ziamath and WebKit."""

from __future__ import annotations

import time
from dataclasses import dataclass

from AppKit import NSApplication, NSBitmapImageRep, NSColorSpace
from Cocoa import NSColor, NSImage
from Foundation import NSDate, NSMakeRect, NSRunLoop, NSURL, NSThread
from WebKit import WKSnapshotConfiguration, WKWebView

import ziamath as zm

_WEBVIEW: WKWebView | None = None


@dataclass(frozen=True)
class MathCacheKey:
    latex: str
    inline: bool
    font_size: float
    color_hex: str
    scale_factor: float


@dataclass(frozen=True)
class MathBitmap:
    image: NSImage
    size: tuple[float, float]
    baseline: float


class MathRenderError(RuntimeError):
    pass


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


def _svg_to_nsimage(
    svg: str,
    width: float,
    height: float,
    *,
    scale_factor: float,
) -> NSImage:
    # WebKit snapshots at 1x are blank for small ziamath SVGs; rasterize at 2x min.
    scale = max(scale_factor, 2.0)
    pixel_width = max(1, int(round(width * scale)))
    pixel_height = max(1, int(round(height * scale)))
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;padding:0;background:transparent;'>"
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

    point_size = (width, height)
    rep.setSize_(point_size)
    image = NSImage.alloc().initWithSize_(point_size)
    image.addRepresentation_(rep)
    return image


def _render_latex_to_bitmap_main(
    latex: str,
    *,
    inline: bool,
    color_hex: str,
    font_size: float,
    scale_factor: float,
) -> MathBitmap:
    _ensure_application()

    try:
        expr = zm.Latex(latex, size=font_size, inline=inline, color=color_hex)
    except (ValueError, TypeError, SyntaxError, KeyError, AttributeError) as error:
        raise MathRenderError(f"Invalid LaTeX: {latex!r}") from error

    width, height = expr.getsize()
    baseline = expr.getyofst()
    svg = expr.svg()
    image = _svg_to_nsimage(
        svg,
        width,
        height,
        scale_factor=scale_factor,
    )
    return MathBitmap(image=image, size=(width, height), baseline=baseline)


def render_latex_to_bitmap(
    latex: str,
    *,
    inline: bool,
    color: NSColor,
    font_size: float,
    scale_factor: float = 1.0,
) -> MathBitmap:
    if not latex.strip():
        raise MathRenderError("Empty LaTeX expression")

    color_hex = _color_hex(color)
    if NSThread.isMainThread():
        return _render_latex_to_bitmap_main(
            latex,
            inline=inline,
            color_hex=color_hex,
            font_size=font_size,
            scale_factor=scale_factor,
        )

    from dispatch import dispatch_get_main_queue, dispatch_sync

    result: dict[str, MathBitmap] = {}

    def wrapper() -> None:
        result["value"] = _render_latex_to_bitmap_main(
            latex,
            inline=inline,
            color_hex=color_hex,
            font_size=font_size,
            scale_factor=scale_factor,
        )

    dispatch_sync(dispatch_get_main_queue(), wrapper)
    return result["value"]


def lookup_or_render_math_bitmap(
    cache: dict[MathCacheKey, MathBitmap],
    latex: str,
    *,
    inline: bool,
    color: NSColor,
    font_size: float,
    scale_factor: float,
) -> MathBitmap:
    key = MathCacheKey(
        latex=latex,
        inline=inline,
        font_size=font_size,
        color_hex=_color_hex(color),
        scale_factor=scale_factor,
    )
    cached = cache.get(key)
    if cached is not None:
        return cached
    bitmap = render_latex_to_bitmap(
        latex,
        inline=inline,
        color=color,
        font_size=font_size,
        scale_factor=scale_factor,
    )
    cache[key] = bitmap
    return bitmap

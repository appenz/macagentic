# Math Rendering

## Overview

The Cocoa UI renders LaTeX math-mode expressions in Markdown (`$...$` inline,
`$$...$$` display) as bitmap attachments in the conversation log. Rendering
uses ziamath (pure Python) for SVG and WebKit (via PyObjC) to rasterize SVG to
bitmap. The CLI is unchanged and prints raw Markdown.

Only `macagentic/ui/math_render.py` imports ziamath. `markdown.py` integrates
math tokens and owns the source map used for copy. `core.py` does not import
`math_render`.

## Math Render API

```python
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


def render_latex_to_bitmap(
    latex: str,
    *,
    inline: bool,
    color: NSColor,
    font_size: float,
    scale_factor: float = 1.0,
) -> MathBitmap: ...


def lookup_or_render_math_bitmap(
    cache: dict[MathCacheKey, MathBitmap],
    latex: str,
    *,
    inline: bool,
    color: NSColor,
    font_size: float,
    scale_factor: float,
) -> MathBitmap: ...
```

- `render_latex_to_bitmap`: Renders a LaTeX math expression to an `NSImage`.
  Raises on failure. Must run on AppKit's main thread (dispatches there when
  called from a worker thread).
- `lookup_or_render_math_bitmap`: Returns a cached bitmap or renders, stores,
  and returns it.
- `MathBitmap.size`: Attachment width and height in points.
- `MathBitmap.baseline`: ziamath `getyofst()` — bottom-of-bbox offset for
  inline attachment alignment.

Internal implementation uses `ziamath.Latex`, `getsize()`, `getyofst()`, and
`svg()`. A single shared offscreen `WKWebView` rasterizes SVG via snapshot.
WebKit rendering is single-flight on the main thread.

## Bitmap Cache

Each `UITab` owns `math_cache: dict[MathCacheKey, MathBitmap]`. The cache
persists for the tab lifetime. `MacAgenticUI._render_window()` passes the active
tab's cache to `MarkdownRenderer.render()`.

There is no global render cache in `math_render.py`.

## Markdown Integration

`MarkdownRenderer` enables `dollarmath_plugin` on the existing parser
(`allow_digits=True`) and handles `math_inline`, `math_block`, and
`math_block_label` tokens.

```python
class MarkdownRenderer:
    _source_markdown: str
    _source_map: list[tuple[int, int, int, int]]

    def render(
        self,
        text: str,
        color,
        *,
        math_cache: dict[MathCacheKey, MathBitmap],
    ) -> NSMutableAttributedString: ...

    def markdown_for_selection(self, char_range: tuple[int, int]) -> str: ...
```

- `_source_markdown`: The Markdown string passed to the most recent `render()`.
- `_source_map`: Half-open ranges linking rendered character indices to
  source Markdown indices. Plain text is 1:1. A math attachment occupies one
  rendered character and maps to the full `$...$` or `$$...$$` span. UI-only
  text such as `[copy]` links has no mapping and is omitted from copy output.
- `markdown_for_selection`: Returns a contiguous substring of
  `_source_markdown` for the rendered selection. Overlapping map entries
  determine the source start/end; characters between those entries (emphasis
  markers, blank lines, softbreaks) are included. Do not reconstruct by
  concatenating mapped fragments — that drops unmapped source characters.

On render failure, `lookup_or_render_math_bitmap` raises. There is no monospace
fallback.

## Font Sizing

Math size follows the surrounding text at render time. Inline math in body
text uses `base_font.pointSize()`. Inline math in headings uses
`HEADING_FONT_SIZES`. Display blocks use `FONT_SIZE`. Pass the window backing
scale as `scale_factor` for Retina; attachment bounds stay in points. WebKit
rasterizes at at least 2x to avoid blank snapshots, and the SVG is CSS-scaled
to fill that snapshot so glyphs are not undersized. ziamath is called with
`margin=0` and size `font_size * 1.1` so STIX glyphs optically match SF Pro.
Display-block line height is `max(LINE_HEIGHT, height - baseline)` so tall
formulas are not clipped.

## Copy

`ConversationTextView` overrides `copy_`. Copy calls
`renderer.markdown_for_selection(selectedRange())` and writes plain text to
the pasteboard. This covers keyboard, menu, and context-menu Copy.

Copy returns a contiguous slice of the rendered source Markdown (see
`markdown_for_selection` above), not a reconstruction from attachment
attributes or mapped fragments alone.

A math formula is one atomic attachment character; it cannot be partially
selected. Paste is unchanged.

Copy never reads attachment attributes or calls `math_render`.

## Dependencies

Add with `uv add ziamath mdit-py-plugins`. Do not hand-edit `pyproject.toml`.
WebKit is provided by macOS via `pyobjc-framework-WebKit`.

## Files

- `macagentic/ui/math_render.py`: ziamath wrapper and WebKit bitmap rendering.
- `macagentic/ui/markdown.py`: math token handling, source map, copy helper.
- `macagentic/ui/core.py`: custom `copy_` on `ConversationTextView`, `UITab`
  math cache, `_render_window` reentrancy guard.

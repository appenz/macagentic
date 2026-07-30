# Math Rendering

## Overview

The Cocoa UI renders Markdown math (`$...$` inline, `$$...$$` display) as
bitmap attachments. Pipeline: dollarmath tokens → ziamath SVG → WebKit
rasterization. The CLI prints raw Markdown.

Only `math_render.py` imports ziamath. `markdown.py` owns token integration and
the copy source map. `core.py` does not import `math_render`.

## Architecture

- Each `UITab` owns a `MathBitmapCache`; there is no global cache. The active
  tab’s cache is passed into `MarkdownRenderer.render()`.
- Before parsing, `$$...$$` spans are lifted to top-level placeholders so
  CommonMark lists cannot split display math (e.g. a lone `+` line).
- Render failure raises; there is no monospace fallback.
- WebKit rasterization is single-flight on the AppKit main thread.
- Copy uses `markdown_for_selection` only — never attachment attributes or
  `math_render`.

## Math Render API

```python
@dataclass(frozen=True)
class MathBitmap:
    image: NSImage
    size: tuple[float, float]  # points
    baseline: float            # inline vertical alignment offset


class MathBitmapCache:
    def render(
        self,
        latex: str,
        inline: bool,
        font_size: float,
        scale_factor: float,
        *,
        color: NSColor,
    ) -> MathBitmap: ...
```

`MathBitmapCache.render` returns a cached bitmap or renders, stores, and
returns it. Cache keys are private. Raises on failure. Rasterization runs on
the AppKit main thread.

## Markdown Integration

```python
class MarkdownRenderer:
    def render(
        self,
        text: str,
        color,
        *,
        math_bitmap_cache: MathBitmapCache,
    ) -> NSMutableAttributedString: ...

    def markdown_for_selection(self, char_range: tuple[int, int]) -> str: ...
```

`render` parses with `dollarmath_plugin` (`allow_digits=True`) and handles
`math_inline`, `math_block`, and `math_block_label`. Math size follows the
surrounding font; pass window backing scale as `scale_factor`.

`markdown_for_selection` returns a contiguous substring of the last rendered
source Markdown (including unmapped characters between mapped spans). Do not
reconstruct by concatenating mapped fragments.

`ConversationTextView.copy_` writes that Markdown to the pasteboard. A math
attachment is one atomic character.

## Testing

Screenshot testing for math rendering is described in `specs/testing.md`.

## Files

- `macagentic/ui/math_render.py`: ziamath wrapper and WebKit bitmap rendering.
- `macagentic/ui/markdown.py`: math token handling, source map, copy helper.
- `macagentic/ui/core.py`: custom `copy_` on `ConversationTextView`, `UITab`
  math bitmap cache, `_render_window` reentrancy guard.

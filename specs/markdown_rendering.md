# Markdown Rendering

## Overview

The CLI prints conversation Markdown as plain text. The Cocoa transcript parses
Markdown into a native attributed string. Rendering is presentation-only: the
conversation log remains the source of truth.

`macagentic/ui/markdown.py` owns Markdown parsing, attributed-string rendering,
and render metadata. `macagentic/ui/math_render.py` owns LaTeX bitmap generation.
`core.py` owns Cocoa interaction and pasteboard access.

## Ownership and API

`MacAgenticUI` shares one stateless `MarkdownRenderer`. Each render returns a
Cocoa attributed string and document-specific block metadata. Each `UITab`
separately owns its expanded-block IDs and `MathBitmapCache`.

```python
@dataclass(frozen=True)
class MarkdownRenderMetadata:
    block_contents: Mapping[str, str]
    block_ranges: tuple[tuple[str, int, int], ...]

    def block_content(self, block_id: str) -> str | None: ...


class MarkdownRenderer:
    def render(
        self,
        markdown: str,
        color: NSColor,
        *,
        expanded_block_ids: set[str],
        math_bitmap_cache: MathBitmapCache,
        scale_factor: float,
    ) -> tuple[NSMutableAttributedString, MarkdownRenderMetadata]: ...
```

## Block Rendering

The parser is Markdown-It with tables enabled and the dollar-math plugin.
Spacing uses paragraph attributes rather than visible blank lines.

- Prose and headings use system fonts; inline and block code use monospace.
- Lists use hanging indents and support nesting. Links are clickable and gain a
  subdued ` ↗` suffix.
- Tables use padded monospace columns, right-align numeric values, bold headers,
  and truncate at the transcript edge.
- Code blocks and blockquotes over 20 lines show five lines initially, with
  expand/collapse and `[copy]` links. Status fences render as subdued plain text.

Render metadata retains complete collapsible-block content and rendered ranges
for block copy and keyboard focus.

## Math Rendering

Inline math uses `$...$`; display math uses `$$...$$`. Parsing follows Pandoc's
`tex_math_dollars` rules (`allow_space=False`, `allow_digits=False`): whitespace
is not allowed directly inside delimiters and a digit may not immediately
follow the closing delimiter. This prevents currency such as
`$3,400/year ... > $10k` from being parsed as math.

Before Markdown parsing, display-math spans are lifted into top-level
placeholders so CommonMark list parsing cannot split expressions containing a
lone `+`, `-`, or `*` line.

Math tokens are rendered through this pipeline:

`dollarmath token → ziamath SVG → WebKit rasterization → NSTextAttachment`

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

Math follows the surrounding font size and current text color. The window's
backing scale is passed to rasterization. Rendering is single-flight on the
AppKit main thread, and each tab caches its own bitmaps.

`MathBitmapCache.render()` raises `MathRenderError` on failure. The Markdown
renderer catches it, logs a warning, and displays the literal `$...$` or
`$$...$$` source in the surrounding font. One invalid expression must never
fail the transcript render.

## Copy and Paste

- Transcript copy preserves the selected rendered text, styling, links, and
  table layout, publishing both rich-text and plain-text pasteboard forms.
  Visual block gaps become blank lines in the plain-text form.
- Math attachments become their original `$...$` or `$$...$$` source. Link
  arrows, `[copy]`, expand/collapse labels, and focus highlighting are omitted.
- A block's `[copy]` action copies its complete plain-text content regardless
  of expansion.
- Input paste always inserts the clipboard's plain-text representation,
  replacing the current selection and discarding rich formatting.

## Testing

Unit tests cover attributed output, block spacing, collapsible blocks, links,
tables, math, transcript copy, and plain-text input paste.

Screenshot testing and the manual math-rendering fixtures are described in
`specs/testing.md`.

## Files

- `macagentic/ui/markdown.py`: parser, attributed-string renderer,
  collapsible-block metadata, and copy attributes.
- `macagentic/ui/math_render.py`: ziamath and WebKit bitmap rendering.
- `macagentic/ui/core.py`: transcript copy, block-copy actions, plain-text input
  paste, per-tab render metadata, and per-tab math cache.
- `tests/test_markdown.py`: rendering and render-metadata tests.
- `tests/test_ui.py`: Cocoa copy/paste interaction tests.

# Cocoa Markdown Rendering

## Overview

The Cocoa transcript parses conversation Markdown into a native attributed
string. Rendering is presentation-only: the conversation log remains the source
of truth. The CLI projection of the same log is specified in
`specs/markdown_cli.md`.

`macagentic/ui/markdown.py` owns Markdown parsing, attributed-string rendering,
and render metadata. `macagentic/ui/math_render.py` renders LaTeX to PNG.
`macagentic/ui/image_render.py` sizes images and wraps PNGs as attachments.
`core.py` owns Cocoa interaction and pasteboard access.

## Ownership and API

`MacAgenticUI` shares one stateless `MarkdownRenderer`. Each render returns a
Cocoa attributed string and document-specific block metadata. Each `UITab`
owns its expanded-block IDs.

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
        image_base_directory: Path,  # the tab agent's root
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
  expand/collapse and `[copy]` links. Status fences render as subdued plain
  text; `` `quoted` `` spans drop their backticks and render in italics.

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

```python
math_render.render_math(
    latex: str, *, inline: bool, font_size: float, color: NSColor, scale_factor: float
) -> tuple[Path, float]  # PNG path, baseline offset in points; raises MathRenderError
```

Pipeline: `ziamath SVG → WebKit rasterization → PNG`, content-addressed under
`$TMPDIR/macagentic-images/`. Math follows the surrounding font size and text
color; rasterization is single-flight on the AppKit main thread.

## Images

Every graphic is a PNG file inserted through one function:

```python
image_render.image_attachment(
    path: Path, *, scale_factor: float, baseline: float = 0.0
) -> NSTextAttachment  # bounds = pixels ÷ scale_factor
```

- `math_inline` → `render_math(inline=True)`; flows in text at `baseline`.
- `math_block` → `render_math(inline=False)`; own line, centered.
- `image` → `generate_render_image(max_pixels=(600, 320) × scale, card=True)`
  (`specs/markdown_images.md`); own line, centered, click opens the file.

Own-line images get a paragraph line height matching the image. On
`MathRenderError` or `ImageError` the renderer logs a warning and shows the
literal `$...$`, `$$...$$`, or `![alt](source)` in the surrounding font at
reduced alpha. One bad graphic must never fail the transcript render.

## Copy and Paste

- Transcript copy preserves the selected rendered text, styling, links, and
  table layout, publishing both rich-text and plain-text pasteboard forms.
  Visual block gaps become blank lines in the plain-text form.
- Attachments become their `$...$`, `$$...$$`, or `![alt](source)` Markdown. Link arrows, `[copy]`, expand/collapse labels,
  and focus highlighting are omitted.
- A block's `[copy]` action copies its complete plain-text content regardless
  of expansion.
- Input paste always inserts the clipboard's plain-text representation,
  replacing the current selection and discarding rich formatting.

## Testing

Unit tests cover attributed output, block spacing, collapsible blocks, links,
tables, math, images, transcript copy, and plain-text input paste.

Screenshot testing and the manual math-rendering fixtures are described in
`specs/testing.md`.

## Files

- `macagentic/ui/markdown.py`: parser, attributed-string renderer,
  collapsible-block metadata, and copy attributes.
- `macagentic/ui/math_render.py`: `render_math()`.
- `macagentic/ui/image_render.py`: `generate_render_image()`, `image_attachment()`.
- `macagentic/ui/core.py`: transcript copy, block-copy actions, plain-text input
  paste, link clicks, and per-tab render metadata.
- `tests/test_markdown.py`: rendering and render-metadata tests.
- `tests/test_ui.py`: Cocoa copy/paste interaction tests.

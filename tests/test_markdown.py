import pytest
from unittest.mock import patch

pytest.importorskip("Cocoa", reason="Cocoa renderer requires macOS")
from AppKit import NSBitmapImageRep, NSPNGFileType
from Cocoa import (
    NSColor,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSLineBreakByTruncatingTail,
    NSParagraphStyleAttributeName,
)
from Foundation import NSString

from macagentic.ui.math_render import (
    MathBitmapCache,
    MathRenderError,
)
from macagentic.ui.markdown import (
    BLOCK_GAP,
    CODE_FONT_SIZE,
    LINE_HEIGHT,
    LIST_ITEM_SPACING,
    PARAGRAPH_GAP,
    MarkdownDisplayMap,
    MarkdownRenderer,
)


def _style_at(rendered, marker):
    index = str(rendered.string()).index(marker)
    style, _ = rendered.attribute_atIndex_effectiveRange_(
        NSParagraphStyleAttributeName,
        index,
        None,
    )
    return style


def _paragraph_styles(rendered):
    text = NSString.stringWithString_(str(rendered.string()))
    styles = []
    position = 0
    while position < rendered.length():
        paragraph_range = text.paragraphRangeForRange_((position, 0))
        style, _ = rendered.attribute_atIndex_effectiveRange_(
            NSParagraphStyleAttributeName,
            paragraph_range.location,
            None,
        )
        styles.append(style)
        position = paragraph_range.location + paragraph_range.length
    return styles


def _render(renderer, *args, **kwargs):
    rendered, _display_map = renderer.render(*args, **kwargs)
    return rendered


def test_markdown_renders_blocks_and_tables() -> None:
    renderer = MarkdownRenderer()
    rendered, display_map = renderer.render(
        "# Heading\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "```python\nprint('hello')\n```\n",
        NSColor.blackColor(),
    )

    text = str(rendered.string())
    assert "Heading" in text
    assert "A" in text and "2" in text
    assert "print('hello')" in text
    assert "[copy]" in text
    assert len(display_map.block_ranges) == 1


def test_markdown_renders_status_as_subdued_plain_text() -> None:
    rendered = _render(
        MarkdownRenderer(),
        "```status\nChecking calendar\n```\n\n"
        "```status\nReading event details\n```",
        NSColor.blackColor(),
    )

    assert str(rendered.string()) == "Checking calendar\nReading event details"
    color, _ = rendered.attribute_atIndex_effectiveRange_(
        NSForegroundColorAttributeName,
        0,
        None,
    )
    assert color.alphaComponent() == 0.55
    assert "[copy]" not in str(rendered.string())
    assert _style_at(rendered, "Checking").paragraphSpacing() == 0
    assert _style_at(rendered, "Reading").paragraphSpacingBefore() == 0


def test_markdown_lists_use_hanging_indents_and_spacing() -> None:
    renderer = MarkdownRenderer()
    rendered = _render(
        renderer,
        "Intro\n\n"
        "- First item with enough text to wrap onto another line in the UI\n"
        "- Second item\n\n"
        "After",
        NSColor.blackColor(),
    )

    text = str(rendered.string())
    bullet = text.index("•")
    attributes, _ = rendered.attributesAtIndex_effectiveRange_(
        bullet,
        None,
    )
    style = attributes[NSParagraphStyleAttributeName]
    second_bullet = text.index("•", bullet + 1)
    second_attributes, _ = rendered.attributesAtIndex_effectiveRange_(
        second_bullet,
        None,
    )
    second_style = second_attributes[NSParagraphStyleAttributeName]

    assert style.firstLineHeadIndent() == 14.0
    assert style.headIndent() == 28.0
    assert style.paragraphSpacing() == 3.5
    assert style.paragraphSpacingBefore() == 3.5
    assert second_style.paragraphSpacing() == 3.5
    assert "Second item\nAfter" in text


def test_markdown_uses_block_transition_spacing() -> None:
    renderer = MarkdownRenderer()
    color = NSColor.blackColor()

    paragraph_heading = _render(
        renderer,
        "Intro\n\n## Heading",
        color,
    )
    heading_paragraph = _render(
        renderer,
        "## Heading\n\nBody",
        color,
    )
    list_heading = _render(
        renderer,
        "- Item\n\n## Heading",
        color,
    )
    paragraph_list = _render(
        renderer,
        "Intro\n\n- Item",
        color,
    )

    assert _style_at(
        paragraph_heading,
        "Heading",
    ).paragraphSpacingBefore() == PARAGRAPH_GAP
    assert _style_at(
        heading_paragraph,
        "Body",
    ).paragraphSpacingBefore() == BLOCK_GAP
    assert _style_at(
        list_heading,
        "Heading",
    ).paragraphSpacingBefore() == PARAGRAPH_GAP
    assert _style_at(
        paragraph_list,
        "Item",
    ).paragraphSpacingBefore() == BLOCK_GAP


def test_markdown_list_outer_and_internal_spacing() -> None:
    renderer = MarkdownRenderer()
    rendered = _render(
        renderer,
        "Intro\n\n- One\n- Two\n- Three\n\nAfter",
        NSColor.blackColor(),
    )
    styles = [style for style in _paragraph_styles(rendered) if style is not None]

    assert styles[1].paragraphSpacingBefore() == BLOCK_GAP
    assert styles[1].paragraphSpacing() == LIST_ITEM_SPACING
    assert styles[2].paragraphSpacing() == LIST_ITEM_SPACING
    assert styles[3].paragraphSpacing() == BLOCK_GAP
    assert styles[4].paragraphSpacingBefore() == BLOCK_GAP


def test_markdown_heading_typography() -> None:
    renderer = MarkdownRenderer()
    rendered = _render(
        renderer,
        "# Title\n\n## Section\n\n### Subsection",
        NSColor.blackColor(),
    )
    text = str(rendered.string())

    expected = {
        "Title": (16.0, 16.0 * 1.2),
        "Section": (15.0, 15.0 * 1.2),
        "Subsection": (14.0, LINE_HEIGHT),
    }
    for marker, (font_size, line_height) in expected.items():
        index = text.index(marker)
        font, _ = rendered.attribute_atIndex_effectiveRange_(
            NSFontAttributeName,
            index,
            None,
        )
        style = _style_at(rendered, marker)
        assert font.pointSize() == font_size
        assert style.minimumLineHeight() == line_height
        assert style.maximumLineHeight() == line_height


def test_markdown_heavy_block_layout() -> None:
    renderer = MarkdownRenderer()
    rendered = _render(
        renderer,
        "Intro\n\n| A |\n|---|\n| 1 |",
        NSColor.blackColor(),
    )
    text = str(rendered.string())
    table_index = text.index("A")
    font, _ = rendered.attribute_atIndex_effectiveRange_(
        NSFontAttributeName,
        table_index,
        None,
    )
    style = _style_at(rendered, "A")

    assert font.pointSize() == CODE_FONT_SIZE
    assert style.firstLineHeadIndent() == 8.0
    assert style.headIndent() == 8.0
    assert style.lineBreakMode() == NSLineBreakByTruncatingTail
    assert style.paragraphSpacingBefore() == PARAGRAPH_GAP


def test_markdown_links_and_table_alignment() -> None:
    renderer = MarkdownRenderer()
    links = _render(
        renderer,
        "Visit https://example.com or [docs](https://example.com/docs).",
        NSColor.blackColor(),
    )
    table = _render(
        renderer,
        "| Name | Count |\n|---|---:|\n| A | 2 |\n| Longer | 10 |",
        NSColor.blackColor(),
    )

    assert str(links.string()).count(" ↗") == 2
    assert "A           2\nLonger     10" in str(table.string())


def test_markdown_renders_inline_and_block_math() -> None:
    renderer = MarkdownRenderer()
    cache = MathBitmapCache()
    source = "Energy $E=mc^2$ here\n\n$$\n24 \\times 576\n$$\n"
    rendered = _render(
        renderer,
        source,
        NSColor.blackColor(),
        math_bitmap_cache=cache,
    )
    text = str(rendered.string())

    assert "\ufffc" in text
    assert "$E=mc^2$" not in text
    assert "24 \\times 576" not in text
    assert len(cache) == 2


def test_math_bitmap_cache_reuses_bitmaps() -> None:
    cache = MathBitmapCache()
    renderer = MarkdownRenderer()
    source = "Again $x^2$ and $x^2$"

    _render(renderer, source, NSColor.blackColor(), math_bitmap_cache=cache)
    assert len(cache) == 1
    first = next(iter(cache._entries.values()))

    _render(renderer, source, NSColor.blackColor(), math_bitmap_cache=cache)
    assert len(cache) == 1
    assert next(iter(cache._entries.values())) is first


def test_display_math_uses_tall_line_height() -> None:
    renderer = MarkdownRenderer()
    latex = r"\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}"
    source = f"$$\n{latex}\n$$"
    rendered = _render(
        renderer,
        source,
        NSColor.blackColor(),
        math_bitmap_cache=MathBitmapCache(),
    )
    style = _style_at(rendered, "\ufffc")
    assert style.minimumLineHeight() > LINE_HEIGHT
    assert style.minimumLineHeight() >= 35.0


def test_math_bitmap_cache_produces_png() -> None:
    bitmap = MathBitmapCache().render(
        r"\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}",
        False,
        14.0,
        2.0,
        color=NSColor.blackColor(),
    )
    assert bitmap is not None
    rep = NSBitmapImageRep.alloc().initWithData_(bitmap.image.TIFFRepresentation())
    assert rep is not None
    png = rep.representationUsingType_properties_(NSPNGFileType, None)
    assert png is not None
    assert len(bytes(png)) > 1000


def test_markdown_inline_math_render_failure_falls_back_to_source() -> None:
    renderer = MarkdownRenderer()
    source = "Bad $x^2$ math"
    with patch.object(
        MathBitmapCache,
        "render",
        side_effect=MathRenderError("bad math"),
    ):
        rendered, display_map = renderer.render(
            source,
            NSColor.blackColor(),
            math_bitmap_cache=MathBitmapCache(),
        )
    text = str(rendered.string())
    assert text == source
    assert "\ufffc" not in text
    assert display_map.markdown_for_range((0, len(text))) == source


def test_markdown_display_math_render_failure_falls_back_to_source() -> None:
    renderer = MarkdownRenderer()
    source = "Before\n\n$$\nx^2\n$$\n\nAfter"
    with patch.object(
        MathBitmapCache,
        "render",
        side_effect=MathRenderError("bad math"),
    ):
        rendered, display_map = renderer.render(
            source,
            NSColor.blackColor(),
            math_bitmap_cache=MathBitmapCache(),
        )
    text = str(rendered.string())
    assert "\ufffc" not in text
    assert "$$\nx^2\n$$" in text
    assert display_map.markdown_for_range((0, len(text))) == source


def test_markdown_invalid_latex_renders_as_text() -> None:
    """Real ziamath failure (raw `&` / `>` produce invalid MathML)."""
    renderer = MarkdownRenderer()
    source = "so $a & b > c$ here"
    rendered = _render(
        renderer,
        source,
        NSColor.blackColor(),
        math_bitmap_cache=MathBitmapCache(),
    )
    assert str(rendered.string()) == source


def test_markdown_currency_pairs_are_not_math() -> None:
    renderer = MarkdownRenderer()
    cache = MathBitmapCache()
    source = (
        "1kW is $3,400/year at PG&E residential rates, "
        "so this is likely > $10k/year"
    )
    rendered = _render(
        renderer,
        source,
        NSColor.blackColor(),
        math_bitmap_cache=cache,
    )
    assert str(rendered.string()) == source
    assert len(cache) == 0


def test_markdown_currency_and_math_on_same_line() -> None:
    renderer = MarkdownRenderer()
    cache = MathBitmapCache()
    source = "costs $5 and $10 total, so $x^2$ applies"
    rendered = _render(
        renderer,
        source,
        NSColor.blackColor(),
        math_bitmap_cache=cache,
    )
    text = str(rendered.string())
    assert text.startswith("costs $5 and $10 total, so ")
    assert "\ufffc" in text
    assert "$x^2$" not in text
    assert len(cache) == 1


def test_markdown_for_selection_preserves_math_markdown() -> None:
    renderer = MarkdownRenderer()
    cache = MathBitmapCache()
    source = "Before $x^2$ after"
    rendered, display_map = renderer.render(
        source,
        NSColor.blackColor(),
        math_bitmap_cache=cache,
    )
    text = str(rendered.string())
    math_index = text.index("\ufffc")

    copied = display_map.markdown_for_range((0, len(text)))
    assert copied == source

    copied_math = display_map.markdown_for_range((math_index, 1))
    assert copied_math == "$x^2$"

    copied_mixed = display_map.markdown_for_range((0, math_index + 1))
    assert copied_mixed == "Before $x^2$"


def test_display_math_inside_list_with_plus_line_renders() -> None:
    """A lone `+` inside $$ must not split the fence via CommonMark lists."""
    renderer = MarkdownRenderer()
    cache = MathBitmapCache()
    source = (
        "1. **Ampère–Maxwell law**\n"
        "$$\n"
        r"\oint_{\partial S} \mathbf{B}\cdot d\boldsymbol{\ell}"
        "\n=\n"
        r"\mu_0 I_{\mathrm{enc}}"
        "\n+\n"
        r"\mu_0\varepsilon_0\frac{d}{dt}\int_S \mathbf{E}\cdot d\mathbf{A}"
        "\n$$\n"
    )
    rendered, display_map = renderer.render(
        source,
        NSColor.blackColor(),
        math_bitmap_cache=cache,
    )
    text = str(rendered.string())

    assert "\ufffc" in text
    assert "$$" not in text
    assert r"\oint" not in text
    assert len(cache) == 1
    assert display_map.markdown_for_range((0, len(text))) == source.rstrip()


def test_markdown_for_selection_preserves_source_not_reconstruction() -> None:
    """Copy must return source Markdown, including unmapped ** and blank lines."""
    renderer = MarkdownRenderer()
    source = (
        "**You:** Show me Maxwell\n\n"
        "**Gauss’s law**\n\n"
        "$$\n"
        r"\oint \mathbf{E}\cdot d\mathbf{A} = \frac{Q}{\varepsilon_0}"
        "\n$$\n\n"
        "**Ampère–Maxwell**\n\n"
        "$$\n"
        r"\oint \mathbf{B}\cdot d\mathbf{\ell} = \mu_0 I"
        "\n$$\n"
    )
    rendered, display_map = renderer.render(
        source,
        NSColor.blackColor(),
        math_bitmap_cache=MathBitmapCache(),
    )
    text = str(rendered.string())
    copied = display_map.markdown_for_range((0, len(text)))

    assert copied == source.rstrip()
    assert "**You:**" in copied
    assert "**Ampère–Maxwell**\n\n$$" in copied
    assert "formMaxwell" not in copied.replace("\n", "")
    assert "Ampère–Maxwell$$" not in copied.replace("\n", "")


def test_display_map_contains_only_python_metadata() -> None:
    renderer = MarkdownRenderer()
    source = "Before\n\n```\ncode\n```"
    _rendered, display_map = renderer.render(source, NSColor.blackColor())

    assert isinstance(display_map, MarkdownDisplayMap)
    assert display_map.markdown_source == source
    assert isinstance(display_map.source_spans, tuple)
    assert isinstance(display_map.block_contents, dict)
    assert isinstance(display_map.block_ranges, tuple)
    assert all(
        isinstance(value, (str, int))
        for span in display_map.source_spans
        for value in span
    )
    assert all(
        isinstance(value, (str, int))
        for block_range in display_map.block_ranges
        for value in block_range
    )


def test_renderer_reuse_does_not_leak_display_state() -> None:
    renderer = MarkdownRenderer()
    first_source = "First\n\n```\nfirst block\n```"
    _first_rendered, first_map = renderer.render(
        first_source,
        NSColor.blackColor(),
    )
    first_block_id = first_map.block_ranges[0][0]

    second_source = "Second only"
    _second_rendered, second_map = renderer.render(
        second_source,
        NSColor.blackColor(),
    )

    assert vars(renderer).keys() == {"_parser"}
    assert first_map.markdown_source == first_source
    assert first_map.block_content(first_block_id) == "first block"
    assert second_map.markdown_source == second_source
    assert second_map.block_ranges == ()
    assert second_map.block_content(first_block_id) is None


def test_expanded_block_ids_are_per_render_call() -> None:
    renderer = MarkdownRenderer()
    content = "\n".join(f"line {index}" for index in range(25))
    source = f"```\n{content}\n```"

    collapsed, collapsed_map = renderer.render(source, NSColor.blackColor())
    block_id = collapsed_map.block_ranges[0][0]
    expanded, expanded_map = renderer.render(
        source,
        NSColor.blackColor(),
        expanded_block_ids={block_id},
    )
    collapsed_again, collapsed_again_map = renderer.render(
        source,
        NSColor.blackColor(),
    )

    assert "20 more lines" in str(collapsed.string())
    assert "line 24" not in str(collapsed.string())
    assert "line 24" in str(expanded.string())
    assert "▾ collapse" in str(expanded.string())
    assert "20 more lines" in str(collapsed_again.string())
    assert "line 24" not in str(collapsed_again.string())
    assert expanded_map.block_content(block_id) == content
    assert collapsed_again_map.block_content(block_id) == content

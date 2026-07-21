from Cocoa import (
    NSColor,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSLineBreakByTruncatingTail,
    NSParagraphStyleAttributeName,
)
from Foundation import NSString

from macagentic.ui.markdown import (
    BLOCK_GAP,
    CODE_FONT_SIZE,
    LINE_HEIGHT,
    LIST_ITEM_SPACING,
    PARAGRAPH_GAP,
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


def test_markdown_renders_blocks_and_tables() -> None:
    renderer = MarkdownRenderer()
    rendered = renderer.render(
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
    assert len(renderer.block_ranges) == 1


def test_markdown_renders_status_as_subdued_plain_text() -> None:
    rendered = MarkdownRenderer().render(
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
    rendered = renderer.render(
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

    paragraph_heading = renderer.render(
        "Intro\n\n## Heading",
        color,
    )
    heading_paragraph = renderer.render(
        "## Heading\n\nBody",
        color,
    )
    list_heading = renderer.render(
        "- Item\n\n## Heading",
        color,
    )
    paragraph_list = renderer.render(
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
    rendered = renderer.render(
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
    rendered = renderer.render(
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
    rendered = renderer.render(
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
    links = renderer.render(
        "Visit https://example.com or [docs](https://example.com/docs).",
        NSColor.blackColor(),
    )
    table = renderer.render(
        "| Name | Count |\n|---|---:|\n| A | 2 |\n| Longer | 10 |",
        NSColor.blackColor(),
    )

    assert str(links.string()).count(" ↗") == 2
    assert "A           2\nLonger     10" in str(table.string())

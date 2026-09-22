"""Native Cocoa Markdown rendering."""

from dataclasses import dataclass
from hashlib import sha1
import logging
import re

from Cocoa import (
    NSAttributedString,
    NSAttachmentAttributeName,
    NSBackgroundColorAttributeName,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSLineBreakByTruncatingTail,
    NSLinkAttributeName,
    NSParagraphStyleAttributeName,
    NSUnderlineColorAttributeName,
    NSUnderlinePatternDot,
    NSUnderlineStyleAttributeName,
    NSUnderlineStyleSingle,
)
from Foundation import (
    NSMutableAttributedString,
    NSMutableParagraphStyle,
    NSURL,
)
from AppKit import NSTextAttachment, NSTextTab, NSScreen, NSTextAlignmentCenter
from mdit_py_plugins.dollarmath import dollarmath_plugin
from markdown_it import MarkdownIt

from macagentic.ui.math_render import (
    MathBitmap,
    MathBitmapCache,
    MathRenderError,
)

_LOGGER = logging.getLogger(__name__)

FONT_SIZE = 14.0
LINE_HEIGHT = FONT_SIZE * 1.2
PARAGRAPH_GAP = FONT_SIZE * 0.75
BLOCK_GAP = FONT_SIZE * 0.25
HEAVY_GAP = PARAGRAPH_GAP
LIST_ITEM_SPACING = FONT_SIZE * 0.25
LIST_BASE_INDENT = 14.0
INDENT_PER_LEVEL = 16.0
BULLET_TEXT_OFFSET = 14.0
CODE_FONT_SIZE = 12.0
COLLAPSE_AFTER_LINES = 20
COLLAPSE_PREVIEW_LINES = 5
COPY_OMIT_ATTRIBUTE = "MacAgenticCopyOmit"
MATH_SOURCE_ATTRIBUTE = "MacAgenticMathSource"


def _attributed(
    text,
    *,
    color,
    font=None,
    link=None,
    style=None,
    omit_from_copy=False,
):
    attrs = {
        NSForegroundColorAttributeName: color,
        NSFontAttributeName: font or NSFont.systemFontOfSize_(FONT_SIZE),
    }
    if link is not None:
        attrs[NSLinkAttributeName] = link
    if style is not None:
        attrs[NSParagraphStyleAttributeName] = style
    if omit_from_copy:
        attrs[COPY_OMIT_ATTRIBUTE] = True
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def _clean_url(raw):
    url = raw
    while url and url[-1] in _TRAILING_PUNCT:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def _linkify_text(text, color, font):
    result = NSMutableAttributedString.alloc().init()
    plain_attributes = {
        NSForegroundColorAttributeName: color,
        NSFontAttributeName: font,
    }
    last_end = 0
    for match in _URL_RE.finditer(text):
        url = _clean_url(match.group())
        url_end = match.start() + len(url)
        if match.start() > last_end:
            result.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(
                    text[last_end : match.start()],
                    plain_attributes,
                )
            )

        link_url = NSURL.URLWithString_(url)
        result.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                url,
                {
                    NSForegroundColorAttributeName: _LINK_COLOR,
                    NSFontAttributeName: font,
                    NSLinkAttributeName: link_url,
                    NSUnderlineStyleAttributeName: _UNDERLINE_STYLE,
                    NSUnderlineColorAttributeName: _UNDERLINE_COLOR,
                },
            )
        )
        result.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                _LINK_ARROW,
                {
                    NSForegroundColorAttributeName: _LINK_COLOR,
                    NSFontAttributeName: font,
                    NSLinkAttributeName: link_url,
                },
            )
        )
        last_end = url_end

    if last_end < len(text):
        result.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                text[last_end:],
                plain_attributes,
            )
        )
    return result


HEADING_FONT_SIZES = {1: 16.0, 2: 15.0}
TABLE_COLUMN_GAP = "  "
_NUMERIC_RE = re.compile(r"^[-+]?[$€£¥]?\d[\d,. ]*[%$€£¥]?$")
_URL_RE = re.compile(r"https?://\S+")
_TRAILING_PUNCT = frozenset(".,;:!?'\")}]>")
_LINK_ARROW = " ↗"
_LINK_COLOR = NSColor.colorWithCalibratedWhite_alpha_(0.50, 1.0)
_UNDERLINE_COLOR = NSColor.colorWithCalibratedWhite_alpha_(0.50, 0.45)
_UNDERLINE_STYLE = NSUnderlineStyleSingle | NSUnderlinePatternDot

_BLOCK_KIND = {
    "paragraph_open": "paragraph",
    "heading_open": "heading",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "table_open": "heavy",
    "fence": "heavy",
    "math_block": "heavy",
    "math_block_label": "heavy",
    "status": "status",
    "code_block": "heavy",
    "blockquote_open": "heavy",
}

_GAP_BEFORE = {
    ("start", "paragraph"): 0.0,
    ("start", "heading"): 0.0,
    ("start", "list"): 0.0,
    ("start", "heavy"): 0.0,
    ("start", "status"): 0.0,
    ("paragraph", "paragraph"): PARAGRAPH_GAP,
    ("paragraph", "heading"): PARAGRAPH_GAP,
    ("paragraph", "list"): BLOCK_GAP,
    ("paragraph", "heavy"): HEAVY_GAP,
    ("paragraph", "status"): BLOCK_GAP,
    ("heading", "paragraph"): BLOCK_GAP,
    ("heading", "heading"): BLOCK_GAP,
    ("heading", "list"): BLOCK_GAP,
    ("heading", "heavy"): HEAVY_GAP,
    ("heading", "status"): BLOCK_GAP,
    ("list", "paragraph"): BLOCK_GAP,
    ("list", "heading"): PARAGRAPH_GAP,
    ("list", "list"): BLOCK_GAP,
    ("list", "heavy"): HEAVY_GAP,
    ("list", "status"): BLOCK_GAP,
    ("heavy", "paragraph"): HEAVY_GAP,
    ("heavy", "heading"): HEAVY_GAP,
    ("heavy", "list"): HEAVY_GAP,
    ("heavy", "heavy"): HEAVY_GAP,
    ("heavy", "status"): BLOCK_GAP,
    ("status", "paragraph"): BLOCK_GAP,
    ("status", "heading"): BLOCK_GAP,
    ("status", "list"): BLOCK_GAP,
    ("status", "heavy"): BLOCK_GAP,
    ("status", "status"): 0.0,
}


def _paragraph_style(indent=0.0, *, line_height=LINE_HEIGHT):
    style = NSMutableParagraphStyle.alloc().init()
    style.setMinimumLineHeight_(line_height)
    style.setMaximumLineHeight_(line_height)
    style.setFirstLineHeadIndent_(indent)
    style.setHeadIndent_(indent)
    return style


def _gap_before(previous_type, current_type):
    previous = (
        "start" if previous_type is None else _BLOCK_KIND.get(previous_type, "paragraph")
    )
    current = _BLOCK_KIND.get(current_type, "paragraph")
    return _GAP_BEFORE.get((previous, current), BLOCK_GAP)


def _block_separator(gap: float):
    if not gap:
        return NSAttributedString.alloc().initWithString_("\n")
    style = NSMutableParagraphStyle.alloc().init()
    style.setMinimumLineHeight_(gap)
    style.setMaximumLineHeight_(gap)
    result = NSMutableAttributedString.alloc().initWithString_("\n\n")
    result.addAttributes_range_(
        {
            NSFontAttributeName: NSFont.systemFontOfSize_(1.0),
            NSParagraphStyleAttributeName: style,
        },
        (1, 1),
    )
    return result



def _md_line_start(source: str, line: int) -> int:
    if line <= 0:
        return 0
    pos = 0
    for _ in range(line):
        next_pos = source.find("\n", pos)
        if next_pos == -1:
            return len(source)
        pos = next_pos + 1
    return pos


def _md_line_range(source: str, start_line: int, end_line: int) -> tuple[int, int]:
    return _md_line_start(source, start_line), _md_line_start(source, end_line)


def _math_inline_source(inline_content: str, latex: str, markup: str) -> str:
    wrapped = f"{markup}{latex}{markup}"
    if wrapped in inline_content:
        return wrapped
    if markup != "$":
        alt = f"${latex}$"
        if alt in inline_content:
            return alt
    return wrapped


# Display math must be lifted out before CommonMark list parsing: a line that is
# only `+`/`-`/`*` inside `$$...$$` is a new list marker and splits the fence.
_DISPLAY_MATH_RE = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)
_DISPLAY_MATH_PLACEHOLDER_RE = re.compile(r"^MACAGENTIC_MATH_(\d+)$")
_DISPLAY_MATH_PLACEHOLDER = "MACAGENTIC_MATH_{index}"


def _extract_display_math(
    source: str,
) -> tuple[str, list[tuple[str, int, int]], list[tuple[int, int]]]:
    """Replace `$$...$$` with top-level placeholders; return parse text + spans.

    Returns `(parse_source, blocks, anchors)` where each block is
    `(latex, orig_start, orig_end)` for the full `$$...$$` span, and `anchors`
    map parse-source offsets back to `source` offsets.
    """
    blocks: list[tuple[str, int, int]] = []
    anchors: list[tuple[int, int]] = [(0, 0)]
    out: list[str] = []
    mod_len = 0
    last = 0
    for match in _DISPLAY_MATH_RE.finditer(source):
        gap = source[last : match.start()]
        out.append(gap)
        mod_len += len(gap)
        index = len(blocks)
        blocks.append((match.group(1), match.start(), match.end()))
        placeholder = f"\n\n$${_DISPLAY_MATH_PLACEHOLDER.format(index=index)}$$\n\n"
        anchors.append((mod_len, match.start()))
        out.append(placeholder)
        mod_len += len(placeholder)
        anchors.append((mod_len, match.end()))
        last = match.end()
    out.append(source[last:])
    return "".join(out), blocks, anchors


def _map_parse_to_source(parse_pos: int, anchors: list[tuple[int, int]]) -> int:
    mod_base = 0
    orig_base = 0
    for mod_pos, orig_pos in anchors:
        if mod_pos > parse_pos:
            break
        mod_base = mod_pos
        orig_base = orig_pos
    return orig_base + (parse_pos - mod_base)


def _backing_scale() -> float:
    screen = NSScreen.mainScreen()
    if screen is None:
        return 1.0
    return float(screen.backingScaleFactor())


def _math_line_height(bitmap: MathBitmap) -> float:
    _width, height = bitmap.size
    return max(LINE_HEIGHT, height - bitmap.baseline)


def _append_math_attachment(
    result,
    latex: str,
    *,
    copy_source: str,
    inline: bool,
    color,
    font_size: float,
    math_bitmap_cache: MathBitmapCache,
    scale_factor: float,
) -> tuple[int, int, MathBitmap]:
    start = result.length()
    bitmap = math_bitmap_cache.render(
        latex,
        inline,
        font_size,
        scale_factor,
        color=color,
    )
    attachment = NSTextAttachment.alloc().init()
    attachment.setImage_(bitmap.image)
    width, height = bitmap.size
    attachment.setBounds_(((0.0, bitmap.baseline), (width, height)))
    result.appendAttributedString_(
        NSAttributedString.attributedStringWithAttachment_(attachment)
    )
    result.addAttributes_range_(
        {
            MATH_SOURCE_ATTRIBUTE: copy_source,
            NSForegroundColorAttributeName: color,
            NSFontAttributeName: NSFont.systemFontOfSize_(font_size),
        },
        (start, result.length() - start),
    )
    return start, result.length(), bitmap


def _linkify_text(text, color, font):
    result = NSMutableAttributedString.alloc().init()
    plain_attributes = {
        NSForegroundColorAttributeName: color,
        NSFontAttributeName: font,
    }
    last_end = 0
    for match in _URL_RE.finditer(text):
        url = _clean_url(match.group())
        url_end = match.start() + len(url)
        if match.start() > last_end:
            chunk = text[last_end : match.start()]
            result.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(
                    chunk,
                    plain_attributes,
                )
            )

        link_url = NSURL.URLWithString_(url)
        result.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                url,
                {
                    NSForegroundColorAttributeName: _LINK_COLOR,
                    NSFontAttributeName: font,
                    NSLinkAttributeName: link_url,
                    NSUnderlineStyleAttributeName: _UNDERLINE_STYLE,
                    NSUnderlineColorAttributeName: _UNDERLINE_COLOR,
                },
            )
        )
        result.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                _LINK_ARROW,
                {
                    NSForegroundColorAttributeName: _LINK_COLOR,
                    NSFontAttributeName: font,
                    NSLinkAttributeName: link_url,
                    COPY_OMIT_ATTRIBUTE: True,
                },
            )
        )
        last_end = url_end

    if last_end < len(text):
        chunk = text[last_end:]
        result.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                chunk,
                plain_attributes,
            )
        )
    return result


@dataclass(frozen=True)
class MarkdownRenderMetadata:
    """Pure-Python interaction metadata for one rendered document."""

    block_contents: dict[str, str]
    block_ranges: tuple[tuple[str, int, int], ...]

    def block_content(self, block_id: str) -> str | None:
        return self.block_contents.get(block_id)


def prepare_copy(attributed) -> NSMutableAttributedString:
    """Return rendered content prepared for the system pasteboard."""
    rich = NSMutableAttributedString.alloc().init()
    index = 0
    while index < attributed.length():
        attributes, effective = attributed.attributesAtIndex_effectiveRange_(
            index,
            None,
        )
        end = min(
            attributed.length(),
            effective.location + effective.length,
        )
        length = end - index
        if attributes.get(COPY_OMIT_ATTRIBUTE):
            index = end
            continue

        math_source = attributes.get(MATH_SOURCE_ATTRIBUTE)
        if math_source is not None:
            copy_attributes = dict(attributes)
            copy_attributes.pop(NSAttachmentAttributeName, None)
            copy_attributes.pop(MATH_SOURCE_ATTRIBUTE, None)
            copy_attributes.pop(NSBackgroundColorAttributeName, None)
            copy_attributes.pop(COPY_OMIT_ATTRIBUTE, None)
            rich.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(
                    str(math_source),
                    copy_attributes,
                )
            )
        else:
            piece = NSMutableAttributedString.alloc().initWithAttributedString_(
                attributed.attributedSubstringFromRange_((index, length))
            )
            piece.removeAttribute_range_(
                COPY_OMIT_ATTRIBUTE,
                (0, piece.length()),
            )
            piece.removeAttribute_range_(
                NSBackgroundColorAttributeName,
                (0, piece.length()),
            )
            rich.appendAttributedString_(piece)
        index = end
    return rich


class MarkdownRenderer:
    """Reusable Markdown parser and Cocoa attributed-string renderer."""

    def __init__(self) -> None:
        # Pandoc's tex_math_dollars rules: no whitespace just inside the
        # delimiters and no digit right after the closing `$`, so prose like
        # "$3,400/year ... > $10k" is currency, not math.
        self._parser = (
            MarkdownIt()
            .enable("table")
            .use(dollarmath_plugin, allow_space=False, allow_digits=False)
        )

    def render(
        self,
        text: str,
        color,
        *,
        expanded_block_ids: set[str] | frozenset[str] = frozenset(),
        math_bitmap_cache: MathBitmapCache | None = None,
        scale_factor: float | None = None,
    ) -> tuple[NSMutableAttributedString, MarkdownRenderMetadata]:
        source = text.rstrip()
        parse_source, display_math, anchors = _extract_display_math(source)
        expanded = set(expanded_block_ids)
        cache = math_bitmap_cache if math_bitmap_cache is not None else MathBitmapCache()
        backing_scale = scale_factor if scale_factor is not None else _backing_scale()
        tokens = self._parser.parse(parse_source)
        block_contents: dict[str, str] = {}
        block_ranges: list[tuple[str, int, int]] = []
        blocks: list[tuple[str, object, str | None]] = []

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.type in {"bullet_list_open", "ordered_list_open"}:
                list_text, i = self._render_list(
                    tokens,
                    i,
                    color,
                    math_bitmap_cache=cache,
                    scale_factor=backing_scale,
                )
                blocks.append((token.type, list_text, None))
                continue

            if token.type in {"math_block", "math_block_label"}:
                block = self._render_math_block(
                    token,
                    color,
                    source=source,
                    display_math=display_math,
                    parse_source=parse_source,
                    anchors=anchors,
                    math_bitmap_cache=cache,
                    scale_factor=backing_scale,
                )
                blocks.append((token.type, block, None))
                i += 1
                continue

            if token.type in {"fence", "code_block"}:
                block = NSMutableAttributedString.alloc().init()
                if token.type == "fence" and token.info.strip() == "status":
                    block.appendAttributedString_(
                        _attributed(
                            (token.content or "").strip(),
                            color=color.colorWithAlphaComponent_(0.55),
                            font=NSFont.systemFontOfSize_(CODE_FONT_SIZE),
                            style=_paragraph_style(),
                        )
                    )
                    blocks.append(("status", block, None))
                    i += 1
                    continue
                block_id = self._append_collapsible_block(
                    block,
                    (token.content or "").rstrip("\n"),
                    color,
                    block_contents=block_contents,
                    expanded_block_ids=expanded,
                    monospace=True,
                )
                blocks.append((token.type, block, block_id))
                i += 1
                continue

            if token.type == "blockquote_open":
                content = []
                i += 1
                while i < len(tokens) and tokens[i].type != "blockquote_close":
                    if tokens[i].type == "inline":
                        content.append(tokens[i].content or "")
                    i += 1
                block = NSMutableAttributedString.alloc().init()
                block_id = self._append_collapsible_block(
                    block,
                    "\n".join(content).strip(),
                    color.colorWithAlphaComponent_(0.75),
                    block_contents=block_contents,
                    expanded_block_ids=expanded,
                    monospace=False,
                )
                blocks.append((token.type, block, block_id))
                i += 1
                continue

            if token.type == "table_open":
                block, i = self._render_table(tokens, i, color)
                blocks.append((token.type, block, None))
                continue

            if token.type in {"heading_open", "paragraph_open"}:
                close_type = (
                    "heading_close"
                    if token.type == "heading_open"
                    else "paragraph_close"
                )
                heading_level = 0
                if token.type == "heading_open" and token.tag[1:].isdigit():
                    heading_level = int(token.tag[1:])
                block = NSMutableAttributedString.alloc().init()
                i += 1
                while i < len(tokens) and tokens[i].type != close_type:
                    if tokens[i].type == "inline":
                        font = None
                        if heading_level:
                            size = HEADING_FONT_SIZES.get(
                                heading_level,
                                FONT_SIZE,
                            )
                            font = NSFont.boldSystemFontOfSize_(size)
                        inline_token = tokens[i]
                        inline_content = inline_token.content or ""
                        inline_block = self._render_inline(
                            inline_token.children or [],
                            color,
                            base_font=font,
                            inline_content=inline_content,
                            math_bitmap_cache=cache,
                            scale_factor=backing_scale,
                        )
                        block.appendAttributedString_(inline_block)
                    i += 1
                if block.length():
                    line_height = (
                        HEADING_FONT_SIZES.get(heading_level, FONT_SIZE) * 1.2
                        if heading_level
                        else LINE_HEIGHT
                    )
                    block.addAttribute_value_range_(
                        NSParagraphStyleAttributeName,
                        _paragraph_style(line_height=line_height),
                        (0, block.length()),
                    )
                blocks.append((token.type, block, None))
                i += 1
                continue

            i += 1

        result = NSMutableAttributedString.alloc().init()
        for index, (token_type, block, block_id) in enumerate(blocks):
            previous_type = blocks[index - 1][0] if index else None
            boundary_gap = _gap_before(previous_type, token_type)
            if index:
                result.appendAttributedString_(_block_separator(boundary_gap))
            base = result.length()
            result.appendAttributedString_(block)
            if block_id is not None:
                block_ranges.append((block_id, base, block.length()))

        metadata = MarkdownRenderMetadata(
            block_contents=block_contents,
            block_ranges=tuple(block_ranges),
        )
        return result, metadata

    @staticmethod
    def _render_math_block(
        token,
        color,
        *,
        source,
        display_math,
        parse_source,
        anchors,
        math_bitmap_cache,
        scale_factor,
    ):
        latex = (token.content or "").strip()
        placeholder = _DISPLAY_MATH_PLACEHOLDER_RE.match(latex)
        if placeholder is not None:
            index = int(placeholder.group(1))
            latex, md_start, md_end = display_math[index]
            latex = latex.strip()
        else:
            md_start, md_end = _md_line_range(
                parse_source,
                token.map[0],
                token.map[1],
            )
            md_start = _map_parse_to_source(md_start, anchors)
            md_end = _map_parse_to_source(md_end, anchors)
        copy_source = source[md_start:md_end].strip() or f"$${latex}$$"
        block = NSMutableAttributedString.alloc().init()
        try:
            _, _, bitmap = _append_math_attachment(
                block,
                latex,
                copy_source=copy_source,
                inline=False,
                color=color,
                font_size=FONT_SIZE,
                math_bitmap_cache=math_bitmap_cache,
                scale_factor=scale_factor,
            )
        except MathRenderError as error:
            _LOGGER.warning("Display math fell back to source text: %s", error)
            block.appendAttributedString_(
                _attributed(copy_source, color=color)
            )
            block.addAttribute_value_range_(
                NSParagraphStyleAttributeName,
                _paragraph_style(),
                (0, block.length()),
            )
            return block
        line_height = _math_line_height(bitmap)
        style = NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(NSTextAlignmentCenter)
        style.setMinimumLineHeight_(line_height)
        style.setMaximumLineHeight_(line_height)
        block.addAttribute_value_range_(
            NSParagraphStyleAttributeName,
            style,
            (0, block.length()),
        )
        return block

    @staticmethod
    def _has_following_list_item(tokens, start: int, close_type: str) -> bool:
        while start < len(tokens) and tokens[start].type != close_type:
            if tokens[start].type == "list_item_open":
                return True
            start += 1
        return False

    @staticmethod
    def _list_item_style(indent: float, *, is_last: bool):
        content_column = indent + BULLET_TEXT_OFFSET
        style = NSMutableParagraphStyle.alloc().init()
        style.setFirstLineHeadIndent_(indent)
        style.setHeadIndent_(content_column)
        style.setTabStops_([])
        tab = NSTextTab.alloc().initWithTextAlignment_location_options_(
            0,
            content_column,
            {},
        )
        style.setTabStops_([tab])
        style.setDefaultTabInterval_(BULLET_TEXT_OFFSET)
        style.setMinimumLineHeight_(LINE_HEIGHT)
        style.setMaximumLineHeight_(LINE_HEIGHT)
        if not is_last:
            style.setParagraphSpacing_(LIST_ITEM_SPACING)
        return style

    def _render_list(
        self,
        tokens,
        start: int,
        color,
        depth: int = 0,
        *,
        math_bitmap_cache,
        scale_factor,
    ):
        font = NSFont.systemFontOfSize_(FONT_SIZE)
        result = NSMutableAttributedString.alloc().init()
        ordered = tokens[start].type == "ordered_list_open"
        close_type = (
            "ordered_list_close" if ordered else "bullet_list_close"
        )
        indent = LIST_BASE_INDENT + depth * INDENT_PER_LEVEL
        item_number = 0
        if ordered:
            start_attr = tokens[start].attrGet("start")
            if start_attr is not None:
                item_number = int(start_attr) - 1
        first_item = True
        i = start + 1

        while i < len(tokens) and tokens[i].type != close_type:
            if tokens[i].type != "list_item_open":
                i += 1
                continue

            item_number += 1
            i += 1
            if not first_item:
                result.appendAttributedString_(
                    NSAttributedString.alloc().initWithString_("\n")
                )

            has_following = self._has_following_list_item(
                tokens,
                i + 1,
                close_type,
            )
            style = self._list_item_style(
                indent,
                is_last=not has_following,
            )
            first_item = False
            item_line = NSMutableAttributedString.alloc().init()
            prefix = f"{item_number}.\t" if ordered else "•\t"
            item_line.appendAttributedString_(
                _attributed(prefix, color=color, font=font)
            )
            nested = NSMutableAttributedString.alloc().init()

            while i < len(tokens) and tokens[i].type != "list_item_close":
                if tokens[i].type == "paragraph_open":
                    i += 1
                    while (
                        i < len(tokens)
                        and tokens[i].type != "paragraph_close"
                    ):
                        if tokens[i].type == "inline":
                            inline_token = tokens[i]
                            inline_content = inline_token.content or ""
                            inline_block = self._render_inline(
                                inline_token.children or [],
                                color,
                                base_font=font,
                                inline_content=inline_content,
                                math_bitmap_cache=math_bitmap_cache,
                                scale_factor=scale_factor,
                            )
                            item_line.appendAttributedString_(inline_block)
                        i += 1
                    i += 1
                elif tokens[i].type in {
                    "bullet_list_open",
                    "ordered_list_open",
                }:
                    nested_list, i = self._render_list(
                        tokens,
                        i,
                        color,
                        depth + 1,
                        math_bitmap_cache=math_bitmap_cache,
                        scale_factor=scale_factor,
                    )
                    nested.appendAttributedString_(
                        NSAttributedString.alloc().initWithString_("\n")
                    )
                    nested.appendAttributedString_(nested_list)
                else:
                    i += 1

            i += 1
            item_line.addAttribute_value_range_(
                NSParagraphStyleAttributeName,
                style,
                (0, item_line.length()),
            )
            result.appendAttributedString_(item_line)
            if nested.length() > 0:
                result.appendAttributedString_(nested)

        return result, i + 1

    def _render_inline(
        self,
        children,
        color,
        base_font=None,
        *,
        inline_content: str = "",
        math_bitmap_cache,
        scale_factor,
    ):
        result = NSMutableAttributedString.alloc().init()
        font = base_font or NSFont.systemFontOfSize_(FONT_SIZE)
        bold_font = NSFont.boldSystemFontOfSize_(font.pointSize())
        bold = False
        index = 0
        while index < len(children):
            child = children[index]
            if child.type == "strong_open":
                bold = True
                index += 1
                continue
            if child.type == "strong_close":
                bold = False
                index += 1
                continue
            if child.type == "link_open":
                href = child.attrGet("href") or ""
                link_result = NSMutableAttributedString.alloc().init()
                link_text = ""
                index += 1
                while (
                    index < len(children)
                    and children[index].type != "link_close"
                ):
                    piece = children[index].content or ""
                    link_text += piece
                    link_result.appendAttributedString_(
                        _attributed(
                            piece,
                            color=_LINK_COLOR,
                            font=font,
                        )
                    )
                    index += 1
                if link_result.length():
                    link_url = NSURL.URLWithString_(href)
                    text_length = link_result.length()
                    link_result.addAttribute_value_range_(
                        NSLinkAttributeName,
                        link_url,
                        (0, text_length),
                    )
                    link_result.addAttribute_value_range_(
                        NSUnderlineStyleAttributeName,
                        _UNDERLINE_STYLE,
                        (0, text_length),
                    )
                    link_result.addAttribute_value_range_(
                        NSUnderlineColorAttributeName,
                        _UNDERLINE_COLOR,
                        (0, text_length),
                    )
                    link_result.appendAttributedString_(
                        _attributed(
                            _LINK_ARROW,
                            color=_LINK_COLOR,
                            font=font,
                            link=link_url,
                            omit_from_copy=True,
                        )
                    )
                    result.appendAttributedString_(link_result)
                index += 1
                continue
            if child.type == "softbreak":
                result.appendAttributedString_(
                    _attributed("\n", color=color, font=font)
                )
                index += 1
                continue
            if child.type == "math_inline":
                latex = child.content or ""
                markup = child.markup or "$"
                source = _math_inline_source(inline_content, latex, markup)
                try:
                    _append_math_attachment(
                        result,
                        latex,
                        copy_source=source,
                        inline=True,
                        color=color,
                        font_size=font.pointSize(),
                        math_bitmap_cache=math_bitmap_cache,
                        scale_factor=scale_factor,
                    )
                except MathRenderError as error:
                    _LOGGER.warning("Inline math fell back to source text: %s", error)
                    result.appendAttributedString_(
                        _attributed(source, color=color, font=font)
                    )
                index += 1
                continue

            content = child.content or ""
            if not content:
                index += 1
                continue
            if child.type == "code_inline":
                current_font = NSFont.monospacedSystemFontOfSize_weight_(
                    font.pointSize(),
                    0.0,
                )
            elif bold:
                current_font = bold_font
            else:
                current_font = font
            piece = _linkify_text(
                content,
                color,
                current_font,
            )
            result.appendAttributedString_(piece)
            index += 1
        return result

    def _append_collapsible_block(
        self,
        result,
        content: str,
        color,
        *,
        block_contents: dict[str, str],
        expanded_block_ids: set[str],
        monospace: bool,
    ) -> None:
        block_id = sha1(content.encode("utf-8")).hexdigest()[:12]
        block_contents[block_id] = content
        lines = content.splitlines() or [""]
        collapsed = (
            len(lines) > COLLAPSE_AFTER_LINES
            and block_id not in expanded_block_ids
        )
        shown = "\n".join(lines[:COLLAPSE_PREVIEW_LINES]) if collapsed else content
        start = result.length()
        font = (
            NSFont.monospacedSystemFontOfSize_weight_(CODE_FONT_SIZE, 0.0)
            if monospace
            else NSFont.systemFontOfSize_(CODE_FONT_SIZE)
        )
        result.appendAttributedString_(
            _attributed(
                shown,
                color=color,
                font=font,
            )
        )
        if len(lines) > COLLAPSE_AFTER_LINES:
            if collapsed:
                label = f"\n  ▸ {len(lines) - COLLAPSE_PREVIEW_LINES} more lines"
            else:
                label = "\n  ▾ collapse"
            result.appendAttributedString_(
                _attributed(
                    label,
                    color=color.colorWithAlphaComponent_(0.40),
                    font=NSFont.systemFontOfSize_(10.0),
                    link=f"macagentic://toggle/{block_id}",
                    omit_from_copy=True,
                )
            )
        copy_prefix = "  " if len(lines) > COLLAPSE_AFTER_LINES else "\n  "
        result.appendAttributedString_(
            _attributed(
                f"{copy_prefix}[copy]",
                color=color.colorWithAlphaComponent_(0.40),
                font=NSFont.systemFontOfSize_(10.0),
                link=f"macagentic://copy/{block_id}",
                omit_from_copy=True,
            )
        )
        style = NSMutableParagraphStyle.alloc().init()
        style.setFirstLineHeadIndent_(8.0)
        style.setHeadIndent_(8.0)
        result.addAttribute_value_range_(
            NSParagraphStyleAttributeName,
            style,
            (start, result.length() - start),
        )
        return block_id

    def _render_table(self, tokens, start: int, color):
        headers = []
        rows = []
        current_row = []
        in_header = False
        i = start + 1
        while i < len(tokens) and tokens[i].type != "table_close":
            token = tokens[i]
            if token.type == "thead_open":
                in_header = True
            elif token.type == "thead_close":
                in_header = False
            elif token.type == "tr_open":
                current_row = []
            elif token.type == "tr_close":
                if in_header:
                    headers = current_row
                else:
                    rows.append(current_row)
            elif token.type == "inline":
                if token.children:
                    parts = [
                        " " if child.type == "softbreak" else child.content
                        for child in token.children
                        if child.type == "softbreak" or child.content
                    ]
                    current_row.append("".join(parts))
                else:
                    current_row.append(token.content or "")
            i += 1

        all_rows = ([headers] if headers else []) + rows
        if not all_rows:
            return NSMutableAttributedString.alloc().init(), i + 1

        column_count = max(len(row) for row in all_rows)
        widths = [0] * column_count
        for row in all_rows:
            for column, cell in enumerate(row):
                widths[column] = max(widths[column], len(cell))

        alignments = []
        for column in range(column_count):
            cells = [
                row[column]
                for row in rows
                if column < len(row) and row[column].strip()
            ]
            numeric = (
                all(_NUMERIC_RE.match(cell.strip()) for cell in cells)
                if cells
                else False
            )
            alignments.append("right" if numeric else "left")

        def format_row(row):
            cells = []
            for column in range(column_count):
                cell = row[column] if column < len(row) else ""
                if alignments[column] == "right":
                    cells.append(cell.rjust(widths[column]))
                else:
                    cells.append(cell.ljust(widths[column]))
            return TABLE_COLUMN_GAP.join(cells)

        result = NSMutableAttributedString.alloc().init()
        regular_font = NSFont.monospacedSystemFontOfSize_weight_(
            CODE_FONT_SIZE,
            0.0,
        )
        bold_font = NSFont.monospacedSystemFontOfSize_weight_(
            CODE_FONT_SIZE,
            0.4,
        )
        if headers:
            result.appendAttributedString_(
                _attributed(
                    format_row(headers),
                    color=color,
                    font=bold_font,
                )
            )
            result.appendAttributedString_(
                _attributed(
                    "\n"
                    + TABLE_COLUMN_GAP.join(
                        "─" * width for width in widths
                    ),
                    color=color.colorWithAlphaComponent_(0.30),
                    font=regular_font,
                )
            )
        for row in rows:
            result.appendAttributedString_(
                _attributed(
                    "\n" + format_row(row),
                    color=color.colorWithAlphaComponent_(0.75),
                    font=regular_font,
                )
            )

        style = NSMutableParagraphStyle.alloc().init()
        style.setFirstLineHeadIndent_(8.0)
        style.setHeadIndent_(8.0)
        style.setLineBreakMode_(NSLineBreakByTruncatingTail)
        style.setAllowsDefaultTighteningForTruncation_(False)
        result.addAttribute_value_range_(
            NSParagraphStyleAttributeName,
            style,
            (0, result.length()),
        )
        return result, i + 1

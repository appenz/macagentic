"""Native Cocoa Markdown rendering."""

from hashlib import sha1
import re

from Cocoa import (
    NSAttributedString,
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
    NSString,
    NSURL,
)
from AppKit import NSTextAttachment, NSTextTab, NSScreen, NSTextAlignmentCenter
from mdit_py_plugins.dollarmath import dollarmath_plugin
from markdown_it import MarkdownIt

from macagentic.ui.math_render import (
    MathBitmap,
    MathBitmapCache,
)

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


def _attributed(text, *, color, font=None, link=None, style=None):
    attrs = {
        NSForegroundColorAttributeName: color,
        NSFontAttributeName: font or NSFont.systemFontOfSize_(FONT_SIZE),
    }
    if link is not None:
        attrs[NSLinkAttributeName] = link
    if style is not None:
        attrs[NSParagraphStyleAttributeName] = style
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


def _apply_block_margins(
    attributed, spacing_before=0.0, spacing_after=0.0
):
    if attributed.length() == 0 or (not spacing_before and not spacing_after):
        return attributed

    text = NSString.stringWithString_(str(attributed.string()))
    ranges = []
    position = 0
    while position < attributed.length():
        paragraph_range = text.paragraphRangeForRange_((position, 0))
        if paragraph_range.length == 0:
            break
        ranges.append((paragraph_range.location, paragraph_range.length))
        next_position = paragraph_range.location + paragraph_range.length
        if next_position <= position:
            break
        position = next_position

    for index, (location, length) in enumerate(ranges):
        style, _ = attributed.attribute_atIndex_effectiveRange_(
            NSParagraphStyleAttributeName,
            location,
            None,
        )
        style = (
            NSMutableParagraphStyle.alloc().init()
            if style is None
            else style.mutableCopy()
        )
        if index == 0 and spacing_before:
            style.setParagraphSpacingBefore_(spacing_before)
        if index == len(ranges) - 1 and spacing_after:
            style.setParagraphSpacing_(spacing_after)
        attributed.addAttribute_value_range_(
            NSParagraphStyleAttributeName,
            style,
            (location, length),
        )
    return attributed



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
    return start, result.length(), bitmap


def _linkify_text_mapped(text, color, font, md_start: int):
    result = NSMutableAttributedString.alloc().init()
    segments: list[tuple[int, int, int, int]] = []
    plain_attributes = {
        NSForegroundColorAttributeName: color,
        NSFontAttributeName: font,
    }
    last_end = 0
    rendered_at = 0
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
            chunk_start = rendered_at
            rendered_at += len(chunk)
            segments.append(
                (chunk_start, rendered_at, md_start + last_end, md_start + match.start())
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
        url_start = rendered_at
        rendered_at += len(url)
        segments.append(
            (url_start, rendered_at, md_start + match.start(), md_start + url_end)
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
        rendered_at += len(_LINK_ARROW)
        last_end = url_end

    if last_end < len(text):
        chunk = text[last_end:]
        result.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                chunk,
                plain_attributes,
            )
        )
        chunk_start = rendered_at
        rendered_at += len(chunk)
        segments.append(
            (chunk_start, rendered_at, md_start + last_end, md_start + len(text))
        )
    return result, segments


class MarkdownRenderer:
    """Render Markdown into one NSAttributedString and track interactive blocks."""

    def __init__(self) -> None:
        self._parser = (
            MarkdownIt().enable("table").use(dollarmath_plugin, allow_digits=True)
        )
        self._blocks: dict[str, str] = {}
        self._expanded: set[str] = set()
        self.block_ranges: list[tuple[str, int, int]] = []
        self._source_markdown = ""
        self._parse_source = ""
        self._parse_anchors: list[tuple[int, int]] = [(0, 0)]
        self._display_math: list[tuple[str, int, int]] = []
        self._source_map: list[tuple[int, int, int, int]] = []

    def _source_pos(self, parse_pos: int) -> int:
        return _map_parse_to_source(parse_pos, self._parse_anchors)

    def _source_line_start(self, line: int) -> int:
        return self._source_pos(_md_line_start(self._parse_source, line))

    def markdown_for_selection(self, char_range: tuple[int, int]) -> str:
        """Return the contiguous source-Markdown slice for a rendered selection.

        Mapped spans locate the selection in `_source_markdown`. The result is
        one substring of that source (not a join of mapped fragments), so
        unmapped source characters between spans — emphasis markers, blank
        lines, softbreak newlines — are preserved. UI-only rendered text with
        no source mapping is omitted by not extending the slice beyond the
        overlapping mapped ranges.
        """
        start, length = char_range
        if length <= 0:
            return ""
        end = start + length
        md_from: int | None = None
        md_to: int | None = None
        for rendered_start, rendered_end, md_start, md_end in self._source_map:
            if rendered_end <= start or rendered_start >= end:
                continue
            overlap_start = max(rendered_start, start)
            overlap_end = min(rendered_end, end)
            rendered_span = rendered_end - rendered_start
            md_span = md_end - md_start
            if rendered_span <= 0 or md_span <= 0:
                continue
            start_num = overlap_start - rendered_start
            end_num = overlap_end - rendered_start
            slice_start = md_start + (md_span * start_num) // rendered_span
            slice_end = md_start + (md_span * end_num) // rendered_span
            if md_from is None or slice_start < md_from:
                md_from = slice_start
            if md_to is None or slice_end > md_to:
                md_to = slice_end
        if md_from is None or md_to is None or md_to <= md_from:
            return ""

        # Include unmapped source at the edges (e.g. ** markers) so copy is a
        # true substring of the source, not a reconstruction of mapped pieces.
        covered: set[int] = set()
        for _r0, _r1, m0, m1 in self._source_map:
            covered.update(range(m0, m1))
        source_len = len(self._source_markdown)
        while md_from > 0 and (md_from - 1) not in covered:
            md_from -= 1
        while md_to < source_len and md_to not in covered:
            md_to += 1
        return self._source_markdown[md_from:md_to]

    def render(
        self,
        text: str,
        color,
        *,
        math_bitmap_cache: MathBitmapCache | None = None,
        scale_factor: float | None = None,
    ) -> NSMutableAttributedString:
        source = text.rstrip()
        self._source_markdown = source
        self._source_map = []
        parse_source, display_math, anchors = _extract_display_math(source)
        self._parse_source = parse_source
        self._display_math = display_math
        self._parse_anchors = anchors
        cache = math_bitmap_cache if math_bitmap_cache is not None else MathBitmapCache()
        backing_scale = scale_factor if scale_factor is not None else _backing_scale()
        tokens = self._parser.parse(parse_source)
        self._blocks = {}
        self.block_ranges = []
        blocks: list[tuple[str, object, str | None, list]] = []

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.type in {"bullet_list_open", "ordered_list_open"}:
                list_text, list_segments, i = self._render_list(
                    tokens, i, color, math_bitmap_cache=cache, scale_factor=backing_scale
                )
                blocks.append((token.type, list_text, None, list_segments))
                continue

            if token.type in {"math_block", "math_block_label"}:
                block, segments = self._render_math_block(
                    token, color, math_bitmap_cache=cache, scale_factor=backing_scale
                )
                blocks.append((token.type, block, None, segments))
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
                    blocks.append(("status", block, None, []))
                    i += 1
                    continue
                block_id = self._append_collapsible_block(
                    block,
                    (token.content or "").rstrip("\n"),
                    color,
                    monospace=True,
                )
                segments = self._fence_segments(token, block.length())
                blocks.append((token.type, block, block_id, segments))
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
                    monospace=False,
                )
                blocks.append((token.type, block, block_id, []))
                i += 1
                continue

            if token.type == "table_open":
                block, i = self._render_table(tokens, i, color)
                blocks.append((token.type, block, None, []))
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
                segments: list[tuple[int, int, int, int]] = []
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
                        inline_md_start = self._source_line_start(
                            inline_token.map[0] if inline_token.map else 0,
                        )
                        inline_block, inline_segments = self._render_inline(
                            inline_token.children or [],
                            color,
                            base_font=font,
                            inline_content=inline_content,
                            inline_md_start=inline_md_start,
                            math_bitmap_cache=cache,
                            scale_factor=backing_scale,
                        )
                        offset = block.length()
                        block.appendAttributedString_(inline_block)
                        segments.extend(
                            (offset + r0, offset + r1, m0, m1)
                            for r0, r1, m0, m1 in inline_segments
                        )
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
                blocks.append((token.type, block, None, segments))
                i += 1
                continue

            i += 1

        result = NSMutableAttributedString.alloc().init()
        for index, (token_type, block, block_id, segments) in enumerate(blocks):
            previous_type = blocks[index - 1][0] if index else None
            next_type = blocks[index + 1][0] if index + 1 < len(blocks) else None
            _apply_block_margins(
                block,
                _gap_before(previous_type, token_type),
                0.0 if next_type is None else _gap_before(token_type, next_type),
            )
            if index:
                result.appendAttributedString_(
                    NSAttributedString.alloc().initWithString_("\n")
                )
            base = result.length()
            result.appendAttributedString_(block)
            for rendered_start, rendered_end, md_start, md_end in segments:
                self._source_map.append(
                    (base + rendered_start, base + rendered_end, md_start, md_end)
                )
            if block_id is not None:
                self.block_ranges.append((block_id, base, block.length()))

        return result

    def block_content(self, block_id: str) -> str | None:
        return self._blocks.get(block_id)

    def _fence_segments(self, token, rendered_length: int):
        if not token.map or rendered_length <= 0:
            return []
        md_start, md_end = _md_line_range(
            self._parse_source,
            token.map[0],
            token.map[1],
        )
        md_start = self._source_pos(md_start)
        md_end = self._source_pos(md_end)
        content = (token.content or "").rstrip("\n")
        fence_start = self._source_markdown.find(content, md_start, md_end)
        if fence_start == -1:
            return [(0, rendered_length, md_start, md_end)]
        ui_end = min(rendered_length, len(content))
        return [(0, ui_end, fence_start, fence_start + ui_end)]

    def _render_math_block(self, token, color, *, math_bitmap_cache, scale_factor):
        latex = (token.content or "").strip()
        placeholder = _DISPLAY_MATH_PLACEHOLDER_RE.match(latex)
        if placeholder is not None:
            index = int(placeholder.group(1))
            latex, md_start, md_end = self._display_math[index]
            latex = latex.strip()
        else:
            md_start, md_end = _md_line_range(
                self._parse_source,
                token.map[0],
                token.map[1],
            )
            md_start = self._source_pos(md_start)
            md_end = self._source_pos(md_end)
        block = NSMutableAttributedString.alloc().init()
        rendered_start = block.length()
        _, _, bitmap = _append_math_attachment(
            block,
            latex,
            inline=False,
            color=color,
            font_size=FONT_SIZE,
            math_bitmap_cache=math_bitmap_cache,
            scale_factor=scale_factor,
        )
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
        segments = [(rendered_start, block.length(), md_start, md_end)]
        return block, segments

    def toggle_block(self, block_id: str) -> None:
        if block_id in self._expanded:
            self._expanded.remove(block_id)
        else:
            self._expanded.add(block_id)

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
        self, tokens, start: int, color, depth: int = 0, *, math_bitmap_cache, scale_factor
    ):
        font = NSFont.systemFontOfSize_(FONT_SIZE)
        result = NSMutableAttributedString.alloc().init()
        segments: list[tuple[int, int, int, int]] = []
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
            item_segments: list[tuple[int, int, int, int]] = []
            prefix = f"{item_number}.\t" if ordered else "•\t"
            item_line.appendAttributedString_(
                _attributed(prefix, color=color, font=font)
            )
            nested = NSMutableAttributedString.alloc().init()
            nested_segments: list[tuple[int, int, int, int]] = []

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
                            inline_md_start = self._source_line_start(
                                inline_token.map[0] if inline_token.map else 0,
                            )
                            inline_block, inline_segments = self._render_inline(
                                inline_token.children or [],
                                color,
                                base_font=font,
                                inline_content=inline_content,
                                inline_md_start=inline_md_start,
                                math_bitmap_cache=math_bitmap_cache,
                                scale_factor=scale_factor,
                            )
                            offset = item_line.length()
                            item_line.appendAttributedString_(inline_block)
                            item_segments.extend(
                                (offset + r0, offset + r1, m0, m1)
                                for r0, r1, m0, m1 in inline_segments
                            )
                        i += 1
                    i += 1
                elif tokens[i].type in {
                    "bullet_list_open",
                    "ordered_list_open",
                }:
                    nested_list, nested_segments, i = self._render_list(
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
            base = result.length()
            result.appendAttributedString_(item_line)
            segments.extend(
                (base + r0, base + r1, m0, m1) for r0, r1, m0, m1 in item_segments
            )
            if nested.length() > 0:
                nested_base = result.length()
                result.appendAttributedString_(nested)
                segments.extend(
                    (nested_base + r0, nested_base + r1, m0, m1)
                    for r0, r1, m0, m1 in nested_segments
                )

        return result, segments, i + 1

    def _render_inline(
        self,
        children,
        color,
        base_font=None,
        *,
        inline_content: str = "",
        inline_md_start: int = 0,
        math_bitmap_cache,
        scale_factor,
    ):
        result = NSMutableAttributedString.alloc().init()
        segments: list[tuple[int, int, int, int]] = []
        font = base_font or NSFont.systemFontOfSize_(FONT_SIZE)
        bold_font = NSFont.boldSystemFontOfSize_(font.pointSize())
        bold = False
        cursor = 0
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
                    pos = inline_content.find(link_text, cursor) if link_text else cursor
                    if pos == -1:
                        pos = cursor
                    md_start = inline_md_start + pos
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
                        )
                    )
                    offset = result.length()
                    result.appendAttributedString_(link_result)
                    segments.append(
                        (
                            offset,
                            offset + text_length,
                            md_start,
                            md_start + len(link_text),
                        )
                    )
                    cursor = pos + len(link_text)
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
                pos = inline_content.find(source, cursor)
                if pos == -1:
                    pos = cursor
                md_start = inline_md_start + pos
                md_end = md_start + len(source)
                rendered_start = result.length()
                _append_math_attachment(
                    result,
                    latex,
                    inline=True,
                    color=color,
                    font_size=font.pointSize(),
                    math_bitmap_cache=math_bitmap_cache,
                    scale_factor=scale_factor,
                )
                segments.append((rendered_start, result.length(), md_start, md_end))
                cursor = pos + len(source)
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
            pos = inline_content.find(content, cursor)
            if pos == -1:
                pos = cursor
            md_start = inline_md_start + pos
            piece, piece_segments = _linkify_text_mapped(
                content,
                color,
                current_font,
                md_start,
            )
            offset = result.length()
            result.appendAttributedString_(piece)
            segments.extend(
                (offset + r0, offset + r1, m0, m1)
                for r0, r1, m0, m1 in piece_segments
            )
            cursor = pos + len(content)
            index += 1
        return result, segments

    def _append_collapsible_block(
        self,
        result,
        content: str,
        color,
        *,
        monospace: bool,
    ) -> None:
        block_id = sha1(content.encode("utf-8")).hexdigest()[:12]
        self._blocks[block_id] = content
        lines = content.splitlines() or [""]
        collapsed = (
            len(lines) > COLLAPSE_AFTER_LINES
            and block_id not in self._expanded
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
                )
            )
        copy_prefix = "  " if len(lines) > COLLAPSE_AFTER_LINES else "\n  "
        result.appendAttributedString_(
            _attributed(
                f"{copy_prefix}[copy]",
                color=color.colorWithAlphaComponent_(0.40),
                font=NSFont.systemFontOfSize_(10.0),
                link=f"macagentic://copy/{block_id}",
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
        result.addAttribute_value_range_(
            NSParagraphStyleAttributeName,
            style,
            (0, result.length()),
        )
        return result, i + 1

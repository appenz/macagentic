from __future__ import annotations

import queue
import signal
import threading
from pathlib import Path

import objc
from Cocoa import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackgroundColorAttributeName,
    NSBackingStoreBuffered,
    NSBorderlessWindowMask,
    NSBox,
    NSBoxCustom,
    NSColor,
    NSCommandKeyMask,
    NSControlKeyMask,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageView,
    NSMenu,
    NSMenuItem,
    NSNoBorder,
    NSObject,
    NSOffState,
    NSOnState,
    NSPanel,
    NSParagraphStyleAttributeName,
    NSPasteboard,
    NSScreen,
    NSScrollView,
    NSShiftKeyMask,
    NSStringPboardType,
    NSTextField,
    NSTextView,
    NSThread,
    NSView,
    NSWindow,
    NSWorkspace,
    NSMutableAttributedString,
    NSMutableParagraphStyle,
)
from Foundation import NSTimer, NSURL
from quickmachotkey import mask, quickHotKey
from quickmachotkey.constants import kVK_Space, optionKey

from macagentic.agent import Agent
from macagentic.app import app
from macagentic.config import MODEL_TIERS
from macagentic.history import save_history
from macagentic.session import SavedSession, SavedTab, save_session as write_session
from macagentic.ui.helpers import request_fast_text
from macagentic.ui.math_render import MathBitmapCache
from macagentic.ui.markdown import (
    FONT_SIZE,
    MarkdownDisplayMap,
    MarkdownRenderer,
)
from macagentic.ui.projection import (
    display_model_name,
    render_conversation,
    render_history,
)
from macagentic.ui.updates import (
    AgentThreadCompleted,
    SetTabTitle,
    SetToolCallDescription,
    UIUpdate,
)


_hotkey_ui = None
_ASSETS = Path(__file__).parent / "assets"
_MODEL_TIER_KEYS = {"1": "fast", "2": "medium", "3": "slow"}
_MODEL_TIER_LABELS = {
    "fast": "Fast",
    "medium": "Medium",
    "slow": "Slow",
}
_MODEL_TIER_ICONS = {
    "fast": "model_fast.png",
    "medium": "model_medium.png",
    "slow": "model_slow.png",
}


def _load_template_image(filename: str) -> NSImage:
    image = NSImage.alloc().initByReferencingFile_(
        str(_ASSETS / filename)
    )
    # 16pt is the standard NSMenuItem image size (matches menu text).
    image.setSize_((16.0, 16.0))
    image.setTemplate_(True)
    return image


@quickHotKey(virtualKey=kVK_Space, modifierMask=mask(optionKey))
def _handle_hotkey():
    if _hotkey_ui is not None:
        _hotkey_ui.hotkey_pressed()


class QuickPanel(NSPanel):
    ui = None

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True

    def performKeyEquivalent_(self, event):
        flags = event.modifierFlags()
        key = str(event.charactersIgnoringModifiers() or "").lower()
        if flags & NSCommandKeyMask:
            responder = self.firstResponder()
            if key == "c" and hasattr(responder, "copy_"):
                responder.copy_(None)
                return True
            if key == "x" and hasattr(responder, "cut_"):
                responder.cut_(None)
                return True
            if key == "v" and hasattr(responder, "paste_"):
                if hasattr(responder, "pasteAndMatchStyle_"):
                    responder.pasteAndMatchStyle_(None)
                else:
                    responder.paste_(None)
                return True
            if key == "a" and hasattr(responder, "selectAll_"):
                responder.selectAll_(None)
                return True
            if key == "n" and self.ui is not None:
                self.ui.new_tab()
                return True
            if key == "w" and self.ui is not None:
                self.ui.close_tab(self.ui.active_index)
                return True
            if key in _MODEL_TIER_KEYS and self.ui is not None:
                self.ui.set_active_model_tier(_MODEL_TIER_KEYS[key])
                return True
        return objc.super(QuickPanel, self).performKeyEquivalent_(event)

    # System DefaultKeyBinding maps ^Tab / ^$Tab to these; reclaim for tabs.
    def selectNextKeyView_(self, _sender):
        if self.ui is not None:
            self.ui.cycle_tab(-1)

    def selectPreviousKeyView_(self, _sender):
        if self.ui is not None:
            self.ui.cycle_tab(1)


class TabCloseView(NSView):
    ui = None
    tab_id = -1

    def mouseDown_(self, _event):
        if self.ui is not None:
            self.ui.close_tab_by_id(self.tab_id)


class TabBarItemView(NSView):
    ui = None
    tab_id = -1
    title_label = None
    close_button = None
    active_background = None

    @objc.python_method
    def configure(self, ui, tab_id: int) -> None:
        self.ui = ui
        self.tab_id = tab_id

        background = NSBox.alloc().initWithFrame_(((0, 0), (1, 1)))
        background.setBoxType_(NSBoxCustom)
        background.setBorderType_(NSNoBorder)
        background.setCornerRadius_(4.0)
        background.setFillColor_(NSColor.whiteColor())
        background.setHidden_(True)
        self.addSubview_(background)
        self.active_background = background

        label = NSTextField.alloc().initWithFrame_(((0, 0), (1, 1)))
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setAlignment_(1)
        label.setFont_(NSFont.systemFontOfSize_(11.0))
        self.addSubview_(label)
        self.title_label = label

        close = TabCloseView.alloc().initWithFrame_(((0, 0), (1, 1)))
        close.ui = ui
        close.tab_id = tab_id
        close_label = NSTextField.alloc().initWithFrame_(((0, 0), (1, 1)))
        close_label.setStringValue_("×")
        close_label.setEditable_(False)
        close_label.setSelectable_(False)
        close_label.setBezeled_(False)
        close_label.setDrawsBackground_(False)
        close_label.setAlignment_(1)
        close.addSubview_(close_label)
        close.close_label = close_label
        self.addSubview_(close)
        self.close_button = close

    @objc.python_method
    def set_title(self, title: str, *, running: bool) -> None:
        value = f"⟳ {title}" if running else title
        self.title_label.setStringValue_(value)

    @objc.python_method
    def set_active(self, active: bool) -> None:
        self.active_background.setHidden_(not active)
        self.title_label.setTextColor_(
            NSColor.blackColor()
            if active
            else NSColor.colorWithCalibratedWhite_alpha_(0.4, 1.0)
        )

    @objc.python_method
    def layout(self, width: float, height: float, overlap: float) -> None:
        self.active_background.setFrame_(
            ((0, -overlap), (width, height + overlap))
        )
        self.title_label.setFrame_(((6, 0), (width - 28, height)))
        self.close_button.setFrame_(((width - 18, 0), (16, height)))
        self.close_button.close_label.setFrame_(((0, 0), (16, height)))

    def mouseDown_(self, _event):
        if self.ui is not None:
            self.ui.switch_tab_by_id(self.tab_id)


class ConversationTextView(NSTextView):
    ui = None
    content_view = None

    def keyDown_(self, event):
        characters = str(event.charactersIgnoringModifiers() or "")
        flags = event.modifierFlags()
        if characters == "\t":
            if flags & NSControlKeyMask:
                self.ui.cycle_tab(1 if flags & NSShiftKeyMask else -1)
            else:
                self.ui.focus_next_block(backwards=bool(flags & NSShiftKeyMask))
            return
        if characters in {"\r", "\n"}:
            self.ui.copy_focused_block()
            return
        if event.keyCode() == 53:
            self.ui.exit_block_focus()
            return
        objc.super(ConversationTextView, self).keyDown_(event)

    def copy_(self, _sender):
        display_map = (
            self.content_view.markdown_display_map
            if self.content_view is not None
            else None
        )
        if display_map is None:
            objc.super(ConversationTextView, self).copy_(None)
            return
        selected = self.selectedRange()
        if selected.length == 0:
            objc.super(ConversationTextView, self).copy_(None)
            return
        markdown = display_map.markdown_for_range(
            (selected.location, selected.length)
        )
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.declareTypes_owner_([NSStringPboardType], None)
        pasteboard.setString_forType_(markdown, NSStringPboardType)


class InputDelegate(NSObject):
    ui = None
    text_view = None

    def initWithUI_textView_(self, ui, text_view):
        self = objc.super(InputDelegate, self).init()
        self.ui = ui
        self.text_view = text_view
        text_view.setDelegate_(self)
        return self

    def textView_doCommandBySelector_(self, _view, selector):
        try:
            if selector == "insertNewline:":
                event = NSApp().currentEvent()
                flags = event.modifierFlags() if event is not None else 0
                text = str(self.text_view.string()).strip()
                if flags & NSShiftKeyMask:
                    self.text_view.insertText_("\n")
                    return True
                if flags & NSCommandKeyMask:
                    self.ui.interrupt_active(replacement=text)
                else:
                    self.ui.submit(text)
                return True
            if selector in ("selectNextKeyView:", "selectPreviousKeyView:"):
                # System DefaultKeyBinding maps ^Tab / ^$Tab to these.
                self.ui.cycle_tab(
                    1 if selector == "selectPreviousKeyView:" else -1
                )
                return True
            if selector in ("insertTab:", "insertBacktab:"):
                event = NSApp().currentEvent()
                flags = event.modifierFlags() if event is not None else 0
                if flags & NSControlKeyMask:
                    self.ui.cycle_tab(1 if flags & NSShiftKeyMask else -1)
                    return True
                if selector == "insertTab:" and self.ui.focus_next_block():
                    return True
                return False
            if selector == "cancelOperation:":
                self.ui.close_window()
                return True
            if selector == "noop:":
                event = NSApp().currentEvent()
                if event is None:
                    return False
                flags = event.modifierFlags()
                key = str(event.charactersIgnoringModifiers() or "").lower()
                if flags & NSControlKeyMask and key == "\t":
                    self.ui.cycle_tab(1 if flags & NSShiftKeyMask else -1)
                    return True
                if flags & NSCommandKeyMask:
                    if key == "c":
                        self.text_view.copy_(None)
                        return True
                    if key == "x":
                        self.text_view.cut_(None)
                        return True
                    if key == "v":
                        if hasattr(self.text_view, "pasteAndMatchStyle_"):
                            self.text_view.pasteAndMatchStyle_(None)
                        else:
                            self.text_view.paste_(None)
                        return True
                    if key == "a":
                        self.text_view.selectAll_(None)
                        return True
                    if key == "z":
                        undo_manager = self.text_view.undoManager()
                        if flags & NSShiftKeyMask:
                            if undo_manager.canRedo():
                                undo_manager.redo()
                        elif undo_manager.canUndo():
                            undo_manager.undo()
                        return True
                    if key == "n":
                        self.ui.new_tab()
                        return True
                    if key == "w":
                        self.ui.close_tab(self.ui.active_index)
                        return True
                    if key in _MODEL_TIER_KEYS:
                        self.ui.set_active_model_tier(_MODEL_TIER_KEYS[key])
                        return True
                if flags & NSControlKeyMask and key == "c":
                    self.ui.interrupt_active()
                    return True
            return False
        except Exception:
            return False


class ConversationDelegate(NSObject):
    ui = None

    def textView_clickedOnLink_atIndex_(self, _text_view, link, _index):
        value = str(link)
        if value.startswith("macagentic://copy/"):
            self.ui.copy_block(value.rsplit("/", 1)[-1])
            return True
        if value.startswith("macagentic://toggle/"):
            self.ui.toggle_block(value.rsplit("/", 1)[-1])
            return True
        try:
            NSWorkspace.sharedWorkspace().openURL_(
                NSURL.URLWithString_(value)
            )
            return True
        except Exception:
            return False


class TabContentView(NSView):
    ui = None
    tab_id = -1
    status_box = None
    status_view = None
    transcript_box = None
    transcript_scroll = None
    transcript_view = None
    input_box = None
    input_scroll = None
    input_text_view = None
    input_delegate = None
    conversation_delegate = None
    markdown_display_map: MarkdownDisplayMap | None = None
    focused_block = -1

    @objc.python_method
    def configure(self, ui, tab_id: int, input_text: str) -> None:
        self.ui = ui
        self.tab_id = tab_id
        self.markdown_display_map = None
        self.focused_block = -1

        status_box = NSBox.alloc().initWithFrame_(((0, 0), (1, 1)))
        status_box.setBoxType_(NSBoxCustom)
        status_box.setBorderType_(NSNoBorder)
        status_box.setCornerRadius_(ui.text_corner_radius)
        status_box.setFillColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.8, 1.0)
        )
        self.addSubview_(status_box)
        self.status_box = status_box

        image = NSImageView.alloc().initWithFrame_(((0, 0), (1, 1)))
        image.setImage_(ui.logo)
        image.setImageScaling_(3)
        status_box.addSubview_(image)
        self.status_icon = image

        status_view = NSTextView.alloc().initWithFrame_(((0, 0), (1, 1)))
        status_view.setEditable_(False)
        status_view.setSelectable_(False)
        status_view.setDrawsBackground_(False)
        status_view.setTextContainerInset_((0.0, 0.0))
        status_box.addSubview_(status_view)
        self.status_view = status_view

        transcript_box = NSBox.alloc().initWithFrame_(((0, 0), (1, 1)))
        transcript_box.setBoxType_(NSBoxCustom)
        transcript_box.setBorderType_(NSNoBorder)
        transcript_box.setCornerRadius_(ui.text_corner_radius)
        transcript_box.setFillColor_(NSColor.whiteColor())
        transcript_box.setHidden_(True)
        self.addSubview_(transcript_box)
        self.transcript_box = transcript_box

        transcript_scroll = NSScrollView.alloc().initWithFrame_(
            ((0, 0), (1, 1))
        )
        transcript_scroll.setHasHorizontalScroller_(False)
        transcript_box.addSubview_(transcript_scroll)
        self.transcript_scroll = transcript_scroll

        transcript_view = ConversationTextView.alloc().initWithFrame_(
            ((0, 0), (1, 1))
        )
        transcript_view.ui = ui
        transcript_view.content_view = self
        transcript_view.setEditable_(False)
        transcript_view.setSelectable_(True)
        transcript_view.setDrawsBackground_(False)
        transcript_view.setLinkTextAttributes_({})
        transcript_view.setVerticallyResizable_(True)
        transcript_view.setHorizontallyResizable_(False)
        transcript_view.setMinSize_((0.0, 0.0))
        transcript_view.setMaxSize_((1.0e7, 1.0e7))
        transcript_view.textContainer().setContainerSize_((1.0, 1.0e7))
        transcript_view.textContainer().setWidthTracksTextView_(True)
        transcript_view.textContainer().setLineFragmentPadding_(0)
        conversation_delegate = ConversationDelegate.alloc().init()
        conversation_delegate.ui = ui
        transcript_view.setDelegate_(conversation_delegate)
        transcript_scroll.setDocumentView_(transcript_view)
        self.transcript_view = transcript_view
        self.conversation_delegate = conversation_delegate

        input_box = NSBox.alloc().initWithFrame_(((0, 0), (1, 1)))
        input_box.setBoxType_(NSBoxCustom)
        input_box.setBorderType_(NSNoBorder)
        input_box.setCornerRadius_(ui.text_corner_radius)
        input_box.setFillColor_(NSColor.whiteColor())
        self.addSubview_(input_box)
        self.input_box = input_box

        input_scroll = NSScrollView.alloc().initWithFrame_(((0, 0), (1, 1)))
        input_scroll.setHasVerticalScroller_(False)
        input_box.addSubview_(input_scroll)
        self.input_scroll = input_scroll

        input_view = NSTextView.alloc().initWithFrame_(((0, 0), (1, 1)))
        input_view.setString_(input_text)
        input_view.setFont_(NSFont.systemFontOfSize_(FONT_SIZE))
        input_view.setDrawsBackground_(False)
        input_view.setAutomaticQuoteSubstitutionEnabled_(False)
        input_view.setAutomaticDashSubstitutionEnabled_(False)
        input_view.setSelectedRange_((len(input_text), 0))
        input_delegate = InputDelegate.alloc().initWithUI_textView_(ui, input_view)
        input_scroll.setDocumentView_(input_view)
        self.input_text_view = input_view
        self.input_delegate = input_delegate

    @objc.python_method
    def set_status(self, agent: Agent) -> None:
        snapshot = agent.usage.snapshot()
        model = display_model_name(agent.model_name)
        line1 = f"{model} / ${snapshot.cost:.2f}"
        line2 = (
            f"Input: {snapshot.input_tokens:,} / "
            f"Cached: {snapshot.cached_input_tokens:,}"
        )
        line3 = (
            f"Writes: {snapshot.cache_write_tokens:,} / "
            f"Output: {snapshot.output_tokens:,}"
        )
        status = f"{line1}\n{line2}\n{line3}"
        self.status_view.setString_(status)

        paragraph = NSMutableParagraphStyle.alloc().init()
        paragraph.setAlignment_(2)
        first_line_attributes = {
            NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
            NSForegroundColorAttributeName: (
                NSColor.colorWithCalibratedWhite_alpha_(0.45, 1.0)
            ),
            NSParagraphStyleAttributeName: paragraph,
        }
        detail_attributes = {
            NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
            NSForegroundColorAttributeName: (
                NSColor.colorWithCalibratedWhite_alpha_(0.6, 1.0)
            ),
            NSParagraphStyleAttributeName: paragraph,
        }
        attributed = NSMutableAttributedString.alloc().initWithString_(status)
        attributed.addAttributes_range_(
            first_line_attributes,
            (0, len(line1)),
        )
        attributed.addAttributes_range_(
            detail_attributes,
            (len(line1), len(status) - len(line1)),
        )
        self.status_view.textStorage().setAttributedString_(attributed)

    @objc.python_method
    def set_transcript(
        self,
        cocoa_text,
        markdown_display_map: MarkdownDisplayMap,
    ) -> None:
        selected = self.transcript_view.selectedRange()
        clip = self.transcript_scroll.contentView()
        origin = clip.bounds().origin
        document_height = self.transcript_view.frame().size.height
        visible_height = clip.bounds().size.height
        at_bottom = origin.y + visible_height >= document_height - 2

        self.transcript_view.textStorage().setAttributedString_(cocoa_text)
        length = self.transcript_view.textStorage().length()
        location = min(selected.location, length)
        selection_length = min(selected.length, length - location)
        self.transcript_view.setSelectedRange_((location, selection_length))
        self.markdown_display_map = markdown_display_map
        self._saved_scroll_origin = origin
        self._scroll_to_end = at_bottom and selected.length == 0

    @objc.python_method
    def layout_content(
        self,
        *,
        root_size,
        top_y: float,
        main_y: float,
        main_height: float,
        has_content: bool,
    ) -> None:
        ui = self.ui
        self.setFrame_(((0, 0), root_size))
        self.status_box.setFrame_(
            (
                (ui.content_x, top_y),
                (ui.content_width, ui.top_bar_height),
            )
        )
        icon_y = int((ui.top_bar_height - ui.icon_width) / 2) - 5
        self.status_icon.setFrame_(
            ((0, icon_y), (ui.icon_width, ui.icon_width))
        )
        text_width = 240
        self.status_view.setFrame_(
            (
                (ui.content_width - text_width - 8, icon_y),
                (text_width, ui.top_bar_height - icon_y - 10),
            )
        )

        self.input_box.setFrame_(
            (
                (ui.content_x, ui.padding),
                (ui.content_width, ui.input_height),
            )
        )
        input_size = (
            ui.content_width - 2 * ui.text_corner_radius,
            ui.input_height - 2 * ui.text_corner_radius,
        )
        self.input_scroll.setFrame_(
            ((ui.textbox_x_fudge, ui.textbox_y_fudge), input_size)
        )
        self.input_text_view.setFrame_(((0, 0), input_size))

        self.transcript_box.setHidden_(not has_content)
        if not has_content:
            return
        self.transcript_box.setFrame_(
            ((ui.content_x, main_y), (ui.content_width, main_height))
        )
        scroll_size = (
            ui.content_width - 2 * ui.text_corner_radius,
            main_height - 2 * ui.text_corner_radius,
        )
        # Match input: inset the scroll view inside the rounded box so glyphs are
        # not clipped by the corner radius. Keep the document view at (0, 0).
        self.transcript_scroll.setFrame_(
            ((ui.textbox_x_fudge, ui.textbox_y_fudge), scroll_size)
        )
        self.transcript_scroll.setHasVerticalScroller_(
            main_height >= NSScreen.mainScreen().frame().size.height * 0.64
        )
        if hasattr(self.transcript_scroll, "tile"):
            self.transcript_scroll.tile()
        clip_size = self.transcript_scroll.contentView().bounds().size
        # Prefer the post-tile clip width (accounts for the scroller). Fall back
        # to scroll_size when clip.width is briefly 0 after hide/show + resize.
        clip_width = float(clip_size.width)
        if clip_width <= 1.0:
            clip_width = float(scroll_size[0])
        transcript_width = max(0.0, clip_width - ui.text_right_inset)
        text_container = self.transcript_view.textContainer()
        text_container.setContainerSize_((transcript_width, 1.0e7))
        self.transcript_view.setFrame_(
            ((0.0, 0.0), (transcript_width, max(1.0, float(clip_size.height))))
        )
        layout_manager = self.transcript_view.layoutManager()
        layout_manager.ensureLayoutForTextContainer_(text_container)
        used_height = float(
            layout_manager.usedRectForTextContainer_(text_container).size.height
        )
        transcript_height = max(
            float(clip_size.height),
            used_height,
            main_height - 2 * ui.text_corner_radius - ui.textbox_y_fudge,
        )
        self.transcript_view.setFrame_(
            ((0.0, 0.0), (transcript_width, transcript_height))
        )
        self.transcript_view.setNeedsDisplay_(True)
        if getattr(self, "_scroll_to_end", True):
            self.transcript_view.scrollRangeToVisible_(
                (self.transcript_view.textStorage().length(), 0)
            )
        else:
            clip = self.transcript_scroll.contentView()
            # Restore vertical position only; horizontal origin must stay 0 now
            # that the document view is pinned at (0, 0).
            saved = self._saved_scroll_origin
            clip.scrollToPoint_((0.0, float(saved.y)))
            self.transcript_scroll.reflectScrolledClipView_(clip)

    @objc.python_method
    def input_text(self) -> str:
        return str(self.input_text_view.string())

    @objc.python_method
    def clear_input(self) -> None:
        self.input_text_view.setString_("")

    @objc.python_method
    def clear_block_focus(self) -> None:
        self.focused_block = -1
        storage = self.transcript_view.textStorage()
        storage.removeAttribute_range_(
            NSBackgroundColorAttributeName,
            (0, storage.length()),
        )

class MainThreadBridge(NSObject):
    ui = None

    def pollSignals_(self, _timer):
        pass

    def repaint_(self, value):
        if self.ui is not None:
            tab_id = None if value is None else int(value)
            self.ui._main_thread_update(tab_id)

    def captureAndQuit_(self, path):
        from macagentic.ui.screenshot import capture_window_by_title

        self.ui._render_window()
        capture_window_by_title("macAgentic", str(path))
        NSApp().terminate_(None)

    def captureFromTimer_(self, timer):
        self.captureAndQuit_(timer.userInfo())


class AppDelegate(NSObject):
    ui = None

    def applicationShouldHandleReopen_hasVisibleWindows_(
        self,
        _application,
        _has_visible_windows,
    ):
        if self.ui is not None and not self.ui.window_is_visible():
            self.ui.hotkey_pressed()
        return True

    def applicationWillTerminate_(self, _notification):
        if self.ui is not None:
            self.ui.save_session()

    def selectModelTier_(self, sender):
        if self.ui is None:
            return
        tier = str(sender.representedObject())
        self.ui.set_active_model_tier(tier)


class UITab:
    def __init__(
        self,
        tab_id: int,
        agent: Agent,
        *,
        title: str = "New Agent",
        input_text: str = "",
    ) -> None:
        self.id = tab_id
        self.agent = agent
        self.title = title
        self.input_text = input_text
        self.tool_call_descriptions: dict[str, str] = {}
        self.display_event_index = 0
        self.math_bitmap_cache = MathBitmapCache()
        self.expanded_block_ids: set[str] = set()
        self.tab_bar_item: TabBarItemView | None = None
        self.content_view: TabContentView | None = None
        self.thread: threading.Thread | None = None
        self.requests: queue.Queue[str] = queue.Queue()

    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class MacAgenticUI:
    """A passive Cocoa renderer over each tab's in-memory transcript."""

    tabs: list[UITab]
    active_index: int
    window: NSWindow | None
    renderer: MarkdownRenderer
    bridge: MainThreadBridge
    update_queue: queue.Queue[UIUpdate]

    padding = 4
    top_bar_height = 48
    tab_bar_height = 24
    content_width = 640
    input_height = 90
    window_corner_radius = 12.0
    text_corner_radius = 8.0
    text_right_inset = 4.0
    fudge = 1
    icon_width = 38
    window_width = content_width + padding * 2
    content_x = padding + fudge
    padding_internal_fudge = 5
    textbox_x_fudge = 3
    textbox_y_fudge = 3

    def __init__(
        self,
        agent: Agent,
        *,
        tabs: list[UITab] | None = None,
        active_index: int = 0,
    ) -> None:
        self.window = None
        self.window_content = None
        self.root_view = None
        self.tab_bar_container = None
        self.tab_content_container = None
        self.tab_separators = []
        self.renderer = MarkdownRenderer()
        self.tabs = (
            tabs if tabs is not None else [UITab(agent.id, agent)]
        )
        for tab in self.tabs:
            tab.agent.ui = self
        self.active_index = active_index
        self.update_queue: queue.Queue[UIUpdate] = queue.Queue()
        self._rendering = False
        self._render_pending = False

        self.bridge = MainThreadBridge.alloc().init()
        self.bridge.ui = self
        self.logo = NSImage.alloc().initByReferencingFile_(
            str(_ASSETS / "llama.png")
        )
        self.dock_icon = NSImage.alloc().initByReferencingFile_(
            str(_ASSETS / "icon.png")
        )
        self.model_icons = {
            tier: _load_template_image(filename)
            for tier, filename in _MODEL_TIER_ICONS.items()
        }
        self.model_menu_items: dict[str, NSMenuItem] = {}

    @property
    def active_tab(self) -> UITab:
        return self.tabs[self.active_index]

    @property
    def active_content_view(self) -> TabContentView | None:
        return self.active_tab.content_view if self.tabs else None

    @property
    def input_field(self) -> NSTextView | None:
        content = self.active_content_view
        return content.input_text_view if content is not None else None

    @property
    def text_view(self) -> ConversationTextView | None:
        content = self.active_content_view
        return content.transcript_view if content is not None else None

    @property
    def top_bar_text_view(self) -> NSTextView | None:
        content = self.active_content_view
        return content.status_view if content is not None else None

    @property
    def input_delegate(self) -> InputDelegate | None:
        content = self.active_content_view
        return content.input_delegate if content is not None else None

    @property
    def conversation_delegate(self) -> ConversationDelegate | None:
        content = self.active_content_view
        return content.conversation_delegate if content is not None else None

    def start(self, *, dont_run_app: bool = False) -> None:
        global _hotkey_ui

        _hotkey_ui = self
        cocoa_app = NSApplication.sharedApplication()
        cocoa_app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self.app_delegate = AppDelegate.alloc().init()
        self.app_delegate.ui = self
        cocoa_app.setDelegate_(self.app_delegate)
        self._install_menu()
        if (
            self.dock_icon.size().width > 0
            and self.dock_icon.size().height > 0
        ):
            cocoa_app.setApplicationIconImage_(self.dock_icon)
        signal.signal(signal.SIGINT, self._handle_console_interrupt)
        self._signal_timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.1,
                self.bridge,
                "pollSignals:",
                None,
                True,
            )
        )
        if not dont_run_app:
            cocoa_app.run()

    def new_tab(self) -> None:
        if self.tabs:
            self._sync_input_text(self.active_tab)
        agent = app.create_agent(render_markdown=True)
        agent.ui = self
        self.tabs.append(UITab(agent.id, agent))
        self.active_index = len(self.tabs) - 1
        if self.window_is_visible():
            self._process_new_display_events(self.active_tab)
            self._render_window()

    def close_tab(self, index: int) -> None:
        if not 0 <= index < len(self.tabs):
            return
        active_id = self.active_tab.id
        tab = self.tabs[index]
        self._sync_input_text(tab)
        tab.agent.interrupt()
        save_history(
            app.workspace,
            render_history(tab.agent.conversation_log.snapshot()),
        )
        if tab.content_view is not None:
            tab.content_view.removeFromSuperview()
        if tab.tab_bar_item is not None:
            tab.tab_bar_item.removeFromSuperview()
        self.tabs.pop(index)
        if not self.tabs:
            agent = app.create_agent(render_markdown=True)
            agent.ui = self
            self.tabs.append(UITab(agent.id, agent))
            self.active_index = 0
        elif tab.id == active_id:
            self.active_index = min(index, len(self.tabs) - 1)
        else:
            self.active_index = next(
                i for i, candidate in enumerate(self.tabs)
                if candidate.id == active_id
            )
        if self.window_is_visible():
            self._process_new_display_events(self.active_tab)
            self._render_window()

    def switch_tab(self, index: int) -> None:
        if not 0 <= index < len(self.tabs):
            return
        self._sync_input_text(self.active_tab)
        self.active_index = index
        self._process_new_display_events(self.active_tab)
        if self.window_is_visible():
            self._render_window()

    def cycle_tab(self, delta: int = 1) -> None:
        if len(self.tabs) < 2:
            return
        self.switch_tab((self.active_index + delta) % len(self.tabs))

    def switch_tab_by_id(self, tab_id: int) -> None:
        index = self._index_for_tab_id(tab_id)
        if index is not None:
            self.switch_tab(index)

    def close_tab_by_id(self, tab_id: int) -> None:
        index = self._index_for_tab_id(tab_id)
        if index is not None:
            self.close_tab(index)

    def set_active_model_tier(self, tier: str) -> None:
        self.active_tab.agent.set_model_tier(tier)
        self._update_model_menu_state()
        if self.window_is_visible():
            self._render_window()

    def submit(self, request: str) -> None:
        request = request.strip()
        if not request:
            return
        tab = self.active_tab
        self._clear_input()
        if tab.title == "New Agent":
            tab.title = " ".join(request.split())[:28]
            tab_id = tab.id
            request_fast_text(
                system_prompt=(
                    "Write a concise 2-4 word title for this coding task. "
                    "Return only the title, without quotes or punctuation."
                ),
                user_prompt=request,
                on_result=lambda result: self.post_update(
                    SetTabTitle(tab_id, _clean_title(result))
                ),
            )

        tab.requests.put(request)
        if not tab.running():
            self._start_tab_thread(tab)
        self.update()

    def interrupt_active(self, replacement: str = "") -> None:
        tab = self.active_tab
        tab.agent.interrupt()
        if replacement:
            tab.requests.put(replacement)
        self._clear_input()
        self.update()

    def _handle_console_interrupt(self, _signum, _frame) -> None:
        if self.tabs and self.active_tab.running():
            self.active_tab.agent.interrupt()
            print("\nInterrupted.")
            self.update()
            return
        NSApp().terminate_(None)

    def update(self) -> None:
        if not self.tabs:
            return
        if NSThread.isMainThread():
            tab = self.active_tab
        else:
            caller = threading.current_thread()
            tab = next(
                (tab for tab in self.tabs if tab.thread is caller),
                None,
            )
        if tab is None:
            return
        self._schedule_main_thread_update(tab.id)

    def post_update(self, event: UIUpdate) -> None:
        self.update_queue.put(event)
        self._schedule_main_thread_update(None)

    def _schedule_main_thread_update(self, tab_id: int | None) -> None:
        if NSThread.isMainThread():
            self._main_thread_update(tab_id)
        else:
            self.bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                "repaint:",
                tab_id,
                False,
            )

    def _start_tab_thread(self, tab: UITab) -> None:
        request = tab.requests.get_nowait()
        tab_id = tab.id
        agent = tab.agent
        updates = self.update_queue
        bridge = self.bridge

        def run() -> None:
            try:
                agent.run_turn(request)
            finally:
                updates.put(
                    AgentThreadCompleted(tab_id, threading.get_ident())
                )
                bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "repaint:", None, False
                )

        tab.thread = threading.Thread(
            target=run,
            name=f"macagentic-tab-{tab.id}",
            daemon=True,
        )
        tab.thread.start()

    def _main_thread_update(self, updated_tab_id: int | None = None) -> None:
        render_active = False
        refresh_titles: set[int] = set()
        while True:
            try:
                event = self.update_queue.get_nowait()
            except queue.Empty:
                break
            tab = self._tab_with_id(event.tab_id)
            if tab is None:
                continue
            if isinstance(event, SetTabTitle):
                tab.title = event.title
                refresh_titles.add(tab.id)
            elif isinstance(event, SetToolCallDescription):
                tab.tool_call_descriptions[event.tool_call_id] = event.text
                render_active = render_active or tab is self.active_tab
            elif (
                isinstance(event, AgentThreadCompleted)
                and tab.thread is not None
                and tab.thread.ident == event.thread_id
            ):
                tab.thread = None
                if not tab.requests.empty():
                    self._start_tab_thread(tab)
                elif app.screenshot_path is not None:
                    path = app.screenshot_path
                    app.screenshot_path = None
                    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                        1.0,
                        self.bridge,
                        "captureFromTimer:",
                        str(path),
                        False,
                    )
                refresh_titles.add(tab.id)

        updated_tab = (
            self._tab_with_id(updated_tab_id)
            if updated_tab_id is not None
            else None
        )
        if updated_tab is self.active_tab:
            self._process_new_display_events(updated_tab)
            render_active = True

        if self.window_is_visible() and render_active:
            self._render_window()
        elif self.window is not None:
            for tab_id in refresh_titles:
                self._refresh_tab_title(tab_id)

    def _process_new_display_events(self, tab: UITab) -> None:
        events = tab.agent.conversation_log.snapshot()
        new_events = events[tab.display_event_index :]
        tab.display_event_index = len(events)
        user_request = next(
            (
                str(event.payload.get("content", ""))
                for event in reversed(events)
                if event.kind == "user_input"
            ),
            "",
        )
        for event in new_events:
            if event.kind != "message":
                continue
            for action in event.payload.get("extra", {}).get("actions", []):
                call_id = str(action.get("tool_call_id", ""))
                if not call_id or call_id in tab.tool_call_descriptions:
                    continue
                tab.tool_call_descriptions[call_id] = "Running command"
                command = str(action.get("command", ""))
                tab_id = tab.id
                request_fast_text(
                    system_prompt=(
                        "Write a concise, user-facing progress update describing "
                        "what the command is accomplishing, not how it works. "
                        "Include the source and specific subject when available. "
                        "Use a 4-9 word gerund phrase. Return only the update with "
                        "no punctuation."
                    ),
                    user_prompt=(
                        f"User request:\n{user_request}\n\n"
                        f"Command:\n{command}"
                    ),
                    on_result=lambda result, tid=tab_id, cid=call_id: self.post_update(
                        SetToolCallDescription(
                            tid,
                            cid,
                            _clean_description(result),
                        )
                    ),
                )

    def _tab_with_id(self, tab_id: int) -> UITab | None:
        return next((tab for tab in self.tabs if tab.id == tab_id), None)

    def _window_backing_scale(self) -> float:
        if self.window is not None:
            screen = self.window.screen()
            if screen is not None:
                return float(screen.backingScaleFactor())
        screen = NSScreen.mainScreen()
        if screen is None:
            return 2.0
        return max(float(screen.backingScaleFactor()), 2.0)

    def _render_window(self, *, activate: bool = False) -> None:
        if not self.tabs:
            return
        if self._rendering:
            self._render_pending = True
            return
        self._rendering = True
        try:
            self._render_window_body(activate=activate)
        finally:
            self._rendering = False
            if self._render_pending:
                self._render_pending = False
                self._render_window()

    def _activate_window(self) -> None:
        if self.window is None or self.input_field is None:
            return
        self.window.orderFrontRegardless()
        self.window.makeKeyWindow()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.window.makeFirstResponder_(self.input_field)

    def _render_window_body(self, *, activate: bool = False) -> None:
        if not self.tabs:
            return
        self._update_model_menu_state()
        tab = self.active_tab
        transcript = render_conversation(
            tab.agent.conversation_log.snapshot(),
            tool_call_descriptions=tab.tool_call_descriptions,
            show_tool_output=app.show_tool_output,
        )
        cocoa_text, markdown_display_map = self.renderer.render(
            transcript,
            NSColor.darkGrayColor(),
            expanded_block_ids=tab.expanded_block_ids,
            math_bitmap_cache=tab.math_bitmap_cache,
            scale_factor=self._window_backing_scale(),
        )
        content_height = self._measure(cocoa_text)
        screen = NSScreen.mainScreen().frame().size
        has_content = bool(transcript)
        max_window_height = int(screen.height * 0.9)
        total_padding = self.padding * 4
        if has_content:
            optimal_main_height = content_height + self.text_corner_radius * 2
            total_height = (
                self.top_bar_height
                + self.tab_bar_height
                + optimal_main_height
                + self.input_height
                + total_padding
                + self.padding_internal_fudge
            )
            window_height = min(total_height, max_window_height)
            main_height = window_height - (
                self.top_bar_height
                + self.tab_bar_height
                + self.input_height
                + total_padding
                + self.padding_internal_fudge
            )
        else:
            main_height = 0
            window_height = (
                self.top_bar_height
                + self.tab_bar_height
                + self.input_height
                + self.padding * 3
            )

        frame = (
            (
                (screen.width - self.window_width) / 2
                - self.window_corner_radius,
                (screen.height - window_height) / 2
                - self.window_corner_radius,
            ),
            (
                self.window_width + 2 * self.window_corner_radius,
                window_height + 2 * self.window_corner_radius,
            ),
        )
        self._ensure_window_shell(frame)

        input_y = self.padding
        if has_content:
            main_y = (
                input_y
                + self.input_height
                + self.padding
                + self.padding_internal_fudge
            )
            tab_y = main_y + main_height
        else:
            main_y = 0
            tab_y = input_y + self.input_height
        top_y = tab_y + self.tab_bar_height + self.padding
        root_size = (
            self.window_width + self.window_corner_radius,
            window_height + self.window_corner_radius,
        )
        self.window_content.setFrame_(((0, 0), frame[1]))
        self.root_view.setFrame_(((0, 0), root_size))
        self.tab_content_container.setFrame_(((0, 0), root_size))
        content_view = self._ensure_tab_content_view(tab)
        # Unhide before layout: NSScrollView clip bounds / tile are unreliable
        # while the content view is still hidden after a window resize.
        for candidate in self.tabs:
            if candidate.content_view is not None:
                candidate.content_view.setHidden_(candidate is not tab)
        content_view.set_status(tab.agent)
        content_view.set_transcript(cocoa_text, markdown_display_map)
        content_view.layout_content(
            root_size=root_size,
            top_y=top_y,
            main_y=main_y,
            main_height=main_height,
            has_content=has_content,
        )
        self.tab_bar_container.setFrame_(
            (
                (self.content_x, tab_y),
                (self.content_width, self.tab_bar_height),
            )
        )
        self._sync_tab_bar()
        self.window.display()
        if not self.window.isVisible():
            self.window.orderFrontRegardless()
        if activate:
            self._activate_window()
        elif self.window.isKeyWindow() and self.input_field is not None:
            self.window.makeFirstResponder_(self.input_field)

    def _ensure_window_shell(self, frame) -> None:
        if self.window is None:
            self.window = QuickPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                frame,
                NSBorderlessWindowMask,
                NSBackingStoreBuffered,
                False,
            )
            self.window.ui = self
            self.window.setTitle_("macAgentic")
            self.window.setLevel_(3)
            self.window.setBackgroundColor_(NSColor.clearColor())

            content = NSView.alloc().initWithFrame_(((0, 0), frame[1]))
            self.window.setContentView_(content)
            self.window_content = content

            root = NSBox.alloc().initWithFrame_(((0, 0), frame[1]))
            root.setBoxType_(NSBoxCustom)
            root.setBorderType_(NSNoBorder)
            root.setCornerRadius_(self.window_corner_radius)
            root.setFillColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.9, 1.0)
            )
            content.addSubview_(root)
            self.root_view = root

            tab_content = NSView.alloc().initWithFrame_(((0, 0), frame[1]))
            root.addSubview_(tab_content)
            self.tab_content_container = tab_content

            tab_bar = NSView.alloc().initWithFrame_(((0, 0), (1, 1)))
            root.addSubview_(tab_bar)
            self.tab_bar_container = tab_bar
        else:
            self.window.setFrame_display_(frame, True)

    def _ensure_tab_content_view(self, tab: UITab) -> TabContentView:
        if tab.content_view is None:
            view = TabContentView.alloc().initWithFrame_(((0, 0), (1, 1)))
            view.configure(self, tab.id, tab.input_text)
            self.tab_content_container.addSubview_(view)
            tab.content_view = view
        return tab.content_view

    def _ensure_tab_bar_item(self, tab: UITab) -> TabBarItemView:
        if tab.tab_bar_item is None:
            item = TabBarItemView.alloc().initWithFrame_(((0, 0), (1, 1)))
            item.configure(self, tab.id)
            self.tab_bar_container.addSubview_(item)
            tab.tab_bar_item = item
        return tab.tab_bar_item

    def _sync_tab_bar(self) -> None:
        for separator in self.tab_separators:
            separator.removeFromSuperview()
        self.tab_separators = []
        for tab in self.tabs:
            if tab.tab_bar_item is not None:
                tab.tab_bar_item.setHidden_(True)

        indices = self._visible_tab_indices()
        separator_width = 1
        separator_count = max(0, len(indices) - 1)
        usable_width = self.content_width - separator_count * separator_width
        tab_width = max(60, int(usable_width / max(1, len(indices))))
        pill_top_padding = 3
        tab_inner_height = self.tab_bar_height - pill_top_padding
        # Connect the active tab to the content box without painting over its
        # first line of text.
        overlap = self.padding
        x = 0
        for position, index in enumerate(indices):
            tab = self.tabs[index]
            is_last = position == len(indices) - 1
            current_width = self.content_width - x if is_last else tab_width
            item = self._ensure_tab_bar_item(tab)
            item.setFrame_(((x, 0), (current_width, tab_inner_height)))
            item.layout(current_width, tab_inner_height, overlap)
            item.set_title(tab.title, running=tab.running())
            item.set_active(index == self.active_index)
            item.setHidden_(False)
            x += current_width
            if not is_last:
                separator = NSBox.alloc().initWithFrame_(
                    ((x, 2), (separator_width, tab_inner_height - 4))
                )
                separator.setBoxType_(NSBoxCustom)
                separator.setBorderType_(NSNoBorder)
                separator.setFillColor_(
                    NSColor.colorWithCalibratedWhite_alpha_(0.65, 1.0)
                )
                self.tab_bar_container.addSubview_(separator)
                self.tab_separators.append(separator)
                x += separator_width

    def _refresh_tab_title(self, tab_id: int) -> None:
        tab = self._tab_with_id(tab_id)
        if tab is None or tab.tab_bar_item is None:
            return
        tab.tab_bar_item.set_title(tab.title, running=tab.running())

    def _measure(self, attributed) -> float:
        # Approximate the live transcript width: rounded-box inset, optional
        # scroller (~15pt when content is tall), and the right text inset.
        text_width = (
            self.content_width
            - 2 * self.text_corner_radius
            - self.text_right_inset
        )
        text = NSTextView.alloc().initWithFrame_(
            ((0, 0), (text_width, 10000))
        )
        text.setHorizontallyResizable_(False)
        text.textContainer().setContainerSize_((text_width, 10000))
        text.textContainer().setWidthTracksTextView_(True)
        text.textContainer().setLineFragmentPadding_(0)
        text.textStorage().setAttributedString_(attributed)
        layout = text.layoutManager()
        container = text.textContainer()
        layout.ensureLayoutForTextContainer_(container)
        return layout.usedRectForTextContainer_(container).size.height

    def _visible_tab_indices(self) -> list[int]:
        count = len(self.tabs)
        newest = list(range(max(0, count - 5), count))
        newest.reverse()
        if self.active_index in newest:
            return newest
        start = max(0, self.active_index - 2)
        end = min(count, start + 5)
        return list(reversed(range(max(0, end - 5), end)))

    def toggle_block(self, block_id: str) -> None:
        expanded = self.active_tab.expanded_block_ids
        if block_id in expanded:
            expanded.remove(block_id)
        else:
            expanded.add(block_id)
        self._render_window()

    def copy_block(self, block_id: str) -> None:
        content_view = self.active_content_view
        display_map = (
            content_view.markdown_display_map
            if content_view is not None
            else None
        )
        content = display_map.block_content(block_id) if display_map else None
        if content is None:
            return
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.declareTypes_owner_([NSStringPboardType], None)
        pasteboard.setString_forType_(content, NSStringPboardType)

    def focus_next_block(self, backwards: bool = False) -> bool:
        content_view = self.active_content_view
        display_map = (
            content_view.markdown_display_map
            if content_view is not None
            else None
        )
        if (
            content_view is None
            or display_map is None
            or not display_map.block_ranges
        ):
            return False
        step = -1 if backwards else 1
        content_view.focused_block = (
            content_view.focused_block + step
        ) % len(display_map.block_ranges)
        _, start, length = display_map.block_ranges[content_view.focused_block]
        storage = content_view.transcript_view.textStorage()
        storage.removeAttribute_range_(
            NSBackgroundColorAttributeName, (0, storage.length())
        )
        storage.addAttribute_value_range_(
            NSBackgroundColorAttributeName,
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.9, 0.9, 1.0, 1.0
            ),
            (start, length),
        )
        content_view.transcript_view.scrollRangeToVisible_((start, length))
        self.window.makeFirstResponder_(content_view.transcript_view)
        return True

    def copy_focused_block(self) -> None:
        content_view = self.active_content_view
        display_map = (
            content_view.markdown_display_map
            if content_view is not None
            else None
        )
        if (
            content_view is not None
            and display_map is not None
            and 0 <= content_view.focused_block < len(display_map.block_ranges)
        ):
            block_id, _, _ = display_map.block_ranges[
                content_view.focused_block
            ]
            self.copy_block(block_id)

    def exit_block_focus(self) -> None:
        if self.active_content_view is not None:
            self.active_content_view.clear_block_focus()

    def close_window(self) -> None:
        for tab in self.tabs:
            self._sync_input_text(tab)
        if self.window is not None:
            self.window.orderOut_(None)
        NSApplication.sharedApplication().hide_(None)

    def save_session(self) -> None:
        for tab in self.tabs:
            self._sync_input_text(tab)
        for tab in self.tabs:
            tab.agent.interrupt()
        for tab in self.tabs:
            if tab.thread is not None:
                tab.thread.join()
        write_session(
            SavedSession(
                workspace=str(app.workspace.resolve()),
                active_index=self.active_index,
                tabs=[
                    SavedTab(
                        id=tab.id,
                        title=tab.title,
                        input_text=tab.input_text,
                        messages=tab.agent.messages,
                        events=tab.agent.conversation_log.records(),
                    )
                    for tab in self.tabs
                ],
            )
        )

    def hotkey_pressed(self, *, activate: bool = True) -> None:
        if not self.window_is_visible():
            self._process_new_display_events(self.active_tab)
            self._render_window(activate=activate)
        else:
            self.close_window()

    def window_is_visible(self) -> bool:
        return self.window is not None and bool(self.window.isVisible())

    def _sync_input_text(self, tab: UITab) -> None:
        if tab.content_view is not None:
            tab.input_text = tab.content_view.input_text()

    def _clear_input(self) -> None:
        self.active_tab.input_text = ""
        if self.active_content_view is not None:
            self.active_content_view.clear_input()

    def _index_for_tab_id(self, tab_id: int) -> int | None:
        return next(
            (
                index
                for index, tab in enumerate(self.tabs)
                if tab.id == tab_id
            ),
            None,
        )

    def _update_model_menu_state(self) -> None:
        current = self.active_tab.agent.model_name if self.tabs else ""
        for tier, item in self.model_menu_items.items():
            preset = app.model_presets.get(tier)
            item.setState_(
                NSOnState if preset == current else NSOffState
            )

    def _install_menu(self) -> None:
        menu = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        app_menu = NSMenu.alloc().init()
        app_menu.addItem_(
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit macAgentic", "terminate:", "q"
            )
        )
        app_item.setSubmenu_(app_menu)
        menu.addItem_(app_item)

        edit_item = NSMenuItem.alloc().init()
        edit_menu = NSMenu.alloc().initWithTitle_("Edit")
        edit_menu.addItem_(
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Undo", "undo:", "z"
            )
        )
        redo = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Redo", "redo:", "Z"
        )
        redo.setKeyEquivalentModifierMask_(
            NSCommandKeyMask | NSShiftKeyMask
        )
        edit_menu.addItem_(redo)
        edit_menu.addItem_(NSMenuItem.separatorItem())
        for title, action, key in (
            ("Cut", "cut:", "x"),
            ("Copy", "copy:", "c"),
            ("Paste", "paste:", "v"),
            ("Select All", "selectAll:", "a"),
        ):
            edit_menu.addItem_(
                NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    title,
                    action,
                    key,
                )
            )
        edit_item.setSubmenu_(edit_menu)
        menu.addItem_(edit_item)

        model_item = NSMenuItem.alloc().init()
        model_menu = NSMenu.alloc().initWithTitle_("Model")
        self.model_menu_items = {}
        for index, tier in enumerate(MODEL_TIERS, start=1):
            preset = app.model_presets.get(tier, "")
            title = (
                f"{_MODEL_TIER_LABELS[tier]} – "
                f"{display_model_name(preset)}"
            )
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title,
                "selectModelTier:",
                str(index),
            )
            item.setTarget_(self.app_delegate)
            item.setRepresentedObject_(tier)
            item.setImage_(self.model_icons[tier])
            model_menu.addItem_(item)
            self.model_menu_items[tier] = item
        model_item.setSubmenu_(model_menu)
        menu.addItem_(model_item)
        self._update_model_menu_state()
        NSApplication.sharedApplication().setMainMenu_(menu)


def _clean_title(value: str) -> str:
    title = " ".join(value.splitlines()[0].split()).strip("\"'` .:;-")
    return title[:28] or "New Agent"


TOOL_UPDATE_MAX_LENGTH = 80


def _clean_description(value: str) -> str:
    description = " ".join(value.splitlines()[0].split()).strip("\"'` .:;-")
    return description[:TOOL_UPDATE_MAX_LENGTH] or "Running command"

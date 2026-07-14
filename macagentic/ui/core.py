from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import objc
from Cocoa import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSAttributedString,
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
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSNoBorder,
    NSObject,
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
    NSWorkspace,
    NSMutableAttributedString,
    NSMutableParagraphStyle,
)
from Foundation import NSTimer, NSURL
from quickmachotkey import mask, quickHotKey
from quickmachotkey.constants import kVK_Space, optionKey

from macagentic.agent import Control, Transcript
from macagentic.agent.skills import EMPTY_SKILL_CATALOG, SkillCatalog
from macagentic.agent.usage import UsageSnapshot, display_model_name
from macagentic.ui.markdown import FONT_SIZE, MarkdownRenderer


_hotkey_ui = None


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
        return objc.super(QuickPanel, self).performKeyEquivalent_(event)


class ClickableTab(NSView):
    ui = None
    index = -1

    def mouseDown_(self, _event):
        if self.ui is not None:
            self.ui.switch_tab(self.index)


class CloseTab(NSView):
    ui = None
    index = -1

    def mouseDown_(self, _event):
        if self.ui is not None:
            self.ui.close_tab(self.index)


class ConversationTextView(NSTextView):
    ui = None

    def keyDown_(self, event):
        characters = str(event.charactersIgnoringModifiers() or "")
        flags = event.modifierFlags()
        if characters == "\t":
            self.ui.focus_next_block(backwards=bool(flags & NSShiftKeyMask))
            return
        if characters in {"\r", "\n"}:
            self.ui.copy_focused_block()
            return
        if event.keyCode() == 53:
            self.ui.exit_block_focus()
            return
        objc.super(ConversationTextView, self).keyDown_(event)


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
                    self.ui.interrupt_active(submit_text=text)
                else:
                    self.ui.submit(text)
                return True
            if selector == "insertTab:":
                if self.ui.focus_next_block():
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


@dataclass
class InteractionRequest:
    prompt: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: object = None


class MainThreadBridge(NSObject):
    ui = None

    def pollSignals_(self, _timer):
        pass

    def repaint_(self, _value):
        if self.ui is not None:
            self.ui.update_window()

    def permission_(self, request):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Permission required")
        alert.setInformativeText_(request.prompt)
        alert.addButtonWithTitle_("Allow")
        alert.addButtonWithTitle_("Deny")
        request.answer = alert.runModal() == NSAlertFirstButtonReturn
        request.event.set()

    def clarification_(self, request):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Agent needs clarification")
        alert.setInformativeText_(request.prompt)
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 360, 24))
        alert.setAccessoryView_(field)
        alert.addButtonWithTitle_("Submit")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == NSAlertFirstButtonReturn:
            request.answer = str(field.stringValue())
        request.event.set()

    def captureAndQuit_(self, path):
        from macagentic.ui.screenshot import capture_window_by_title

        self.ui.update_window()
        capture_window_by_title("macAgentic", str(path))
        NSApp().terminate_(None)


class AppDelegate(NSObject):
    ui = None

    def applicationShouldHandleReopen_hasVisibleWindows_(
        self,
        _application,
        _has_visible_windows,
    ):
        if self.ui is not None and self.ui.window is None:
            self.ui.update_window()
        return True


@dataclass
class UITab:
    control: Control
    title: str = "New Agent"
    draft: str = ""
    thread: threading.Thread | None = None
    pending: list[str] = field(default_factory=list)

    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class MacAgenticUI:
    """A passive Cocoa renderer over each tab's in-memory transcript."""

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
        workspace: Path,
        *,
        model_name: str | None = None,
        initial_task: str | None = None,
        screenshot_path: Path | None = None,
        custom_instructions: str | None = None,
        tool_instructions: str | None = None,
        skill_catalog: SkillCatalog | None = None,
        show_tool_output: bool = False,
    ) -> None:
        self.workspace = workspace
        self.model_name = model_name
        self.initial_task = initial_task
        self.screenshot_path = screenshot_path
        self.custom_instructions = custom_instructions
        self.tool_instructions = tool_instructions
        self.skill_catalog = skill_catalog or EMPTY_SKILL_CATALOG
        self.show_tool_output = show_tool_output
        self.app = None
        self.window = None
        self.input_field = None
        self.text_view = None
        self.renderer = MarkdownRenderer()
        self.tabs: list[UITab] = []
        self.active_index = -1
        self.focused_block = -1
        self._tabs_lock = threading.RLock()

        self.bridge = MainThreadBridge.alloc().init()
        self.bridge.ui = self
        self.logo = NSImage.alloc().initByReferencingFile_(
            str(Path(__file__).parent / "assets" / "llama.png")
        )
        self.dock_icon = NSImage.alloc().initByReferencingFile_(
            str(Path(__file__).parent / "assets" / "icon.png")
        )

    @property
    def active_tab(self) -> UITab:
        return self.tabs[self.active_index]

    def start(self, *, dont_run_app: bool = False) -> None:
        global _hotkey_ui

        _hotkey_ui = self
        self.app = NSApplication.sharedApplication()
        self.app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self.app_delegate = AppDelegate.alloc().init()
        self.app_delegate.ui = self
        self.app.setDelegate_(self.app_delegate)
        self._install_menu()
        if (
            self.dock_icon.size().width > 0
            and self.dock_icon.size().height > 0
        ):
            self.app.setApplicationIconImage_(self.dock_icon)
        self.new_tab()
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
        self.update_window()
        if self.initial_task:
            self.submit(self.initial_task)
        if not dont_run_app:
            self.app.run()

    def new_tab(self) -> None:
        transcript = Transcript(on_change=self.request_update)
        control = Control(
            self.workspace,
            model_name=self.model_name,
            transcript=transcript,
            ask_permission=self.ask_permission,
            ask_clarification=self.ask_clarification,
            on_usage=self._usage_changed,
            custom_instructions=self.custom_instructions,
            tool_instructions=self.tool_instructions,
            skill_catalog=self.skill_catalog,
            show_tool_output=self.show_tool_output,
        )
        with self._tabs_lock:
            self.tabs.append(UITab(control=control))
            self.active_index = len(self.tabs) - 1
        if self.window is not None:
            self.update_window()

    def close_tab(self, index: int) -> None:
        with self._tabs_lock:
            if not 0 <= index < len(self.tabs):
                return
            self.tabs[index].control.interrupt()
            self.tabs.pop(index)
            if not self.tabs:
                self.active_index = -1
                self.new_tab()
                return
            self.active_index = min(self.active_index, len(self.tabs) - 1)
        self.update_window()

    def switch_tab(self, index: int) -> None:
        if not 0 <= index < len(self.tabs):
            return
        self._save_draft()
        self.active_index = index
        self.focused_block = -1
        self.update_window()

    def submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        tab = self.active_tab
        self._clear_input()
        if tab.title == "New Agent":
            tab.title = " ".join(text.split())[:28]

        with self._tabs_lock:
            if tab.running():
                tab.pending.append(text)
                return

            def run() -> None:
                next_text = text
                try:
                    while next_text:
                        tab.control.run_turn(next_text)
                        with self._tabs_lock:
                            next_text = (
                                tab.pending.pop(0) if tab.pending else ""
                            )
                finally:
                    tab.thread = None
                    self.request_update()
                    if self.screenshot_path is not None:
                        path = self.screenshot_path
                        self.screenshot_path = None
                        time.sleep(1.0)
                        self.bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                            "captureAndQuit:", path, False
                        )

            tab.thread = threading.Thread(
                target=run,
                name=f"macagentic-tab-{self.active_index}",
                daemon=True,
            )
            tab.thread.start()
        self.request_update()

    def _usage_changed(self, _usage: UsageSnapshot) -> None:
        self.request_update()

    def interrupt_active(self, submit_text: str = "") -> None:
        tab = self.active_tab
        tab.control.interrupt()
        if submit_text:
            with self._tabs_lock:
                tab.pending.insert(0, submit_text)
        self._clear_input()
        self.request_update()

    def _handle_console_interrupt(self, _signum, _frame) -> None:
        if self.tabs and self.active_tab.running():
            self.active_tab.control.interrupt()
            print("\nInterrupted.")
            self.request_update()
            return
        NSApp().terminate_(None)

    def request_update(self) -> None:
        if self.window is None:
            return
        if NSThread.isMainThread():
            self.update_window()
        else:
            self.bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                "repaint:", None, False
            )

    def ask_permission(self, prompt: str) -> bool:
        request = InteractionRequest(prompt)
        self.bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
            "permission:", request, False
        )
        request.event.wait()
        return bool(request.answer)

    def ask_clarification(self, prompt: str) -> str | None:
        request = InteractionRequest(prompt)
        self.bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
            "clarification:", request, False
        )
        request.event.wait()
        return request.answer if isinstance(request.answer, str) else None

    def update_window(self) -> None:
        if not self.tabs:
            return
        draft = self._current_input()
        if self.window is not None:
            self.active_tab.draft = draft

        transcript = self.active_tab.control.transcript.getvalue()
        rendered = self.renderer.render(transcript, NSColor.darkGrayColor())
        content_height = self._measure(rendered)
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
        else:
            self.window.setFrame_display_(frame, True)

        content = NSView.alloc().initWithFrame_(
            ((0, 0), frame[1])
        )
        self.window.setContentView_(content)
        root = NSBox.alloc().initWithFrame_(
            (
                (0, 0),
                (
                    self.window_width + self.window_corner_radius,
                    window_height + self.window_corner_radius,
                ),
            )
        )
        root.setBoxType_(NSBoxCustom)
        root.setBorderType_(NSNoBorder)
        root.setCornerRadius_(self.window_corner_radius)
        root.setFillColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.9, 1.0)
        )
        content.addSubview_(root)

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

        self._render_top_bar(root, top_y)
        self._render_tabs(root, tab_y)
        if has_content:
            self._render_transcript(root, main_y, main_height, rendered)
        else:
            self.text_view = None
        self._render_input(root, input_y, self.active_tab.draft)

        self.window.display()
        self.window.orderFrontRegardless()
        self.window.makeKeyWindow()
        self.app.activateIgnoringOtherApps_(True)
        self.window.makeFirstResponder_(self.input_field)

    def _render_top_bar(self, root, y: float) -> None:
        bar = NSBox.alloc().initWithFrame_(
            ((self.content_x, y), (self.content_width, self.top_bar_height))
        )
        bar.setBoxType_(NSBoxCustom)
        bar.setBorderType_(NSNoBorder)
        bar.setCornerRadius_(self.text_corner_radius)
        bar.setFillColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.8, 1.0)
        )
        root.addSubview_(bar)

        icon_y = int((self.top_bar_height - self.icon_width) / 2) - 5
        image = NSImageView.alloc().initWithFrame_(
            ((0, icon_y), (self.icon_width, self.icon_width))
        )
        image.setImage_(self.logo)
        image.setImageScaling_(3)
        bar.addSubview_(image)

        snapshot = self.active_tab.control.usage.snapshot()
        model = display_model_name(
            self.model_name or "openai/gpt-5-mini"
        )
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
        text_field_width = 240
        text_y = icon_y
        text_height = self.top_bar_height - text_y - 10
        label = NSTextView.alloc().initWithFrame_(
            (
                (self.content_width - text_field_width - 8, text_y),
                (text_field_width, text_height),
            )
        )
        label.setString_(status)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setDrawsBackground_(False)
        label.setTextContainerInset_((0.0, 0.0))

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
        attributed = (
            NSMutableAttributedString.alloc().initWithString_(status)
        )
        attributed.addAttributes_range_(
            first_line_attributes,
            (0, len(line1)),
        )
        attributed.addAttributes_range_(
            detail_attributes,
            (len(line1), len(status) - len(line1)),
        )
        label.textStorage().setAttributedString_(attributed)
        bar.addSubview_(label)
        self.top_bar_text_view = label

    def _render_tabs(self, root, y: float) -> None:
        container = NSView.alloc().initWithFrame_(
            ((self.content_x, y), (self.content_width, self.tab_bar_height))
        )
        root.addSubview_(container)
        indices = self._visible_tab_indices()
        separator_width = 1
        separator_count = max(0, len(indices) - 1)
        usable_width = self.content_width - separator_count * separator_width
        tab_width = max(60, int(usable_width / max(1, len(indices))))
        pill_top_padding = 3
        tab_inner_height = self.tab_bar_height - pill_top_padding
        overlap = int(self.window_corner_radius) + 4
        x = 0
        for position, index in enumerate(indices):
            tab = self.tabs[index]
            active = index == self.active_index
            is_last = position == len(indices) - 1
            current_width = self.content_width - x if is_last else tab_width
            view = ClickableTab.alloc().initWithFrame_(
                ((x, 0), (current_width, tab_inner_height))
            )
            view.ui = self
            view.index = index
            container.addSubview_(view)

            if active:
                background = NSBox.alloc().initWithFrame_(
                    (
                        (0, -overlap),
                        (current_width, tab_inner_height + overlap),
                    )
                )
                background.setBoxType_(NSBoxCustom)
                background.setBorderType_(NSNoBorder)
                background.setCornerRadius_(4.0)
                background.setFillColor_(NSColor.whiteColor())
                view.addSubview_(background)

            title = f"⟳ {tab.title}" if tab.running() else tab.title
            label = NSTextField.alloc().initWithFrame_(
                ((6, 0), (current_width - 28, tab_inner_height))
            )
            label.setStringValue_(title)
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setAlignment_(1)
            label.setFont_(NSFont.systemFontOfSize_(11.0))
            label.setTextColor_(
                NSColor.blackColor()
                if active
                else NSColor.colorWithCalibratedWhite_alpha_(0.4, 1.0)
            )
            view.addSubview_(label)

            close = CloseTab.alloc().initWithFrame_(
                ((current_width - 18, 0), (16, tab_inner_height))
            )
            close.ui = self
            close.index = index
            close_label = NSTextField.alloc().initWithFrame_(
                ((0, 0), (16, tab_inner_height))
            )
            close_label.setStringValue_("×")
            close_label.setEditable_(False)
            close_label.setSelectable_(False)
            close_label.setBezeled_(False)
            close_label.setDrawsBackground_(False)
            close_label.setAlignment_(1)
            close.addSubview_(close_label)
            view.addSubview_(close)
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
                container.addSubview_(separator)
                x += separator_width

    def _render_transcript(self, root, y: float, height: float, rendered) -> None:
        box = NSBox.alloc().initWithFrame_(
            ((self.content_x, y), (self.content_width, height))
        )
        box.setBoxType_(NSBoxCustom)
        box.setBorderType_(NSNoBorder)
        box.setCornerRadius_(self.text_corner_radius)
        box.setFillColor_(NSColor.whiteColor())
        root.addSubview_(box)

        scroll = NSScrollView.alloc().initWithFrame_(
            (
                (0, self.textbox_y_fudge),
                (
                    self.content_width - 2 * self.text_corner_radius,
                    height - 2 * self.text_corner_radius,
                ),
            )
        )
        scroll.setHasVerticalScroller_(height >= NSScreen.mainScreen().frame().size.height * 0.64)
        scroll.setHasHorizontalScroller_(False)
        box.addSubview_(scroll)

        text = ConversationTextView.alloc().initWithFrame_(
            (
                (self.textbox_x_fudge, self.textbox_y_fudge),
                (
                    self.content_width - 2 * self.text_corner_radius,
                    max(height - 2 * self.text_corner_radius, 1),
                ),
            )
        )
        text.ui = self
        text.setEditable_(False)
        text.setSelectable_(True)
        text.setDrawsBackground_(False)
        text.setLinkTextAttributes_({})
        text.textStorage().setAttributedString_(rendered)
        text.setVerticallyResizable_(True)
        text.setHorizontallyResizable_(False)
        text.textContainer().setWidthTracksTextView_(True)
        text.textContainer().setLineFragmentPadding_(0)
        delegate = ConversationDelegate.alloc().init()
        delegate.ui = self
        text.setDelegate_(delegate)
        self.conversation_delegate = delegate
        self.text_view = text
        scroll.setDocumentView_(text)
        if hasattr(scroll, "tile"):
            scroll.tile()
        clip_size = scroll.contentView().bounds().size
        text_width = max(
            0.0,
            clip_size.width - self.textbox_x_fudge - self.text_right_inset,
        )
        text_height = max(
            clip_size.height,
            height - 2 * self.text_corner_radius - self.textbox_y_fudge,
        )
        text.setFrame_(
            (
                (self.textbox_x_fudge, self.textbox_y_fudge),
                (text_width, text_height),
            )
        )
        text.scrollRangeToVisible_((text.textStorage().length(), 0))

    def _render_input(self, root, y: float, draft: str) -> None:
        box = NSBox.alloc().initWithFrame_(
            ((self.content_x, y), (self.content_width, self.input_height))
        )
        box.setBoxType_(NSBoxCustom)
        box.setBorderType_(NSNoBorder)
        box.setCornerRadius_(self.text_corner_radius)
        box.setFillColor_(NSColor.whiteColor())
        root.addSubview_(box)

        scroll = NSScrollView.alloc().initWithFrame_(
            (
                (self.textbox_x_fudge, self.textbox_y_fudge),
                (
                    self.content_width - 2 * self.text_corner_radius,
                    self.input_height - 2 * self.text_corner_radius,
                ),
            )
        )
        scroll.setHasVerticalScroller_(False)
        box.addSubview_(scroll)
        field = NSTextView.alloc().initWithFrame_(
            ((0, 0), scroll.frame().size)
        )
        field.setString_(draft)
        field.setFont_(NSFont.systemFontOfSize_(FONT_SIZE))
        field.setDrawsBackground_(False)
        field.setAutomaticQuoteSubstitutionEnabled_(False)
        field.setAutomaticDashSubstitutionEnabled_(False)
        field.setSelectedRange_((len(draft), 0))
        delegate = InputDelegate.alloc().initWithUI_textView_(self, field)
        self.input_delegate = delegate
        self.input_field = field
        scroll.setDocumentView_(field)

    def _measure(self, attributed) -> float:
        text_width = self.content_width - 2 * self.text_corner_radius
        text = NSTextView.alloc().initWithFrame_(
            ((0, 0), (text_width, 10000))
        )
        text.setHorizontallyResizable_(False)
        text.textContainer().setContainerSize_((text_width, 10000))
        text.textContainer().setWidthTracksTextView_(True)
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
        self.renderer.toggle_block(block_id)
        self.update_window()

    def copy_block(self, block_id: str) -> None:
        content = self.renderer.block_content(block_id)
        if content is None:
            return
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.declareTypes_owner_([NSStringPboardType], None)
        pasteboard.setString_forType_(content, NSStringPboardType)

    def focus_next_block(self, backwards: bool = False) -> bool:
        if not self.renderer.block_ranges or self.text_view is None:
            return False
        step = -1 if backwards else 1
        self.focused_block = (
            self.focused_block + step
        ) % len(self.renderer.block_ranges)
        _, start, length = self.renderer.block_ranges[self.focused_block]
        storage = self.text_view.textStorage()
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
        self.text_view.scrollRangeToVisible_((start, length))
        self.window.makeFirstResponder_(self.text_view)
        return True

    def copy_focused_block(self) -> None:
        if 0 <= self.focused_block < len(self.renderer.block_ranges):
            block_id, _, _ = self.renderer.block_ranges[self.focused_block]
            self.copy_block(block_id)

    def exit_block_focus(self) -> None:
        self.focused_block = -1
        self.update_window()

    def close_window(self) -> None:
        self._save_draft()
        if self.window is not None:
            self.window.orderOut_(None)
            self.window = None
        self.app.hide_(None)

    def hotkey_pressed(self) -> None:
        if self.window is None:
            self.update_window()
        else:
            self.close_window()

    def _save_draft(self) -> None:
        if self.input_field is not None and self.tabs:
            self.active_tab.draft = str(self.input_field.string())

    def _current_input(self) -> str:
        if self.input_field is None:
            return self.active_tab.draft if self.tabs else ""
        return str(self.input_field.string())

    def _clear_input(self) -> None:
        self.active_tab.draft = ""
        if self.input_field is not None:
            self.input_field.setString_("")

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
        self.app.setMainMenu_(menu)

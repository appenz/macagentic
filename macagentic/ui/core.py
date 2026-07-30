from __future__ import annotations

import queue
import signal
import threading
from dataclasses import dataclass, field
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
from macagentic.history import save_history
from macagentic.ui.helpers import request_fast_text
from macagentic.ui.math_render import MathBitmapCache
from macagentic.ui.markdown import FONT_SIZE, MarkdownRenderer
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

    def copy_(self, _sender):
        if self.ui is None or self.ui.renderer is None:
            objc.super(ConversationTextView, self).copy_(None)
            return
        selected = self.selectedRange()
        if selected.length == 0:
            objc.super(ConversationTextView, self).copy_(None)
            return
        markdown = self.ui.renderer.markdown_for_selection(
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

class MainThreadBridge(NSObject):
    ui = None

    def pollSignals_(self, _timer):
        pass

    def repaint_(self, _value):
        if self.ui is not None:
            self.ui._main_thread_update()

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
        if self.ui is not None and self.ui.window is None:
            self.ui.hotkey_pressed()
        return True


@dataclass
class UITab:
    # Identity and conversation
    id: int
    agent: Agent

    # Display state
    title: str = "New Agent"
    input_text: str = ""
    tool_call_descriptions: dict[str, str] = field(default_factory=dict)
    log_render_index: int = 0
    math_bitmap_cache: MathBitmapCache = field(default_factory=MathBitmapCache)

    # Execution
    thread: threading.Thread | None = None
    requests: queue.Queue[str] = field(default_factory=queue.Queue)

    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class MacAgenticUI:
    """A passive Cocoa renderer over each tab's in-memory transcript."""

    tabs: list[UITab]
    active_index: int
    focused_block: int
    window: NSWindow | None
    input_field: NSTextView | None
    text_view: NSTextView | None
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

    def __init__(self, agent: Agent) -> None:
        self.window = None
        self.input_field = None
        self.text_view = None
        self.renderer = MarkdownRenderer()
        agent.ui = self
        self.tabs = [UITab(id=agent.id, agent=agent)]
        self.active_index = 0
        self.focused_block = -1
        self.update_queue: queue.Queue[UIUpdate] = queue.Queue()
        self._rendering = False
        self._render_pending = False

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
        self._save_input()
        agent = app.create_agent(render_markdown=True)
        agent.ui = self
        self.tabs.append(UITab(id=agent.id, agent=agent))
        self.active_index = len(self.tabs) - 1
        if self.window is not None:
            self._render_window()

    def close_tab(self, index: int) -> None:
        if not 0 <= index < len(self.tabs):
            return
        tab = self.tabs[index]
        tab.agent.interrupt()
        save_history(
            app.workspace,
            render_history(tab.agent.conversation_log.snapshot()),
        )
        self.tabs.pop(index)
        if not self.tabs:
            agent = app.create_agent(render_markdown=True)
            agent.ui = self
            self.tabs.append(UITab(id=agent.id, agent=agent))
            self.active_index = 0
        else:
            self.active_index = min(self.active_index, len(self.tabs) - 1)
        self._render_window()

    def switch_tab(self, index: int) -> None:
        if not 0 <= index < len(self.tabs):
            return
        self._save_input()
        self.active_index = index
        self.focused_block = -1
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
        if NSThread.isMainThread():
            self._main_thread_update()
        else:
            self.bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                "repaint:", None, False
            )

    def post_update(self, event: UIUpdate) -> None:
        self.update_queue.put(event)
        self.update()

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

    def _main_thread_update(self) -> None:
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
            elif isinstance(event, SetToolCallDescription):
                tab.tool_call_descriptions[event.tool_call_id] = event.text
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

        for tab in self.tabs:
            self._start_display_work(tab)
        if self.window is not None:
            self._render_window()

    def _start_display_work(self, tab: UITab) -> None:
        events = tab.agent.conversation_log.snapshot()
        new_events = events[tab.log_render_index :]
        tab.log_render_index = len(events)
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

    def _render_window(self) -> None:
        if not self.tabs:
            return
        if self._rendering:
            self._render_pending = True
            return
        self._rendering = True
        try:
            self._render_window_body()
        finally:
            self._rendering = False
            if self._render_pending:
                self._render_pending = False
                self._render_window()

    def _render_window_body(self) -> None:
        if not self.tabs:
            return
        draft = self._current_input()
        if self.window is not None:
            self.active_tab.input_text = draft

        transcript = render_conversation(
            self.active_tab.agent.conversation_log.snapshot(),
            tool_call_descriptions=self.active_tab.tool_call_descriptions,
            show_tool_output=app.show_tool_output,
        )
        rendered = self.renderer.render(
            transcript,
            NSColor.darkGrayColor(),
            math_bitmap_cache=self.active_tab.math_bitmap_cache,
            scale_factor=self._window_backing_scale(),
        )
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
        self._render_input(root, input_y, self.active_tab.input_text)

        self.window.display()
        self.window.orderFrontRegardless()
        self.window.makeKeyWindow()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
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

        snapshot = self.active_tab.agent.usage.snapshot()
        model = display_model_name(self.active_tab.agent.model_name)
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
        self._render_window()

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
        self._render_window()

    def close_window(self) -> None:
        self._save_input()
        if self.window is not None:
            self.window.orderOut_(None)
            self.window = None
        NSApplication.sharedApplication().hide_(None)

    def hotkey_pressed(self) -> None:
        if self.window is None:
            self._render_window()
        else:
            self.close_window()

    def _save_input(self) -> None:
        if self.input_field is not None and self.tabs:
            self.active_tab.input_text = str(self.input_field.string())

    def _current_input(self) -> str:
        if self.input_field is None:
            return self.active_tab.input_text if self.tabs else ""
        return str(self.input_field.string())

    def _clear_input(self) -> None:
        self.active_tab.input_text = ""
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
        NSApplication.sharedApplication().setMainMenu_(menu)


def _clean_title(value: str) -> str:
    title = " ".join(value.splitlines()[0].split()).strip("\"'` .:;-")
    return title[:28] or "New Agent"


TOOL_UPDATE_MAX_LENGTH = 80


def _clean_description(value: str) -> str:
    description = " ".join(value.splitlines()[0].split()).strip("\"'` .:;-")
    return description[:TOOL_UPDATE_MAX_LENGTH] or "Running command"

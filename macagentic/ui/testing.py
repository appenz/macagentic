"""In-process Cocoa UI instrumentation."""

import time
from collections.abc import Callable

from Cocoa import (
    NSApplication,
    NSCommandKeyMask,
    NSEvent,
    NSKeyDown,
    NSKeyUp,
    NSPasteboard,
    NSStringPboardType,
)
from Foundation import NSDate, NSRunLoop

from macagentic.ui.screenshot import capture_window_by_title

_COMMAND_KEY_CODES = {
    "c": 0x08,
    "v": 0x09,
    "x": 0x07,
    "a": 0x00,
    "z": 0x06,
}


class UITestDriver:
    def __init__(self, ui) -> None:
        self.ui = ui

    def type_text(self, text: str) -> None:
        self.ui.active_content_view.input_text_view.insertText_(text)
        self.spin()

    def press_return(self) -> None:
        content = self.ui.active_content_view
        content.input_delegate.textView_doCommandBySelector_(
            content.input_text_view,
            "insertNewline:",
        )
        self.spin()

    def press_cmd(self, key: str) -> None:
        key = key.lower()
        key_code = _COMMAND_KEY_CODES[key]
        input_view = self.ui.active_content_view.input_text_view
        self.ui.window.makeFirstResponder_(input_view)
        for event_type in (NSKeyDown, NSKeyUp):
            event = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
                event_type,
                (0, 0),
                NSCommandKeyMask,
                0,
                self.ui.window.windowNumber(),
                None,
                key,
                key,
                False,
                key_code,
            )
            if event_type == NSKeyDown:
                self.ui.window.performKeyEquivalent_(event)
            else:
                NSApplication.sharedApplication().postEvent_atStart_(event, True)
        self.spin()

    def input_text(self) -> str:
        return self.ui.active_content_view.input_text()

    def conversation_text(self) -> str:
        content = self.ui.active_content_view
        if content is None:
            return ""
        return str(content.transcript_view.string())

    def tab_count(self) -> int:
        return len(self.ui.tabs)

    def clipboard(self) -> str | None:
        value = NSPasteboard.generalPasteboard().stringForType_(
            NSStringPboardType
        )
        return str(value) if value is not None else None

    def screenshot(self, path: str) -> bool:
        return capture_window_by_title("macAgentic", path)

    def spin(self, seconds: float = 0.1) -> None:
        deadline = NSDate.dateWithTimeIntervalSinceNow_(seconds)
        NSRunLoop.currentRunLoop().runUntilDate_(deadline)

    def wait_for(
        self,
        predicate: Callable[[], bool],
        *,
        timeout: float = 5.0,
        interval: float = 0.1,
    ) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self.spin(interval)
            if predicate():
                return True
        return False

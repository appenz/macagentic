from pathlib import Path
import threading

import pytest

from macagentic.agent.transcript import Transcript
from macagentic.agent.usage import UsageAccumulator
from macagentic.ui.testing import UITestDriver


class FakeControl:
    def __init__(self, _workspace, **kwargs):
        self.transcript = kwargs.get("transcript") or Transcript()
        self.history = Transcript()
        self.on_usage = kwargs.get("on_usage")
        self.usage = UsageAccumulator()
        self.interrupted = False

    def run_turn(self, text: str) -> None:
        content = (
            f"**You:** {text}\n\n"
            "# Agent reply\n\nRendered **Markdown**.\n"
        )
        self.transcript.write(content)
        self.history.write(content)
        snapshot = self.usage.add_response(
            {
                "usage": {
                    "input_tokens": 12345,
                    "input_tokens_details": {
                        "cached_tokens": 8192,
                        "cache_write_tokens": 4096,
                    },
                    "output_tokens": 1024,
                },
                "extra": {"cost": 0.65},
            }
        )
        if snapshot is not None and self.on_usage is not None:
            self.on_usage(snapshot)

    def interrupt(self) -> None:
        self.interrupted = True


@pytest.mark.uitest
def test_ui_passively_renders_transcript(monkeypatch) -> None:
    monkeypatch.setattr("macagentic.ui.core.Control", FakeControl)
    from macagentic.ui.core import MacAgenticUI

    saved = []
    monkeypatch.setattr(
        "macagentic.ui.core.save_history",
        lambda workspace, content: saved.append((workspace, content))
        if content.strip()
        else None,
    )
    ui = MacAgenticUI(Path.cwd())
    ui.start(dont_run_app=True)
    driver = UITestDriver(ui)

    assert ui.window.frame().size.width == 672
    assert ui.window.frame().size.height == 198
    assert ui.app.applicationIconImage().size().width > 0

    driver.type_text("copy me")
    ui.input_field.setSelectedRange_((0, 7))
    driver.press_cmd("c")
    assert driver.clipboard() == "copy me"
    ui.input_field.setString_("")
    driver.press_cmd("v")
    assert driver.input_text() == "copy me"
    ui.input_field.setString_("")

    driver.type_text("hello")
    driver.press_return()
    assert driver.wait_for(lambda: "Agent reply" in driver.conversation_text())
    assert "Rendered Markdown" in driver.conversation_text()
    assert driver.tab_count() == 1
    assert driver.wait_for(
        lambda: "$0.65" in str(ui.top_bar_text_view.string())
    )
    assert str(ui.top_bar_text_view.string()) == (
        "gpt-5-mini / $0.65\n"
        "Input: 12,345 / Cached: 8,192\n"
        "Writes: 4,096 / Output: 1,024"
    )

    ui.new_tab()
    assert str(ui.top_bar_text_view.string()) == (
        "gpt-5-mini / $0.00\n"
        "Input: 0 / Cached: 0\n"
        "Writes: 0 / Output: 0"
    )
    ui.close_tab(ui.active_index)

    release = threading.Event()
    running = threading.Thread(target=release.wait)
    running.start()
    ui.active_tab.thread = running
    ui._handle_console_interrupt(None, None)
    assert ui.active_tab.control.interrupted
    release.set()
    running.join()
    ui.active_tab.thread = None

    ui.close_window()
    assert ui.window is None
    ui.app_delegate.applicationShouldHandleReopen_hasVisibleWindows_(
        ui.app,
        False,
    )
    assert ui.window is not None

    ui.hotkey_pressed()
    assert ui.window is None
    ui.hotkey_pressed()
    assert ui.window is not None
    ui.close_window()
    expected_history = ui.active_tab.control.history.getvalue()
    ui.close_tab(0)
    assert saved == [(Path.cwd(), expected_history)]

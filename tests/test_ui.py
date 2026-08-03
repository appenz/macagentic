import threading
from pathlib import Path

import pytest

pytest.importorskip("Cocoa", reason="Cocoa UI requires macOS")

from macagentic.agent import ConversationLog, UsageTracker
from macagentic.ui.projection import render_history
from macagentic.ui.testing import UITestDriver
from macagentic.ui.updates import SetTabTitle, SetToolCallDescription


class FakeAgent:
    next_id = 1

    def __init__(self, **_kwargs) -> None:
        self.id = self.next_id
        type(self).next_id += 1
        self.ui = None
        self.messages = []
        self.conversation_log = ConversationLog()
        self.usage = UsageTracker()
        self.model_name = "openai/gpt-5-mini"
        self.interrupted = False

    def run_turn(self, text: str) -> None:
        self.conversation_log.append(
            "user_input",
            {"content": text},
        )
        self.conversation_log.append_message(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "# Agent reply\n\n"
                                    "Rendered **Markdown**."
                                ),
                            }
                        ],
                    }
                ],
                "extra": {"actions": []},
            }
        )
        self.usage.add_response(
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
        if self.ui is not None:
            self.ui.update()

    def interrupt(self) -> None:
        self.interrupted = True


def open_test_ui(monkeypatch):
    from macagentic.ui.core import MacAgenticUI

    monkeypatch.setattr(
        "macagentic.ui.core.app.create_agent",
        FakeAgent,
    )
    monkeypatch.setattr(
        "macagentic.ui.core.request_fast_text",
        lambda **_kwargs: None,
    )
    ui = MacAgenticUI(FakeAgent())
    ui.start(dont_run_app=True)
    ui.hotkey_pressed(activate=False)
    return ui, UITestDriver(ui)


@pytest.mark.uitest
def test_ui_passively_renders_conversation_log(monkeypatch) -> None:
    from macagentic.ui.core import MacAgenticUI

    saved = []
    monkeypatch.setattr(
        "macagentic.ui.core.save_history",
        lambda workspace, content: saved.append((workspace, content))
        if content.strip()
        else None,
    )
    monkeypatch.setattr(
        "macagentic.ui.core.app.create_agent",
        FakeAgent,
    )
    monkeypatch.setattr(
        "macagentic.ui.core.request_fast_text",
        lambda **_kwargs: None,
    )

    agent = FakeAgent()
    ui = MacAgenticUI(agent)
    ui.start(dont_run_app=True)
    assert ui.window is None
    ui.hotkey_pressed(activate=False)
    driver = UITestDriver(ui)

    assert ui.window.frame().size.width == 672
    assert ui.window.frame().size.height == 198

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
    assert ui.active_tab.agent.interrupted
    release.set()
    running.join()
    ui.active_tab.thread = None

    ui.close_window()
    retained_window = ui.window
    assert not ui.window_is_visible()
    ui.app_delegate.applicationShouldHandleReopen_hasVisibleWindows_(
        None,
        False,
    )
    assert ui.window is retained_window
    assert ui.window_is_visible()

    ui.hotkey_pressed(activate=False)
    assert not ui.window_is_visible()
    ui.hotkey_pressed(activate=False)
    assert ui.window is retained_window
    assert ui.window_is_visible()
    ui.close_window()
    expected_history = render_history(
        ui.active_tab.agent.conversation_log.snapshot()
    )
    ui.close_tab(0)
    assert saved == [(Path.cwd(), expected_history)]


@pytest.mark.uitest
def test_tab_drafts_remain_with_their_tabs(monkeypatch) -> None:
    ui, driver = open_test_ui(monkeypatch)
    first_content = ui.active_tab.content_view
    first_input = first_content.input_text_view
    assert (
        ui.active_tab.tab_bar_item.active_background.frame().origin.y
        == -ui.padding
    )

    driver.type_text("first tab draft")
    ui.new_tab()
    second_content = ui.active_tab.content_view
    second_input = second_content.input_text_view
    assert driver.input_text() == ""
    assert first_content is not second_content
    assert first_input is not second_input

    driver.type_text("second tab draft")
    ui.switch_tab(0)
    assert driver.input_text() == "first tab draft"
    assert ui.active_tab.input_text == "first tab draft"
    assert ui.active_content_view is first_content
    assert ui.input_field is first_input

    ui.switch_tab(1)
    assert driver.input_text() == "second tab draft"
    assert ui.active_tab.input_text == "second tab draft"
    assert ui.active_content_view is second_content
    assert ui.input_field is second_input
    ui.close_window()


@pytest.mark.uitest
def test_inactive_tab_updates_preserve_visible_selection(monkeypatch) -> None:
    ui, driver = open_test_ui(monkeypatch)
    visible_tab = ui.active_tab
    visible_tab.agent.conversation_log.append(
        "user_input",
        {"content": "Keep this selected"},
    )
    ui._main_thread_update(visible_tab.id)
    ui.new_tab()
    hidden_tab = ui.active_tab
    ui.switch_tab(0)

    selected = (0, 4)
    ui.text_view.setSelectedRange_(selected)
    visible_view = ui.text_view
    visible_text = driver.conversation_text()

    def update_hidden_tab() -> None:
        hidden_tab.thread = threading.current_thread()
        hidden_tab.agent.ui.update()

    worker = threading.Thread(target=update_hidden_tab)
    worker.start()
    worker.join()
    driver.spin()

    assert ui.text_view is visible_view
    assert driver.conversation_text() == visible_text
    selection = ui.text_view.selectedRange()
    assert (selection.location, selection.length) == selected

    ui.post_update(SetTabTitle(hidden_tab.id, "Background title"))
    assert str(hidden_tab.tab_bar_item.title_label.stringValue()) == (
        "Background title"
    )
    assert ui.text_view is visible_view

    ui.post_update(
        SetToolCallDescription(hidden_tab.id, "call-1", "Background work")
    )
    assert ui.text_view is visible_view
    ui.close_window()


def test_main_thread_update_renders_only_the_active_tab(monkeypatch) -> None:
    from macagentic.ui.core import MacAgenticUI

    monkeypatch.setattr(
        "macagentic.ui.core.app.create_agent",
        FakeAgent,
    )
    ui = MacAgenticUI(FakeAgent())
    ui.new_tab()
    hidden_tab = ui.tabs[0]
    active_tab = ui.tabs[1]
    ui.window = object()
    monkeypatch.setattr(ui, "window_is_visible", lambda: True)
    rendered = []
    display_work = []
    monkeypatch.setattr(ui, "_render_window", lambda: rendered.append(True))
    monkeypatch.setattr(
        ui,
        "_process_new_display_events",
        lambda tab: display_work.append(tab.id),
    )
    monkeypatch.setattr(ui, "_refresh_tab_title", lambda _tab_id: None)

    ui._main_thread_update(hidden_tab.id)
    assert rendered == []
    assert display_work == []

    ui._main_thread_update(active_tab.id)
    assert rendered == [True]
    assert display_work == [active_tab.id]

    ui.update_queue.put(
        SetToolCallDescription(hidden_tab.id, "call-1", "Hidden work")
    )
    ui._main_thread_update()
    assert rendered == [True]

    ui.update_queue.put(
        SetToolCallDescription(active_tab.id, "call-2", "Visible work")
    )
    ui._main_thread_update()
    assert rendered == [True, True]


def test_update_resolves_registered_worker_thread(monkeypatch) -> None:
    from macagentic.ui.core import MacAgenticUI

    monkeypatch.setattr(
        "macagentic.ui.core.app.create_agent",
        FakeAgent,
    )
    ui = MacAgenticUI(FakeAgent())
    ui.new_tab()
    scheduled = []
    monkeypatch.setattr(
        ui,
        "_schedule_main_thread_update",
        scheduled.append,
    )

    def update_from(tab=None) -> None:
        if tab is not None:
            tab.thread = threading.current_thread()
        ui.update()

    registered = threading.Thread(target=update_from, args=(ui.tabs[0],))
    registered.start()
    registered.join()
    assert scheduled == [ui.tabs[0].id]

    unknown = threading.Thread(target=update_from)
    unknown.start()
    unknown.join()
    assert scheduled == [ui.tabs[0].id]


def test_closed_tab_discards_async_update(monkeypatch) -> None:
    from macagentic.ui.core import MacAgenticUI

    monkeypatch.setattr(
        "macagentic.ui.core.app.create_agent",
        FakeAgent,
    )
    ui = MacAgenticUI(FakeAgent())
    closed_id = ui.active_tab.id
    ui.close_tab(0)

    ui.update_queue.put(SetTabTitle(closed_id, "Stale title"))
    ui._main_thread_update()

    assert ui.active_tab.title == "New Agent"


def test_ui_saves_only_persistent_tab_state(monkeypatch) -> None:
    from macagentic.ui.core import MacAgenticUI

    captured = []
    monkeypatch.setattr(
        "macagentic.ui.core.write_session",
        captured.append,
    )
    agent = FakeAgent()
    agent.messages = [{"role": "user", "content": "hello"}]
    agent.conversation_log.append(
        "user_input",
        {"content": "hello"},
    )
    ui = MacAgenticUI(agent)
    ui.active_tab.title = "Saved title"
    ui.active_tab.input_text = "draft"
    ui.active_tab.tool_call_descriptions["call-1"] = "cache"

    ui.save_session()

    saved = captured[0]
    assert saved.active_index == 0
    assert saved.tabs[0].title == "Saved title"
    assert saved.tabs[0].input_text == "draft"
    assert saved.tabs[0].messages == agent.messages
    assert saved.tabs[0].events == agent.conversation_log.records()

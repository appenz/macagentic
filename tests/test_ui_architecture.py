import threading
from pathlib import Path

from macagentic.agent import ConversationEvent, ConversationLog
from macagentic.agent.skills import EMPTY_SKILL_CATALOG
from macagentic.app import MacAgenticApp
from macagentic.ui.cli import CommandLineUI
from macagentic.ui.helpers.fast_llm import request_fast_text
from macagentic.ui.projection import render_conversation, render_history


def test_projection_renders_display_state_and_optional_tool_output() -> None:
    events = (
        ConversationEvent("user_input", {"content": "List files"}),
        ConversationEvent(
            "message",
            {
                "extra": {
                    "actions": [
                        {
                            "tool_call_id": "call-1",
                            "command": "ls",
                        }
                    ]
                }
            },
        ),
        ConversationEvent(
            "tool_execution",
            {
                "action": {"command": "ls"},
                "output": {"output": "README.md\n", "returncode": 0},
            },
        ),
    )

    rendered = render_conversation(
        events,
        tool_call_descriptions={"call-1": "Listing workspace files"},
    )
    assert "Listing workspace files" in rendered
    assert "README.md" not in rendered

    rendered_with_tools = render_conversation(
        events,
        tool_call_descriptions={"call-1": "Listing workspace files"},
        show_tool_output=True,
    )
    assert "README.md" in rendered_with_tools
    assert '"tool_call_id": "call-1"' in render_history(events)


def test_fast_llm_request_is_non_blocking(monkeypatch) -> None:
    release = threading.Event()
    completed = threading.Event()
    results = []

    def fake_response(**_kwargs):
        release.wait(timeout=2)
        return {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "Short title"}
                    ],
                }
            ]
        }

    monkeypatch.setattr(
        "macagentic.ui.helpers.fast_llm.litellm.responses",
        fake_response,
    )

    request_fast_text(
        system_prompt="Title this task",
        user_prompt="Fix tests",
        on_result=lambda value: (results.append(value), completed.set()),
    )
    assert not completed.is_set()

    release.set()
    assert completed.wait(timeout=2)
    assert results == ["Short title"]


def test_command_line_ui_projects_only_new_events(
    monkeypatch,
    capsys,
) -> None:
    class FakeAgent:
        def __init__(self) -> None:
            self.ui = None
            self.conversation_log = ConversationLog()

    agent = FakeAgent()
    monkeypatch.setattr(
        "macagentic.ui.cli.app.create_agent",
        lambda: agent,
    )
    ui = CommandLineUI()
    agent.conversation_log.append(
        "user_input",
        {"content": "Hello"},
    )

    ui.update()
    ui.update()

    assert capsys.readouterr().out == "**You:** Hello\n\n"


def test_application_object_creates_configured_agents(monkeypatch) -> None:
    created = []

    class FakeAgent:
        def __init__(self, workspace, **kwargs) -> None:
            created.append((workspace, kwargs))

    monkeypatch.setattr("macagentic.app.Agent", FakeAgent)
    application = MacAgenticApp()
    application.configure(
        workspace=Path("."),
        model_name="test-model",
        custom_instructions="custom",
        tool_instructions="tools",
        skill_catalog=EMPTY_SKILL_CATALOG,
        show_tool_output=True,
    )

    application.create_agent()

    workspace, kwargs = created[0]
    assert workspace == Path.cwd()
    assert kwargs["model_name"] == "test-model"
    assert kwargs["custom_instructions"] == "custom"
    assert kwargs["tool_instructions"] == "tools"

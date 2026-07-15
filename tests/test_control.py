import os
import signal
import threading
from pathlib import Path
from types import SimpleNamespace

from macagentic.agent.control import Control, ResponseModel, load_system_prompt
from macagentic.agent.skills import Skill, SkillCatalog
from macagentic.agent.transcript import Transcript

EXPECTED_DEFAULT_PROMPT = """You are an interactive coding assistant with access to a bash tool.
Answer the user's current message directly. Use bash only when it materially helps
answer the request; simple questions should not use tools. After using tools,
provide a final response without a tool call so control returns to the user.

You have direct access to the local filesystem through bash. When the user asks
you to inspect, search, or summarize local files, use bash to do the work
yourself. Never claim that you cannot access those files or ask the user to run
commands for you. Do not modify files unless the user requests a change.

## Custom Instructions



# Available Tools



# Available Skills

You have access to agent skills that help you fulfill tasks.
Load a skill by reading the SKILL.md path listed for it below.
Below a list of skills, the format is <skill name> - Description - SKILL.md path.


"""


def text_response(
    content: str,
    *,
    usage: dict | None = None,
    cost: float = 0.0,
) -> dict:
    response = {
        "object": "response",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": content},
                ],
            }
        ],
        "extra": {"actions": [], "cost": cost},
    }
    if usage is not None:
        response["usage"] = usage
    return response


class FakeModel:
    def query(self, _messages):
        return text_response("The answer is **2**.")


class SignallingModel:
    def query(self, _messages):
        os.kill(os.getpid(), signal.SIGINT)


class BlockingModel:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def query(self, _messages):
        self.started.set()
        self.release.wait()
        return text_response("Late response")


class ToolModel:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, _messages):
        self.calls += 1
        if self.calls == 1:
            return {
                "object": "response",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "bash",
                        "arguments": '{"command":"printf hello"}',
                    }
                ],
                "extra": {
                    "actions": [
                        {
                            "command": "printf 'hello\\n'",
                            "tool_call_id": "call-1",
                        }
                    ],
                },
            }
        return text_response("Done.")

    def format_observation_messages(self, _response, _outputs):
        return [
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "hello",
            }
        ]


class FakeEnvironment:
    def execute(self, _action):
        return {
            "output": "hello\n",
            "returncode": 0,
            "exception_info": "",
        }

    def interrupt(self):
        return


def test_default_prompt_is_unchanged() -> None:
    assert load_system_prompt() == EXPECTED_DEFAULT_PROMPT


def test_custom_instructions_replace_placeholder() -> None:
    prompt = load_system_prompt("Always answer briefly.")

    assert "## Custom Instructions\n\nAlways answer briefly.\n\n# Available Tools" in prompt
    assert "{{CUSTOM_INSTRUCTIONS}}" not in prompt
    assert "{{TOOLS}}" not in prompt
    assert "{{SKILLS}}" not in prompt


def test_response_model_allows_text_and_preserves_reasoning_items() -> None:
    model = object.__new__(ResponseModel)
    text_only = SimpleNamespace(
        output=[SimpleNamespace(type="message")]
    )

    assert model._parse_actions(text_only) == []
    assert model._prepare_messages_for_api(
        [
            {"role": "system", "content": "Instructions"},
            {
                "object": "response",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "reasoning-1",
                    }
                ],
                "extra": {"cost": 0.01},
            },
        ]
    ) == [
        {"role": "system", "content": "Instructions"},
        {"type": "reasoning", "id": "reasoning-1"},
    ]


def test_tool_instructions_replace_placeholder_with_custom_instructions() -> None:
    prompt = load_system_prompt(
        "Always answer briefly.",
        "### `things`\n\nUse `things list`.",
    )

    assert (
        "## Custom Instructions\n\nAlways answer briefly.\n\n"
        "# Available Tools\n\n"
        "### `things`\n\nUse `things list`."
    ) in prompt
    assert "{{CUSTOM_INSTRUCTIONS}}" not in prompt
    assert "{{TOOLS}}" not in prompt


def test_control_writes_only_conversation_text() -> None:
    transcript = Transcript()
    outputs = []
    control = Control(
        Path.cwd(),
        transcript=transcript,
        on_output=outputs.append,
    )
    control.model = FakeModel()

    control.run_turn("What is 1+1?")

    assert transcript.getvalue() == (
        "**You:** What is 1+1?\n\nThe answer is **2**.\n\n"
    )
    assert outputs == ["The answer is **2**."]
    assert "tool" not in transcript.getvalue().lower()


def test_control_expands_skill_for_model_but_not_transcript() -> None:
    transcript = Transcript()
    catalog = SkillCatalog(
        (
            Skill(
                name="summarize",
                description="Summarize text.",
                body="Follow these summary instructions.",
            ),
        )
    )
    control = Control(
        Path.cwd(),
        transcript=transcript,
        skill_catalog=catalog,
    )
    control.model = FakeModel()

    control.run_turn("/summarize this document")

    assert transcript.getvalue().startswith(
        "**You:** /summarize this document\n\n"
    )
    assert control.messages[1] == {
        "role": "user",
        "content": "Follow these summary instructions. this document",
    }


def test_control_accumulates_response_usage() -> None:
    updates = []
    control = Control(Path.cwd(), on_usage=updates.append)
    control.model = FakeModel()
    control.model.query = lambda _messages: text_response(
        "Done.",
        usage={
            "input_tokens": 120,
            "input_tokens_details": {
                "cached_tokens": 80,
                "cache_write_tokens": 30,
            },
            "output_tokens": 15,
        },
        cost=0.125,
    )

    control.run_turn("Track it")

    assert updates[-1].input_tokens == 120
    assert updates[-1].cached_input_tokens == 80
    assert updates[-1].cache_write_tokens == 30
    assert updates[-1].output_tokens == 15
    assert updates[-1].cost == 0.125


def test_control_reports_usage_per_call_and_once_per_turn() -> None:
    per_call = []
    per_turn = []

    class MultiCallModel(ToolModel):
        def query(self, messages):
            response = super().query(messages)
            response["usage"] = {
                "input_tokens": 100 * self.calls,
                "output_tokens": 10 * self.calls,
            }
            response.setdefault("extra", {})["cost"] = 0.1 * self.calls
            return response

    control = Control(
        Path.cwd(),
        on_usage=per_call.append,
        on_turn_complete=per_turn.append,
    )
    control.model = MultiCallModel()
    control.environment = FakeEnvironment()

    control.run_turn("Use a tool")

    assert len(per_call) == 2
    assert len(per_turn) == 1
    assert per_turn[0].input_tokens == 300
    assert per_turn[0].output_tokens == 30
    assert abs(per_turn[0].cost - 0.3) < 1e-9


def test_console_ctrl_c_interrupts_and_returns_to_prompt(
    monkeypatch,
    capsys,
) -> None:
    transcript = Transcript()
    control = Control(Path.cwd(), transcript=transcript)
    control.model = SignallingModel()
    monkeypatch.setattr("builtins.input", lambda _prompt: "/exit")

    control.start("Long-running request")

    assert "Interrupted." in capsys.readouterr().out
    assert transcript.getvalue().endswith("Interrupted.\n\n")


def test_interrupt_releases_turn_blocked_on_model_query() -> None:
    control = Control(Path.cwd())
    model = BlockingModel()
    control.model = model
    turn = threading.Thread(target=control.run_turn, args=("Wait",))
    turn.start()
    assert model.started.wait(1)

    control.interrupt()
    turn.join(1)
    model.release.set()

    assert not turn.is_alive()
    assert "Late response" not in control.transcript.getvalue()


def test_interrupt_releases_wait_for_clarification() -> None:
    started = threading.Event()
    release = threading.Event()

    def ask_clarification(_prompt: str) -> str:
        started.set()
        release.wait()
        return "Late answer"

    control = Control(
        Path.cwd(),
        ask_clarification=ask_clarification,
    )
    answers = []
    waiting = threading.Thread(
        target=lambda: answers.append(
            control.request_clarification("Question?")
        )
    )
    waiting.start()
    assert started.wait(1)

    control.interrupt()
    waiting.join(1)
    release.set()

    assert not waiting.is_alive()
    assert answers == [None]


def test_interrupted_response_discards_pending_native_tool_call() -> None:
    control = Control(Path.cwd())
    control.messages.append(
        {
            "object": "response",
            "output": [{"type": "function_call"}],
            "extra": {"actions": [{"command": "sleep 1"}]},
        }
    )

    control._discard_incomplete_tool_call()

    assert control.messages == [
        {
            "role": "system",
            "content": load_system_prompt(),
        }
    ]


def test_tool_output_is_visible_only_when_enabled() -> None:
    hidden = Control(Path.cwd())
    hidden.model = ToolModel()
    hidden.environment = FakeEnvironment()
    hidden.run_turn("Run it")
    assert "**Tool:**" not in hidden.transcript.getvalue()

    visible = []
    control = Control(
        Path.cwd(),
        show_tool_output=True,
        on_tool_output=visible.append,
    )
    control.model = ToolModel()
    control.environment = FakeEnvironment()

    control.run_turn("Run it")

    assert "**Tool:** `printf 'hello\\n'` (exit 0)" in control.transcript.getvalue()
    assert "```text\nhello\n```" in control.transcript.getvalue()
    assert visible and visible[0].startswith("**Tool:**")
    assert any(
        message.get("type") == "function_call_output"
        for message in control.messages
    )

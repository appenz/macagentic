import threading
from pathlib import Path
from types import SimpleNamespace

from macagentic.agent import Agent, ConversationLog, ResponseModel
from macagentic.agent.agent import load_system_prompt
from macagentic.agent.skills import Skill, SkillCatalog


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
    model_name = "openai/fake"

    def query(self, _messages):
        return text_response("The answer is **2**.")


class BlockingModel(FakeModel):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def query(self, _messages):
        self.started.set()
        self.release.wait()
        return text_response("Late response")


class ToolModel(FakeModel):
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


class FakeToolRunner:
    def execute(self, _action):
        return {
            "output": "hello\n",
            "returncode": 0,
            "exception_info": "",
        }

    def interrupt(self) -> None:
        return


class BlockingToolRunner(FakeToolRunner):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, action):
        self.started.set()
        self.release.wait()
        return super().execute(action)

    def interrupt(self) -> None:
        self.release.set()


def message_payloads(agent: Agent) -> list[dict]:
    return [
        event.payload
        for event in agent.conversation_log.snapshot()
        if event.kind == "message"
    ]


def make_agent(tmp_path: Path, **kwargs) -> Agent:
    return Agent(
        1,
        roots_directory=tmp_path / "agent-roots",
        **kwargs,
    )


def test_default_prompt_has_all_placeholders_replaced() -> None:
    prompt = load_system_prompt()

    assert "{{CUSTOM_INSTRUCTIONS}}" not in prompt
    assert "{{TOOLS}}" not in prompt
    assert "{{SKILLS}}" not in prompt
    assert "{{FILESYSTEM}}" not in prompt
    assert "{{#if render_markdown}}" not in prompt
    assert "plain text" in prompt
    assert "Final responses should be in Markdown." not in prompt


def test_markdown_prompt_is_used_for_cocoa_agents(tmp_path: Path) -> None:
    prompt = load_system_prompt(render_markdown=True)

    assert "Final responses should be in Markdown." in prompt
    assert "$...$" in prompt

    agent = make_agent(tmp_path, render_markdown=True)
    assert "Final responses should be in Markdown." in (
        agent.messages[0]["content"]
    )


def test_plain_prompt_is_used_for_cli_agents(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)

    assert "plain text" in agent.messages[0]["content"]
    assert "Final responses should be in Markdown." not in (
        agent.messages[0]["content"]
    )


def test_agent_restores_messages_log_and_existing_root(tmp_path: Path) -> None:
    root = tmp_path / "agent-roots" / "1"
    root.mkdir(parents=True)
    (root / "kept.txt").write_text("kept")
    messages = [
        {"role": "system", "content": "Original instructions"},
        {"role": "user", "content": "Continue"},
    ]
    log = ConversationLog(
        [
            {
                "kind": "message",
                "payload": message,
            }
            for message in messages
        ]
    )

    agent = make_agent(
        tmp_path,
        messages=messages,
        conversation_log=log,
    )

    assert agent.messages == messages
    assert agent.conversation_log.records() == log.records()
    assert (agent.root / "kept.txt").read_text() == "kept"
    assert agent.usage.snapshot().input_tokens == 0


def test_custom_and_tool_instructions_are_inserted() -> None:
    prompt = load_system_prompt(
        "Always answer briefly.",
        "### `things`\n\nUse `things list`.",
    )

    assert "## Custom Instructions\n\nAlways answer briefly." in prompt
    assert "# Available Tools\n\n### `things`" in prompt


def test_agent_uses_its_root_for_tools_and_prompt(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    agent = make_agent(
        tmp_path,
        user_mounts={"notes": str(notes)},
    )

    assert agent.id == 1
    assert agent.root == tmp_path / "agent-roots" / "1"
    assert agent.tool_runner.config.cwd == str(agent.root)
    assert agent.tool_runner.config.env["AGENT_ROOT"] == str(agent.root)
    assert "`notes/` - configured user directory" in (
        agent.messages[0]["content"]
    )


def test_response_model_accepts_plain_text_and_reasoning_items() -> None:
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
                "output": [{"type": "reasoning", "id": "reasoning-1"}],
                "extra": {"cost": 0.01},
            },
        ]
    ) == [
        {"role": "system", "content": "Instructions"},
        {"type": "reasoning", "id": "reasoning-1"},
    ]


def test_agent_copies_every_message_into_conversation_log(
    tmp_path: Path,
) -> None:
    agent = make_agent(tmp_path, ui=None)
    agent.model = FakeModel()

    agent.run_turn("What is 1+1?")

    assert message_payloads(agent) == agent.messages
    assert [
        event.payload
        for event in agent.conversation_log.snapshot()
        if event.kind == "user_input"
    ] == [{"content": "What is 1+1?"}]


def test_agent_expands_skills_only_in_model_messages(
    tmp_path: Path,
) -> None:
    catalog = SkillCatalog(
        (
            Skill(
                name="summarize",
                description="Summarize text.",
                body="Follow these summary instructions.",
            ),
        )
    )
    agent = make_agent(tmp_path, ui=None, skill_catalog=catalog)
    agent.model = FakeModel()

    agent.run_turn("/summarize this document")

    assert agent.messages[1] == {
        "role": "user",
        "content": "Follow these summary instructions. this document",
    }
    assert agent.conversation_log.snapshot()[1].payload == {
        "content": "/summarize this document"
    }


def test_agent_runs_tools_and_records_raw_execution(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, ui=None)
    agent.model = ToolModel()
    agent.tool_runner = FakeToolRunner()

    agent.run_turn("Use a tool")

    assert any(
        message.get("type") == "function_call_output"
        for message in agent.messages
    )
    tool_events = [
        event
        for event in agent.conversation_log.snapshot()
        if event.kind == "tool_execution"
    ]
    assert tool_events[0].payload["output"]["returncode"] == 0
    assert message_payloads(agent) == agent.messages


def test_agent_tracks_usage_from_every_model_call(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, ui=None)
    agent.model = FakeModel()
    agent.model.query = lambda _messages: text_response(
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

    agent.run_turn("Track it")

    snapshot = agent.usage.snapshot()
    assert snapshot.input_tokens == 120
    assert snapshot.cached_input_tokens == 80
    assert snapshot.cache_write_tokens == 30
    assert snapshot.output_tokens == 15
    assert snapshot.cost == 0.125


def test_interrupt_releases_model_wait_and_discards_late_result(
    tmp_path: Path,
) -> None:
    agent = make_agent(tmp_path, ui=None)
    model = BlockingModel()
    agent.model = model
    turn = threading.Thread(target=agent.run_turn, args=("Wait",))
    turn.start()
    assert model.started.wait(1)

    agent.interrupt()
    turn.join(1)
    model.release.set()

    assert not turn.is_alive()
    assert not any(
        "Late response" in str(message)
        for message in agent.messages
    )
    assert agent.conversation_log.snapshot()[-1].kind == "interrupted"


def test_interrupt_prunes_incomplete_tool_call_and_records_discard(
    tmp_path: Path,
) -> None:
    agent = make_agent(tmp_path, ui=None)
    agent.model = ToolModel()
    runner = BlockingToolRunner()
    agent.tool_runner = runner
    turn = threading.Thread(target=agent.run_turn, args=("Run it",))
    turn.start()
    assert runner.started.wait(1)

    agent.interrupt()
    turn.join(1)

    assert not turn.is_alive()
    assert not agent.messages[-1].get("extra", {}).get("actions")
    kinds = [
        event.kind for event in agent.conversation_log.snapshot()
    ]
    assert "discarded_message" in kinds
    assert kinds[-1] == "interrupted"

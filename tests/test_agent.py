import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from macagentic.agent import Agent, ConversationLog, ResponseModel
from macagentic.agent.agent import load_system_prompt
from macagentic.agent.model import (
    CONTEXT_FILE_TYPE,
    MERCURY_2_5,
    MERCURY_2_5_METADATA,
)
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
    def __init__(self, model_name: str = "openai/fake") -> None:
        self.config = SimpleNamespace(model_name=model_name)

    @property
    def model_name(self) -> str:
        return self.config.model_name

    def query(self, _messages):
        return text_response("The answer is **2**.")


class BlockingModel(FakeModel):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def query(self, _messages):
        self.started.set()
        self.release.wait()
        return text_response("Late response")


class ToolModel(FakeModel):
    def __init__(self) -> None:
        super().__init__()
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


class RejectingFileModel(ToolModel):
    def query(self, messages):
        self.calls += 1
        if self.calls == 1:
            return {
                "object": "response",
                "output": [{
                    "type": "function_call",
                    "call_id": "call-1",
                    "name": "bash",
                    "arguments": '{"command":"macagentic-read-file chart.png"}',
                }],
                "extra": {"actions": [{
                    "command": "macagentic-read-file chart.png",
                    "tool_call_id": "call-1",
                }]},
            }
        if self.calls == 2:
            assert messages[-1]["output"][0]["type"] == CONTEXT_FILE_TYPE
            raise ValueError("unsupported image")
        assert "unsupported image" in messages[-1]["output"]
        return text_response("I will use another approach.")

    def format_observation_messages(self, _response, _outputs):
        return [{
            "type": "function_call_output",
            "call_id": "call-1",
            "output": [{
                "type": CONTEXT_FILE_TYPE,
                "path": "context/001-chart.png",
            }],
        }]


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


@pytest.mark.parametrize("render_markdown", [False, True])
def test_prompt_placeholders_and_conditionals_are_resolved(
    render_markdown: bool,
) -> None:
    prompt = load_system_prompt(render_markdown=render_markdown)

    assert "{{CUSTOM_INSTRUCTIONS}}" not in prompt
    assert "{{TOOLS}}" not in prompt
    assert "{{SKILLS}}" not in prompt
    assert "{{FILESYSTEM}}" not in prompt
    assert "{{#if render_markdown}}" not in prompt
    assert "{{else}}" not in prompt
    assert "{{/if}}" not in prompt


def test_custom_and_tool_instructions_are_inserted() -> None:
    prompt = load_system_prompt(
        "Always answer briefly.",
        "### `things`\n\nUse `things list`.",
    )

    assert "Always answer briefly." in prompt
    assert "### `things`\n\nUse `things list`." in prompt


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


def test_observation_with_non_object_json_output_is_kept_as_text() -> None:
    model = ResponseModel(model_name="openai/fake", context_root=None)
    response = {
        "extra": {
            "actions": [
                {"command": "wc -l < file", "tool_call_id": "call-1"},
                {"command": "test -f x", "tool_call_id": "call-2"},
            ]
        }
    }
    outputs = [
        {"output": "42\n", "returncode": 0, "exception_info": ""},
        {"output": "true\n", "returncode": 0, "exception_info": ""},
    ]

    observations = model.format_observation_messages(response, outputs)

    assert [o["call_id"] for o in observations] == ["call-1", "call-2"]
    assert all(isinstance(o["output"], str) for o in observations)


def test_response_model_materializes_context_files(tmp_path: Path) -> None:
    context = tmp_path / "context"
    context.mkdir()
    (context / "001-chart.png").write_bytes(b"image")
    (context / "002-report.pdf").write_bytes(b"%PDF")
    model = ResponseModel(model_name="openai/fake", context_root=tmp_path)
    response = {"extra": {"actions": [
        {"command": "read", "tool_call_id": "image"},
        {"command": "read", "tool_call_id": "pdf"},
    ]}}
    outputs = [
        {"output": '{"macagentic_context_file":"context/001-chart.png"}',
         "returncode": 0, "exception_info": ""},
        {"output": '{"macagentic_context_file":"context/002-report.pdf"}',
         "returncode": 0, "exception_info": ""},
    ]

    observations = model.format_observation_messages(response, outputs)
    prepared = model._prepare_messages_for_api(observations)

    image = prepared[0]["output"][0]
    pdf = prepared[1]["output"][0]
    assert image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/png;base64,")
    assert pdf["type"] == "input_file"
    assert pdf["file_data"].startswith("data:application/pdf;base64,")


def test_response_model_registers_missing_mercury_metadata(monkeypatch) -> None:
    registered = []

    def missing_info(_model):
        raise ValueError("not registered")

    monkeypatch.setattr(
        "macagentic.agent.model.litellm.get_model_info",
        missing_info,
    )
    monkeypatch.setattr(
        "macagentic.agent.model.litellm.register_model",
        registered.append,
    )

    model = ResponseModel(model_name=MERCURY_2_5)

    assert model.model_name == MERCURY_2_5
    assert registered == [{MERCURY_2_5: MERCURY_2_5_METADATA}]


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


def test_agent_switches_model_tier_from_slash_command(
    tmp_path: Path,
) -> None:
    agent = make_agent(
        tmp_path,
        ui=None,
        model_name="openai/gpt-5.6-terra",
        model_presets={
            "fast": "openai/gpt-5.6-luna",
            "medium": "openai/gpt-5.6-terra",
            "slow": "openai/gpt-5.6-sol",
        },
    )
    agent.model = FakeModel("openai/gpt-5.6-terra")

    agent.run_turn("/fast hello there")

    assert agent.model_name == "openai/gpt-5.6-luna"
    assert [
        event.payload
        for event in agent.conversation_log.snapshot()
        if event.kind == "model_switch"
    ] == [{"model": "openai/gpt-5.6-luna"}]
    assert [
        event.payload
        for event in agent.conversation_log.snapshot()
        if event.kind == "user_input"
    ] == [{"content": "hello there"}]
    assert agent.messages[-2]["content"] == "hello there"


def test_agent_model_tier_only_does_not_query(
    tmp_path: Path,
) -> None:
    agent = make_agent(
        tmp_path,
        ui=None,
        model_presets={
            "fast": "openai/gpt-5.6-luna",
            "medium": "openai/gpt-5.6-terra",
            "slow": "openai/gpt-5.6-sol",
        },
    )
    model = FakeModel("openai/gpt-5.6-terra")
    agent.model = model
    calls = {"n": 0}
    original_query = model.query

    def counting_query(messages):
        calls["n"] += 1
        return original_query(messages)

    model.query = counting_query  # type: ignore[method-assign]

    agent.run_turn("/medium")

    assert agent.model_name == "openai/gpt-5.6-terra"
    assert calls["n"] == 0
    assert not any(
        event.kind == "user_input"
        for event in agent.conversation_log.snapshot()
    )
    assert any(
        event.kind == "model_switch"
        for event in agent.conversation_log.snapshot()
    )


def test_set_model_tier_does_not_announce_or_create_user_turn(
    tmp_path: Path,
) -> None:
    agent = make_agent(
        tmp_path,
        ui=None,
        model_presets={
            "fast": "openai/gpt-5.6-luna",
            "medium": "openai/gpt-5.6-terra",
            "slow": "openai/gpt-5.6-sol",
        },
    )
    agent.model = FakeModel("openai/gpt-5.6-terra")

    agent.set_model_tier("slow")

    assert agent.model_name == "openai/gpt-5.6-sol"
    kinds = [event.kind for event in agent.conversation_log.snapshot()]
    assert "model_switch" not in kinds
    assert "user_input" not in kinds


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


def test_agent_returns_provider_file_rejection_to_model(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, ui=None)
    model = RejectingFileModel()
    agent.model = model
    agent.tool_runner = FakeToolRunner()

    agent.run_turn("Read chart.png")

    assert model.calls == 3
    assert agent.messages[-1]["output"][0]["content"][0]["text"] == (
        "I will use another approach."
    )
    assert any(
        event.kind == "discarded_message"
        for event in agent.conversation_log.snapshot()
    )


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


def test_response_update_already_includes_recorded_usage(
    tmp_path: Path,
) -> None:
    agent = make_agent(tmp_path, ui=None)
    agent.model = FakeModel()
    agent.model.query = lambda _messages: text_response(
        "Done.",
        usage={"input_tokens": 120, "output_tokens": 15},
        cost=0.125,
    )
    observed = []

    class RecordingUI:
        def update(self) -> None:
            observed.append(
                (
                    len(agent.conversation_log.snapshot()),
                    agent.usage.snapshot().cost,
                )
            )

    agent.ui = RecordingUI()
    agent.run_turn("Track it")

    usage_updates = [entry for entry in observed if entry[1] == 0.125]
    assert usage_updates == [(4, 0.125)]


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


def test_tool_step_failure_leaves_no_dangling_tool_call(
    tmp_path: Path,
) -> None:
    class FailingToolRunner(FakeToolRunner):
        def execute(self, _action):
            raise RuntimeError("tool step exploded")

    agent = make_agent(tmp_path, ui=None)
    agent.model = ToolModel()
    agent.tool_runner = FailingToolRunner()

    with pytest.raises(RuntimeError, match="tool step exploded"):
        agent.run_turn("Run it")

    assert not agent.messages[-1].get("extra", {}).get("actions")
    kinds = [event.kind for event in agent.conversation_log.snapshot()]
    assert "discarded_message" in kinds
    assert "interrupted" not in kinds

    agent.tool_runner = FakeToolRunner()
    agent.run_turn("Try again")
    assert agent.messages[-1]["output"][0]["content"][0]["text"] == "Done."


def test_restored_messages_get_outputs_for_orphaned_tool_calls(
    tmp_path: Path,
) -> None:
    messages = [
        {"role": "system", "content": "Instructions"},
        {"role": "user", "content": "Count lines"},
        {
            "object": "response",
            "output": [
                {"type": "reasoning", "id": "rs-1"},
                {
                    "type": "function_call",
                    "call_id": "call-lost",
                    "name": "bash",
                    "arguments": '{"command":"wc -l < f"}',
                },
            ],
            "extra": {"actions": [{"command": "wc -l < f", "tool_call_id": "call-lost"}]},
        },
        {"role": "user", "content": "Are you still there?"},
        {
            "object": "response",
            "output": [{
                "type": "function_call",
                "call_id": "call-ok",
                "name": "bash",
                "arguments": '{"command":"true"}',
            }],
            "extra": {"actions": []},
        },
        {"type": "function_call_output", "call_id": "call-ok", "output": "{}"},
    ]

    agent = make_agent(tmp_path, messages=messages, conversation_log=ConversationLog())

    types = [m.get("type") or m.get("role") or m.get("object") for m in agent.messages]
    assert types == [
        "system", "user", "response", "function_call_output",
        "user", "response", "function_call_output",
    ]
    inserted = agent.messages[3]
    assert inserted["call_id"] == "call-lost"
    assert "lost" in inserted["output"]
    assert agent.conversation_log.records() == [
        {"kind": "message", "payload": inserted}
    ]


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

from __future__ import annotations

import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Protocol

import yaml
from minisweagent import package_dir

from macagentic.agent.conversation_log import ConversationLog
from macagentic.agent.model import ResponseModel
from macagentic.agent.shell import ShellEnvironment
from macagentic.agent.skills import EMPTY_SKILL_CATALOG, SkillCatalog
from macagentic.agent.usage import UsageTracker

DEFAULT_PROMPT_PATH = Path(__file__).parent / "prompts" / "default.md"
CUSTOM_INSTRUCTIONS_PLACEHOLDER = "{{CUSTOM_INSTRUCTIONS}}"
TOOLS_PLACEHOLDER = "{{TOOLS}}"
SKILLS_PLACEHOLDER = "{{SKILLS}}"


class UI(Protocol):
    def update(self) -> None: ...


def load_system_prompt(
    custom_instructions: str | None = None,
    tool_instructions: str | None = None,
    skill_catalog: SkillCatalog | None = None,
) -> str:
    prompt = DEFAULT_PROMPT_PATH.read_text()
    missing = [
        name
        for name, placeholder in (
            ("custom instructions", CUSTOM_INSTRUCTIONS_PLACEHOLDER),
            ("tools", TOOLS_PLACEHOLDER),
            ("skills", SKILLS_PLACEHOLDER),
        )
        if placeholder not in prompt
    ]
    if missing:
        raise ValueError(
            "System prompt missing placeholder(s): "
            + ", ".join(missing)
        )
    return (
        prompt.replace(
            CUSTOM_INSTRUCTIONS_PLACEHOLDER,
            (custom_instructions or "").strip(),
        ).replace(
            TOOLS_PLACEHOLDER,
            (tool_instructions or "").strip(),
        ).replace(
            SKILLS_PLACEHOLDER,
            (skill_catalog or EMPTY_SKILL_CATALOG).render_prompt(),
        )
    )


class Agent:
    # Dependencies
    workspace: Path
    model: ResponseModel
    tool_runner: ShellEnvironment
    skill_catalog: SkillCatalog

    # Conversation state
    messages: list[dict]
    conversation_log: ConversationLog
    usage: UsageTracker

    # Execution
    interrupted: threading.Event

    # UI
    ui: UI | None

    def __init__(
        self,
        workspace: Path,
        model_name: str | None = None,
        *,
        ui: UI | None = None,
        custom_instructions: str | None = None,
        tool_instructions: str | None = None,
        skill_catalog: SkillCatalog | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.skill_catalog = skill_catalog or EMPTY_SKILL_CATALOG
        self.conversation_log = ConversationLog()
        self.usage = UsageTracker()
        self.ui = ui
        self.interrupted = threading.Event()

        config = yaml.safe_load(
            (Path(package_dir) / "config" / "mini.yaml").read_text()
        )
        selected_model = model_name or os.getenv(
            "MSWEA_MODEL_NAME", "openai/gpt-5-mini"
        )
        self.model = ResponseModel(
            **(config["model"] | {"model_name": selected_model})
        )
        self.tool_runner = ShellEnvironment(
            **(config["environment"] | {"cwd": str(self.workspace)})
        )
        self.messages: list[dict] = []
        self._append_message(
            {
                "role": "system",
                "content": load_system_prompt(
                    custom_instructions,
                    tool_instructions,
                    self.skill_catalog,
                ),
            }
        )

    @property
    def model_name(self) -> str:
        return self.model.model_name

    def update_ui(self) -> None:
        if self.ui is not None:
            self.ui.update()

    def run_turn(self, request: str) -> None:
        request = request.strip()
        if not request:
            return

        self.interrupted.clear()
        self.conversation_log.append(
            "user_input",
            {"content": request},
        )
        self.update_ui()
        expanded_request = self.skill_catalog.expand_commands(request)
        self._append_message(
            {"role": "user", "content": expanded_request}
        )

        try:
            self._run_agent_turn()
        finally:
            if self.interrupted.is_set():
                self._discard_incomplete_tool_call()
                self.conversation_log.append(
                    "interrupted",
                    {"request": request},
                )
                self.update_ui()

    def interrupt(self) -> None:
        self.interrupted.set()
        self.tool_runner.interrupt()

    def _run_agent_turn(self) -> None:
        for _ in range(20):
            if self.interrupted.is_set():
                return

            response = self._query_model()
            if response is None or self.interrupted.is_set():
                return

            self._append_message(response)
            actions = response["extra"]["actions"]
            if not actions:
                return

            outputs = []
            for action in actions:
                if self.interrupted.is_set():
                    return
                output = self.tool_runner.execute(action)
                self.conversation_log.append(
                    "tool_execution",
                    {"action": action, "output": output},
                )
                self.update_ui()
                if self.interrupted.is_set():
                    return
                outputs.append(output)

            for observation in self.model.format_observation_messages(
                response,
                outputs,
            ):
                self._append_message(observation)

        raise RuntimeError("Agent exceeded 20 consecutive tool-call rounds.")

    def _query_model(self) -> dict | None:
        completed = threading.Event()
        responses: list[dict] = []
        errors: list[BaseException] = []
        messages = deepcopy(self.messages)

        def query() -> None:
            try:
                response = self.model.query(messages)
                responses.append(response)
                if self.usage.add_response(response) is not None:
                    self.update_ui()
            except BaseException as error:
                errors.append(error)
            finally:
                completed.set()

        threading.Thread(
            target=query,
            name="macagentic-model-query",
            daemon=True,
        ).start()

        while not completed.wait(0.05):
            if self.interrupted.is_set():
                return None
        if self.interrupted.is_set():
            return None
        if errors:
            raise errors[0]
        return responses[0]

    def _append_message(self, message: dict) -> None:
        self.messages.append(message)
        self.conversation_log.append_message(message)
        self.update_ui()

    def _discard_incomplete_tool_call(self) -> None:
        if not self.messages:
            return
        last = self.messages[-1]
        if last.get("extra", {}).get("actions"):
            discarded = self.messages.pop()
            self.conversation_log.append(
                "discarded_message",
                discarded,
            )

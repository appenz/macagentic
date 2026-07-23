import os
import signal
import threading
from collections.abc import Callable
from pathlib import Path

import yaml
from minisweagent import package_dir
from minisweagent.models.litellm_response_model import LitellmResponseModel
from minisweagent.models.utils.openai_multimodal import (
    DEFAULT_MULTIMODAL_REGEX,
    expand_multimodal_content,
)

from macagentic.agent.environment import InterruptibleLocalEnvironment
from macagentic.agent.transcript import Transcript
from macagentic.agent.usage import UsageAccumulator, UsageSnapshot

DEFAULT_PROMPT_PATH = Path(__file__).parent / "prompts" / "default.md"

PermissionCallback = Callable[[str], bool]
ClarificationCallback = Callable[[str], str | None]
OutputCallback = Callable[[str], None]
ToolOutputCallback = Callable[[str], None]
UsageCallback = Callable[[UsageSnapshot], None]


class ConsoleInterrupt(BaseException):
    """SIGINT marker that third-party retry loops must not swallow."""


class ResponseModel(LitellmResponseModel):
    """Allow ordinary assistant replies as well as optional bash calls."""

    def _parse_actions(self, response) -> list[dict]:
        if not any(
            _value(item, "type") == "function_call"
            for item in (_value(response, "output") or [])
        ):
            return []
        return super()._parse_actions(response)

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]:
        msgs = super().format_observation_messages(message, outputs, template_vars)
        return expand_multimodal_content(msgs, pattern=self.config.multimodal_regex)


def load_system_prompt(
    custom_instructions: str | None = None,
    tool_instructions: str | None = None,
) -> str:
    base_prompt = DEFAULT_PROMPT_PATH.read_text()
    sections = []
    if custom_instructions and custom_instructions.strip():
        sections.append(
            "## Custom Instructions\n\n"
            f"{custom_instructions.strip()}"
        )
    if tool_instructions and tool_instructions.strip():
        sections.append(tool_instructions.strip())
    if not sections:
        return base_prompt
    return (
        f"{base_prompt.rstrip()}\n\n"
        + "\n\n".join(sections)
        + "\n"
    )


class Control:
    """Runs one conversation without depending on any UI implementation."""

    def __init__(
        self,
        workspace: Path,
        model_name: str | None = None,
        *,
        transcript: Transcript | None = None,
        on_output: OutputCallback | None = None,
        on_tool_output: ToolOutputCallback | None = None,
        on_usage: UsageCallback | None = None,
        show_tool_output: bool = False,
        ask_permission: PermissionCallback | None = None,
        ask_clarification: ClarificationCallback | None = None,
        custom_instructions: str | None = None,
        tool_instructions: str | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.model_name = model_name or os.getenv(
            "MSWEA_MODEL_NAME", "openai/gpt-5-mini"
        )
        self.transcript = transcript or Transcript()
        self.on_output = on_output
        self.on_tool_output = on_tool_output
        self.on_usage = on_usage
        self.show_tool_output = show_tool_output
        self.ask_permission_callback = ask_permission
        self.ask_clarification_callback = ask_clarification

        config = yaml.safe_load(
            (Path(package_dir) / "config" / "mini.yaml").read_text()
        )
        self.model = ResponseModel(
            **(config["model"] | {
                "model_name": self.model_name,
                "multimodal_regex": DEFAULT_MULTIMODAL_REGEX,
            })
        )
        self.environment = InterruptibleLocalEnvironment(
            **(config["environment"] | {"cwd": str(self.workspace)})
        )
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": load_system_prompt(
                    custom_instructions,
                    tool_instructions,
                ),
            }
        ]
        self.usage = UsageAccumulator()

        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._run_id = 0

    def run_turn(self, user_message: str) -> None:
        user_message = user_message.strip()
        if not user_message:
            return

        with self._run_lock:
            with self._state_lock:
                self._run_id += 1
                run_id = self._run_id
                self._cancel_event.clear()

            self.transcript.write(f"**You:** {user_message}\n\n")
            self.messages.append({"role": "user", "content": user_message})
            self._run_agent_turn(run_id)

    def start(self, first_message: str) -> None:
        previous_handler = signal.getsignal(signal.SIGINT)

        def handle_sigint(_signum, _frame) -> None:
            self.interrupt()
            raise ConsoleInterrupt

        signal.signal(signal.SIGINT, handle_sigint)
        try:
            user_message = first_message
            while True:
                try:
                    self.run_turn(user_message)
                except (KeyboardInterrupt, ConsoleInterrupt):
                    self.interrupt()
                    self._discard_incomplete_tool_call()
                    self.transcript.write("Interrupted.\n\n")
                    print("\nInterrupted.")

                try:
                    user_message = input("\nYou: ").strip()
                except (KeyboardInterrupt, ConsoleInterrupt):
                    self.interrupt()
                    print("\nInterrupted.")
                    continue
                except EOFError:
                    print()
                    return

                if user_message.lower() in {"/exit", "/quit"}:
                    return
                if not user_message:
                    continue
        finally:
            signal.signal(signal.SIGINT, previous_handler)

    def interrupt(self) -> None:
        with self._state_lock:
            self._run_id += 1
            self._cancel_event.set()
        self.environment.interrupt()

    def request_permission(self, prompt: str) -> bool:
        if self.ask_permission_callback is not None:
            return bool(
                self._wait_for_input(self.ask_permission_callback, prompt)
            )
        answer = input(f"{prompt} [y/N] ").strip().lower()
        return answer in {"y", "yes"}

    def request_clarification(self, prompt: str) -> str | None:
        if self.ask_clarification_callback is not None:
            answer = self._wait_for_input(
                self.ask_clarification_callback,
                prompt,
            )
            return answer if isinstance(answer, str) else None
        try:
            return input(f"{prompt}\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

    def _run_agent_turn(self, run_id: int) -> None:
        for _ in range(20):
            if self._is_cancelled(run_id):
                return

            response = self._query_model(run_id)
            if response is None or self._is_cancelled(run_id):
                return

            self.messages.append(response)
            if content := _assistant_text(response):
                self.transcript.write(f"{content}\n\n")
                if self.on_output is not None:
                    self.on_output(content)

            actions = response["extra"]["actions"]
            if not actions:
                return

            outputs = []
            for action in actions:
                if self._is_cancelled(run_id):
                    return
                output = self.environment.execute(action)
                outputs.append(output)
                if self.show_tool_output:
                    rendered = self._format_tool_output(action, output)
                    self.transcript.write(rendered)
                    if self.on_tool_output is not None:
                        self.on_tool_output(rendered)
                if self._is_cancelled(run_id):
                    return

            self.messages.extend(
                self.model.format_observation_messages(response, outputs)
            )

        raise RuntimeError("Agent exceeded 20 consecutive tool-call rounds.")

    @staticmethod
    def _format_tool_output(action: dict, output: dict) -> str:
        command = str(action.get("command", ""))
        content = str(output.get("output", "")).rstrip()
        returncode = output.get("returncode", -1)
        return (
            f"**Tool:** `{command}` (exit {returncode})\n\n"
            f"```text\n{content}\n```\n\n"
        )

    def _query_model(self, run_id: int) -> dict | None:
        completed = threading.Event()
        responses: list[dict] = []
        errors: list[BaseException] = []

        def query() -> None:
            try:
                response = self.model.query(self.messages)
                responses.append(response)
                snapshot = self.usage.add_response(response)
                if snapshot is not None and self.on_usage is not None:
                    self.on_usage(snapshot)
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
            if self._is_cancelled(run_id):
                return None
        if self._is_cancelled(run_id):
            return None
        if errors:
            raise errors[0]
        return responses[0]

    def _is_cancelled(self, run_id: int) -> bool:
        with self._state_lock:
            return self._cancel_event.is_set() or run_id != self._run_id

    def _wait_for_input(
        self,
        callback: Callable[[str], object],
        prompt: str,
    ) -> object | None:
        with self._state_lock:
            run_id = self._run_id

        completed = threading.Event()
        answers: list[object] = []
        errors: list[BaseException] = []

        def wait() -> None:
            try:
                answers.append(callback(prompt))
            except BaseException as error:
                errors.append(error)
            finally:
                completed.set()

        threading.Thread(
            target=wait,
            name="macagentic-input",
            daemon=True,
        ).start()

        while not completed.wait(0.05):
            if self._is_cancelled(run_id):
                return None
        if self._is_cancelled(run_id):
            return None
        if errors:
            raise errors[0]
        return answers[0]

    def _discard_incomplete_tool_call(self) -> None:
        if not self.messages:
            return
        last = self.messages[-1]
        if last.get("extra", {}).get("actions"):
            self.messages.pop()


def _assistant_text(response: dict) -> str | None:
    output = response.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if (
                _value(item, "type") != "message"
                or _value(item, "role") != "assistant"
            ):
                continue
            for block in _value(item, "content") or []:
                if (
                    _value(block, "type") == "output_text"
                    and (text := _value(block, "text"))
                ):
                    parts.append(str(text))
        return "\n\n".join(parts) or None

    content = response.get("content")
    return content if isinstance(content, str) and content else None


def _value(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)

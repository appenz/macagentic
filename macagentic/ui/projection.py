from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from macagentic.agent import ConversationEvent, UsageSnapshot
from macagentic.ui.helpers.assistant_text import assistant_text


def render_conversation(
    events: Iterable[ConversationEvent],
    *,
    tool_call_descriptions: Mapping[str, str] | None = None,
    show_tool_output: bool = False,
) -> str:
    descriptions = tool_call_descriptions or {}
    parts: list[str] = []
    for event in events:
        if event.kind == "user_input":
            content = str(event.payload.get("content", ""))
            parts.append(f"**You:** {content}\n\n")
        elif event.kind == "message":
            message = event.payload
            if content := assistant_text(message):
                parts.append(f"{content}\n\n")
            for action in message.get("extra", {}).get("actions", []):
                call_id = str(action.get("tool_call_id", ""))
                description = descriptions.get(call_id, "Running command")
                parts.append(f"```status\n{description}\n```\n\n")
        elif event.kind == "tool_execution" and show_tool_output:
            action = event.payload.get("action", {})
            output = event.payload.get("output", {})
            command = str(action.get("command", ""))
            content = str(output.get("output", "")).rstrip()
            returncode = output.get("returncode", -1)
            parts.append(
                f"**Tool:** `{command}` (exit {returncode})\n\n"
                f"```text\n{content}\n```\n\n"
            )
        elif event.kind == "interrupted":
            parts.append("Interrupted.\n\n")
        elif event.kind == "model_switch":
            model = display_model_name(str(event.payload.get("model", "")))
            parts.append(f"Switching to {model}\n\n")
    return "".join(parts)


def render_history(events: Iterable[ConversationEvent]) -> str:
    parts = []
    for event in events:
        payload = json.dumps(
            event.payload,
            indent=2,
            default=str,
            sort_keys=True,
        )
        parts.append(
            f"## {event.kind}\n\n```json\n{payload}\n```\n\n"
        )
    return "".join(parts)


def display_model_name(model_name: str) -> str:
    for prefix in ("openai/responses/", "openai/"):
        if model_name.startswith(prefix):
            return model_name.removeprefix(prefix)
    return model_name


def format_usage(snapshot: UsageSnapshot, *, color: bool = False) -> str:
    fields = (
        ("Input", f"{snapshot.input_tokens:,}"),
        ("Cached", f"{snapshot.cached_input_tokens:,}"),
        ("Writes", f"{snapshot.cache_write_tokens:,}"),
        ("Output", f"{snapshot.output_tokens:,}"),
    )
    if not color:
        token_text = "  ".join(
            f"{label}: {value}" for label, value in fields
        )
        return f"Usage  {token_text}  Cost: ${snapshot.cost:.2f}"

    dim = "\033[2m"
    cyan = "\033[36m"
    green = "\033[32m"
    reset = "\033[0m"
    token_text = "  ".join(
        f"{dim}{label}:{reset} {cyan}{value}{reset}"
        for label, value in fields
    )
    return (
        f"{dim}Usage{reset}  {token_text}  "
        f"{dim}Cost:{reset} {green}${snapshot.cost:.2f}{reset}"
    )

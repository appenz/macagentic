from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from macagentic.agent import ConversationEvent, UsageSnapshot
from macagentic.ui.helpers.assistant_text import assistant_text


def render_conversation(
    events: Iterable[ConversationEvent],
    *,
    tool_call_descriptions: Mapping[str, str] | None = None,
    show_tool_status: bool = True,
    show_tool_output: bool = False,
) -> str:
    descriptions = tool_call_descriptions or {}
    parts: list[str] = []
    status_lines: list[str] = []

    def emit(part: str) -> None:
        # Consecutive status lines share one fence so they can be grouped.
        if status_lines:
            grouped = "\n".join(group_status_lines(status_lines))
            parts.append(f"```status\n{grouped}\n```\n\n")
            status_lines.clear()
        if part:
            parts.append(part)

    for event in events:
        if event.kind == "user_input":
            content = str(event.payload.get("content", ""))
            emit(f"**You:** {content}\n\n")
        elif event.kind == "message":
            message = event.payload
            if content := assistant_text(message):
                emit(f"{content}\n\n")
            if show_tool_status:
                for action in message.get("extra", {}).get("actions", []):
                    call_id = str(action.get("tool_call_id", ""))
                    status_lines.append(
                        descriptions.get(call_id, "Running command")
                    )
        elif event.kind == "tool_execution" and show_tool_output:
            action = event.payload.get("action", {})
            output = event.payload.get("output", {})
            command = str(action.get("command", ""))
            content = str(output.get("output", "")).rstrip()
            returncode = output.get("returncode", -1)
            emit(
                f"**Tool:** `{command}` (exit {returncode})\n\n"
                f"```text\n{content}\n```\n\n"
            )
        elif event.kind == "interrupted":
            emit("Interrupted.\n\n")
        elif event.kind == "model_switch":
            model = display_model_name(str(event.payload.get("model", "")))
            emit(f"Switching to {model}\n\n")
    emit("")
    return "".join(parts)


def group_status_lines(lines: list[str]) -> list[str]:
    """Group runs of consecutive lines sharing their first two words.

    The shared prefix becomes a header and each line's remainder hangs below
    it with tree connectors. Lines without a grouping partner are unchanged.
    """
    result: list[str] = []
    i = 0
    while i < len(lines):
        key = _status_group_key(lines[i])
        j = i + 1
        while key and j < len(lines) and _status_group_key(lines[j]) == key:
            j += 1
        if j - i < 2:
            result.append(lines[i])
        else:
            result.append(key)
            for k in range(i, j):
                connector = "└─" if k == j - 1 else "├─"
                result.append(f"{connector} {lines[k][len(key):].strip()}")
        i = j
    return result


def _status_group_key(line: str) -> str:
    words = line.split()
    if len(words) < 3:
        return ""  # Nothing would remain for the subpoint.
    key = " ".join(words[:2])
    if key.count("`") % 2:
        return ""  # Prefix would split a `quoted` span.
    return key


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
    for prefix in ("openai/responses/", "openai/", "anthropic/"):
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

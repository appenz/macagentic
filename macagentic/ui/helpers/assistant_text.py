from __future__ import annotations

from typing import Any


def assistant_text(response: dict) -> str | None:
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

    if response.get("role") != "assistant":
        return None
    content = response.get("content")
    return content if isinstance(content, str) and content else None


def _value(value: object, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)

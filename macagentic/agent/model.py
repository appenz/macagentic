from __future__ import annotations

from typing import Any

from minisweagent.models.litellm_response_model import LitellmResponseModel


class ResponseModel(LitellmResponseModel):
    """Responses API adapter that also accepts ordinary assistant replies."""

    @property
    def model_name(self) -> str:
        return str(self.config.model_name)

    def _parse_actions(self, response) -> list[dict]:
        if not any(
            _value(item, "type") == "function_call"
            for item in (_value(response, "output") or [])
        ):
            return []
        return super()._parse_actions(response)


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

    content = response.get("content")
    return content if isinstance(content, str) and content else None


def _value(value: object, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)

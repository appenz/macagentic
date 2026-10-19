from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

import litellm
from minisweagent.models.litellm_response_model import LitellmResponseModel

CONTEXT_FILE_TYPE = "macagentic_context_file"
# Replaces mini-swe-agent's template, which demands a bash call per response.
FORMAT_ERROR_TEMPLATE = (
    "Tool call error: {{ error }} "
    "`bash` is the only tool; run the Available Tools as shell commands "
    'through it, e.g. {"command": "websearch \\"query\\""}.'
)
MAX_CONTEXT_FILE_BYTES = 20 * 1024 * 1024
MERCURY_3 = "inception/mercury-3"
MERCURY_3_METADATA = {
    "cache_read_input_token_cost": 0.02 / 1_000_000,
    "input_cost_per_token": 0.20 / 1_000_000,
    "litellm_provider": "inception",
    "max_input_tokens": 1_000_000,
    "max_output_tokens": 131_072,
    "max_tokens": 131_072,
    "mode": "chat",
    "output_cost_per_token": 0.70 / 1_000_000,
    "supports_function_calling": True,
    "supports_parallel_function_calling": True,
    "supports_prompt_caching": True,
    "supports_response_schema": True,
    "supports_system_messages": True,
    "supports_tool_choice": True,
}


class ResponseModel(LitellmResponseModel):
    """Responses API adapter that also accepts ordinary assistant replies."""

    def __init__(self, *, context_root: Path | None = None, **kwargs) -> None:
        self.context_root = context_root
        model_name = str(kwargs.get("model_name", ""))
        if model_name == MERCURY_3:
            _register_mercury_metadata()
        super().__init__(**kwargs)

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

    def format_observation_messages(self, message, outputs, template_vars=None):
        observations = super().format_observation_messages(
            message, outputs, template_vars
        )
        for observation, output in zip(observations, outputs):
            path = _context_path(output)
            if path:
                observation["output"] = [
                    {"type": CONTEXT_FILE_TYPE, "path": path}
                ]
        return observations

    def _prepare_messages_for_api(self, messages: list[dict]) -> list[dict]:
        prepared = super()._prepare_messages_for_api(messages)
        for message in prepared:
            output = message.get("output")
            if isinstance(output, list):
                message["output"] = [
                    self._materialize(item)
                    if item.get("type") == CONTEXT_FILE_TYPE else item
                    for item in output
                ]
        return prepared

    def _materialize(self, item: dict) -> dict:
        if self.context_root is None:
            raise ValueError("Context root is unavailable.")
        context = (self.context_root / "context").resolve()
        path = (self.context_root / item["path"]).resolve()
        if not path.is_file() or not path.is_relative_to(context):
            raise ValueError(f"Invalid context file: {item['path']}")
        if path.stat().st_size > MAX_CONTEXT_FILE_BYTES:
            raise ValueError(f"Context file exceeds 20 MiB: {item['path']}")
        mime = mimetypes.guess_type(path.name)[0] or ""
        data = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
        if mime.startswith("image/"):
            return {"type": "input_image", "image_url": data, "detail": "auto"}
        if mime == "application/pdf":
            return {"type": "input_file", "file_data": data, "filename": path.name}
        raise ValueError(f"Unsupported context file: {item['path']}")


def _register_mercury_metadata() -> None:
    try:
        litellm.get_model_info(MERCURY_3)
    except Exception:
        # LiteLLM 1.91 predates Mercury 3. Use Inception's regular (non-launch)
        # pricing until the installed LiteLLM registry includes the model.
        litellm.register_model({MERCURY_3: MERCURY_3_METADATA})


def _context_path(output: dict) -> str | None:
    if output.get("returncode") != 0:
        return None
    try:
        payload = json.loads(output.get("output", ""))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        # Ordinary output such as `42`, `true`, or `[...]` is valid JSON too.
        return None
    path = payload.get("macagentic_context_file")
    return path if isinstance(path, str) else None


def _value(value: object, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)

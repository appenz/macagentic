from __future__ import annotations

from typing import Any

import litellm
from minisweagent.models.litellm_response_model import LitellmResponseModel

MERCURY_2_5 = "inception/mercury-2.5"
MERCURY_2_5_METADATA = {
    "cache_read_input_token_cost": 0.004 / 1_000_000,
    "input_cost_per_token": 0.04 / 1_000_000,
    "litellm_provider": "inception",
    "max_input_tokens": 260_000,
    "max_output_tokens": 65_536,
    "max_tokens": 65_536,
    "mode": "chat",
    "output_cost_per_token": 0.15 / 1_000_000,
    "supports_function_calling": True,
    "supports_parallel_function_calling": True,
    "supports_prompt_caching": True,
    "supports_response_schema": True,
    "supports_system_messages": True,
    "supports_tool_choice": True,
}


class ResponseModel(LitellmResponseModel):
    """Responses API adapter that also accepts ordinary assistant replies."""

    def __init__(self, **kwargs) -> None:
        model_name = str(kwargs.get("model_name", ""))
        if model_name == MERCURY_2_5:
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


def _register_mercury_metadata() -> None:
    try:
        litellm.get_model_info(MERCURY_2_5)
    except Exception:
        # LiteLLM 1.91 predates Mercury 2.5. Use Inception's current launch
        # pricing until the installed LiteLLM registry includes the model.
        litellm.register_model({MERCURY_2_5: MERCURY_2_5_METADATA})


def _value(value: object, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)

import threading
from collections.abc import Callable

import litellm

from macagentic.ui.helpers.assistant_text import assistant_text

FAST_MODEL = "openai/gpt-5.4-nano"


def request_fast_text(
    *,
    system_prompt: str,
    user_prompt: str,
    on_result: Callable[[str], None],
    max_output_tokens: int = 30,
) -> None:
    def run() -> None:
        try:
            response = litellm.responses(
                model=FAST_MODEL,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                reasoning={"effort": "none"},
                max_output_tokens=max_output_tokens,
                timeout=10,
            )
            if hasattr(response, "model_dump"):
                response = response.model_dump()
            if text := assistant_text(response):
                on_result(text)
        except Exception:
            return

    threading.Thread(
        target=run,
        name="macagentic-fast-llm",
        daemon=True,
    ).start()

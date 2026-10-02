import sys
import threading
from collections.abc import Callable

import litellm

from macagentic.ui.helpers.assistant_text import assistant_text

FAST_MODEL = "openai/gpt-5.4-nano"
MAX_ERROR_CHARS = 200


def one_line_error(error: BaseException) -> str:
    """Collapse an exception to one bounded line; LiteLLM embeds JSON bodies."""
    text = " ".join(f"{type(error).__name__}: {error}".split())
    if len(text) > MAX_ERROR_CHARS:
        text = text[: MAX_ERROR_CHARS - 3] + "..."
    return text


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
        except Exception as error:
            print(
                f"Fast model {FAST_MODEL} failed: {one_line_error(error)}",
                file=sys.stderr,
            )

    threading.Thread(
        target=run,
        name="macagentic-fast-llm",
        daemon=True,
    ).start()

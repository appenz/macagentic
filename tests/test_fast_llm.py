import threading

from macagentic.ui.helpers import fast_llm
from macagentic.ui.helpers.fast_llm import MAX_ERROR_CHARS, one_line_error


def test_one_line_error_collapses_whitespace_and_names_type() -> None:
    error = ValueError('Rate limit\n{\n  "error": {\n    "code": 429\n  }\n}')
    assert one_line_error(error) == 'ValueError: Rate limit { "error": { "code": 429 } }'


def test_one_line_error_truncates_long_messages() -> None:
    text = one_line_error(RuntimeError("x" * 1000))
    assert len(text) == MAX_ERROR_CHARS
    assert text.endswith("...")
    assert "\n" not in text


def test_request_fast_text_reports_failure_on_one_stderr_line(
    monkeypatch, capsys
) -> None:
    done = threading.Event()

    def failing_responses(**_kwargs):
        try:
            raise TimeoutError("Request timed out\nafter 10 seconds")
        finally:
            done.set()

    monkeypatch.setattr(fast_llm.litellm, "responses", failing_responses)
    results: list[str] = []
    fast_llm.request_fast_text(
        system_prompt="s", user_prompt="u", on_result=results.append
    )
    assert done.wait(5)
    for thread in threading.enumerate():
        if thread.name == "macagentic-fast-llm":
            thread.join(5)

    captured = capsys.readouterr()
    assert results == []
    assert captured.out == ""
    lines = captured.err.splitlines()
    assert lines == [
        f"Fast model {fast_llm.FAST_MODEL} failed: "
        "TimeoutError: Request timed out after 10 seconds"
    ]

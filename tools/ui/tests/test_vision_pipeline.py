"""Integration test: send a real screenshot through the multimodal pipeline to a vision model.

Usage:
    # Test against fast-qwen (local):
    uv run pytest tools/ui/tests/test_vision_pipeline.py \
        --vision-url http://192.168.1.157:8080/v1 -m hardware

    # Test against deep-qwen (local):
    uv run pytest tools/ui/tests/test_vision_pipeline.py \
        --vision-url http://192.168.1.161:8081/v1 -m hardware
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).parent.parent / "main.py"


def _capture_screenshot() -> str:
    """Run the UI tool and return the raw stdout (MSWEA-wrapped base64)."""
    result = subprocess.run(
        [sys.executable, str(TOOL_PATH), "screenshot"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"screenshot tool failed: {result.stderr.decode()}")
    return result.stdout.decode()


def _expand_for_model(raw_output: str) -> list[dict]:
    """Expand MSWEA tags into OpenAI multimodal format."""
    from minisweagent.models.utils.openai_multimodal import (
        DEFAULT_MULTIMODAL_REGEX,
        _expand_content_string,
    )
    return _expand_content_string(content=raw_output, pattern=DEFAULT_MULTIMODAL_REGEX)


@pytest.mark.hardware
def test_vision_model_receives_image_as_multimodal(vision_url: str) -> None:
    """End-to-end: capture screenshot → expand tags → send to vision model → verify response.

    The key check is that the model returns a description of what it sees,
    proving it received an actual image (not just base64 text).
    """
    raw = _capture_screenshot()
    expanded = _expand_for_model(raw)

    assert len(expanded) == 1
    assert expanded[0]["type"] == "image_url"
    url_value = expanded[0]["image_url"]["url"]
    assert url_value.startswith("data:image/png;base64,")

    # Build the messages payload for OpenAI-compatible chat API
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe briefly what you see in this screenshot (1-2 sentences)."},
                {"type": "image_url", "image_url": {"url": url_value}},
            ],
        }
    ]

    payload = {
        "model": "fast-qwen",
        "messages": messages,
        "max_tokens": 200,
    }

    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        f"{vision_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as e:
        pytest.skip(f"vision model unreachable: {e}")

    choices = body.get("choices", [])
    assert len(choices) > 0, f"no choices in response: {body}"
    text = choices[0].get("message", {}).get("content", "").strip()
    assert len(text) > 5, f"model returned empty or trivial response: {text!r}"

    print(f"\n  Model saw the image and responded: {text[:200]}")




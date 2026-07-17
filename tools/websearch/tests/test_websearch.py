from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError


TOOL_PATH = Path(__file__).parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("websearch_tool", TOOL_PATH)
assert SPEC and SPEC.loader
websearch_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(websearch_tool)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _brave_payload(results: list[dict] | None = None) -> dict:
    return {
        "web": {
            "results": results
            if results is not None
            else [
                {
                    "title": "Example Result",
                    "url": "https://example.com",
                    "description": "An example snippet.",
                },
                {
                    "title": "Second Result",
                    "url": "https://example.org",
                    "description": "Another snippet.",
                },
            ]
        }
    }


def test_websearch_prints_results(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return FakeResponse(_brave_payload())

    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(websearch_tool.urllib.request, "urlopen", fake_urlopen)

    assert websearch_tool.main(["python tutorials"]) == 0
    output = capsys.readouterr().out
    assert "1. Example Result" in output
    assert "https://example.com" in output
    assert "An example snippet." in output
    assert "2. Second Result" in output
    assert "count=5" in str(captured["url"])
    assert "result_filter=web" in str(captured["url"])
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["x-subscription-token"] == "test-key"


def test_websearch_respects_count(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        return FakeResponse(_brave_payload([]))

    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(websearch_tool.urllib.request, "urlopen", fake_urlopen)

    assert websearch_tool.main(["query", "--count", "10"]) == 0
    assert "count=10" in str(captured["url"])


def test_websearch_rejects_invalid_count(capsys) -> None:
    assert websearch_tool.main(["query", "--count", "0"]) == 2
    assert "between 1 and 20" in capsys.readouterr().err


def test_websearch_requires_api_key(monkeypatch, capsys) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr(
        websearch_tool,
        "_brave_api_key_from_config",
        lambda: "",
    )
    assert websearch_tool.main(["query"]) == 1
    assert "brave_api_key is not set" in capsys.readouterr().err


def test_websearch_loads_key_from_config(monkeypatch, capsys) -> None:
    def fake_urlopen(request, timeout=30):
        headers = {key.lower(): value for key, value in request.header_items()}
        assert headers["x-subscription-token"] == "config-key"
        return FakeResponse(_brave_payload([]))

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr(
        websearch_tool,
        "_brave_api_key_from_config",
        lambda: "config-key",
    )
    monkeypatch.setattr(websearch_tool.urllib.request, "urlopen", fake_urlopen)

    assert websearch_tool.main(["query"]) == 0
    assert capsys.readouterr().out.strip() == "No results found."


def test_websearch_prefers_env_over_config(monkeypatch) -> None:
    captured = SimpleNamespace(token="")

    def fake_urlopen(request, timeout=30):
        headers = {key.lower(): value for key, value in request.header_items()}
        captured.token = headers["x-subscription-token"]
        return FakeResponse(_brave_payload([]))

    monkeypatch.setenv("BRAVE_API_KEY", "env-key")
    monkeypatch.setattr(
        websearch_tool,
        "_brave_api_key_from_config",
        lambda: "config-key",
    )
    monkeypatch.setattr(websearch_tool.urllib.request, "urlopen", fake_urlopen)

    assert websearch_tool.main(["query"]) == 0
    assert captured.token == "env-key"


def test_websearch_reports_http_error(monkeypatch, capsys) -> None:
    def fake_urlopen(request, timeout=30):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"invalid token"),
        )

    monkeypatch.setenv("BRAVE_API_KEY", "bad-key")
    monkeypatch.setattr(websearch_tool.urllib.request, "urlopen", fake_urlopen)

    assert websearch_tool.main(["query"]) == 1
    err = capsys.readouterr().err
    assert "Brave Search API error (401)" in err
    assert "invalid token" in err
    assert "bad-key" not in err


def test_websearch_reports_network_error(monkeypatch, capsys) -> None:
    def fake_urlopen(request, timeout=30):
        raise URLError("timed out")

    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(websearch_tool.urllib.request, "urlopen", fake_urlopen)

    assert websearch_tool.main(["query"]) == 1
    assert "Brave Search request failed" in capsys.readouterr().err


def test_websearch_empty_results(monkeypatch, capsys) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(
        websearch_tool.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(_brave_payload([])),
    )

    assert websearch_tool.main(["obscure query"]) == 0
    assert capsys.readouterr().out.strip() == "No results found."


def test_websearch_rejects_empty_query(capsys) -> None:
    assert websearch_tool.main(["   "]) == 2
    assert "query must not be empty" in capsys.readouterr().err

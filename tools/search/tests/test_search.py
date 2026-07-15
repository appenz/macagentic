from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError


TOOL_PATH = Path(__file__).parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("search_tool", TOOL_PATH)
assert SPEC and SPEC.loader
search_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(search_tool)


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


def test_search_prints_results(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return FakeResponse(_brave_payload())

    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(search_tool.urllib.request, "urlopen", fake_urlopen)

    assert search_tool.main(["python tutorials"]) == 0
    output = capsys.readouterr().out
    assert "1. Example Result" in output
    assert "https://example.com" in output
    assert "An example snippet." in output
    assert "2. Second Result" in output
    assert "count=5" in str(captured["url"])
    assert "result_filter=web" in str(captured["url"])
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["x-subscription-token"] == "test-key"


def test_search_respects_count(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        return FakeResponse(_brave_payload([]))

    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(search_tool.urllib.request, "urlopen", fake_urlopen)

    assert search_tool.main(["query", "--count", "10"]) == 0
    assert "count=10" in str(captured["url"])


def test_search_rejects_invalid_count(capsys) -> None:
    assert search_tool.main(["query", "--count", "0"]) == 2
    assert "between 1 and 20" in capsys.readouterr().err


def test_search_requires_api_key(monkeypatch, capsys) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert search_tool.main(["query"]) == 1
    assert "BRAVE_API_KEY is not set" in capsys.readouterr().err


def test_search_reports_http_error(monkeypatch, capsys) -> None:
    def fake_urlopen(request, timeout=30):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"invalid token"),
        )

    monkeypatch.setenv("BRAVE_API_KEY", "bad-key")
    monkeypatch.setattr(search_tool.urllib.request, "urlopen", fake_urlopen)

    assert search_tool.main(["query"]) == 1
    err = capsys.readouterr().err
    assert "Brave Search API error (401)" in err
    assert "invalid token" in err
    assert "bad-key" not in err


def test_search_reports_network_error(monkeypatch, capsys) -> None:
    def fake_urlopen(request, timeout=30):
        raise URLError("timed out")

    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(search_tool.urllib.request, "urlopen", fake_urlopen)

    assert search_tool.main(["query"]) == 1
    assert "Brave Search request failed" in capsys.readouterr().err


def test_search_empty_results(monkeypatch, capsys) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.setattr(
        search_tool.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(_brave_payload([])),
    )

    assert search_tool.main(["obscure query"]) == 0
    assert capsys.readouterr().out.strip() == "No results found."


def test_search_rejects_empty_query(capsys) -> None:
    assert search_tool.main(["   "]) == 2
    assert "query must not be empty" in capsys.readouterr().err

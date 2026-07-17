# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Search the web with the Brave Search API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_COUNT = 5
MIN_COUNT = 1
MAX_COUNT = 20
COMMAND_HELP = """websearch - Web search via Brave Search
Usage:
  websearch "<query>"
  websearch "<query>" --count 10"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the web with Brave Search",
        add_help=True,
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"Number of results to return ({MIN_COUNT}-{MAX_COUNT})",
    )
    return parser.parse_args(argv)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _brave_api_key_from_config() -> str:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from macagentic.config import load_config

    return load_config(root).brave_api_key.strip()


def _api_key() -> str:
    env_key = os.environ.get("BRAVE_API_KEY", "").strip()
    if env_key:
        return env_key
    return _brave_api_key_from_config()


def _search(query: str, count: int, api_key: str) -> list[dict[str, str]]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "count": str(count),
            "result_filter": "web",
        }
    )
    request = urllib.request.Request(
        f"{BRAVE_SEARCH_URL}?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        message = f"Brave Search API error ({error.code})"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Brave Search request failed: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Brave Search returned invalid JSON.") from error

    return _results_from_payload(payload)


def _results_from_payload(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        raise RuntimeError("Brave Search returned an unexpected response.")
    web = payload.get("web")
    if web is None:
        return []
    if not isinstance(web, dict):
        raise RuntimeError("Brave Search returned malformed web results.")
    results = web.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError("Brave Search returned malformed web results.")

    formatted: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title and not url:
            continue
        formatted.append(
            {
                "title": title or "(untitled)",
                "url": url or "(no url)",
                "description": description,
            }
        )
    return formatted


def _print_results(results: list[dict[str, str]]) -> None:
    if not results:
        print("No results found.")
        return
    for index, result in enumerate(results, start=1):
        if index > 1:
            print()
        print(f"{index}. {result['title']}")
        print(f"   {result['url']}")
        if result["description"]:
            print(f"   {result['description']}")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(COMMAND_HELP)
        return 0

    try:
        args = parse_args(arguments)
    except SystemExit as error:
        code = error.code
        return int(code) if isinstance(code, int) else 2

    query = args.query.strip()
    if not query:
        print("error: query must not be empty", file=sys.stderr)
        return 2
    if args.count < MIN_COUNT or args.count > MAX_COUNT:
        print(
            f"error: --count must be between {MIN_COUNT} and {MAX_COUNT}",
            file=sys.stderr,
        )
        return 2

    api_key = _api_key()
    if not api_key:
        print(
            "error: brave_api_key is not set. "
            "Add it to ~/.config/macagentic/config.toml "
            "or export BRAVE_API_KEY.",
            file=sys.stderr,
        )
        return 1

    try:
        results = _search(query, args.count, api_key)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    _print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

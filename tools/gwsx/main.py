#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Run Google Workspace CLI commands against explicit account profiles."""

from __future__ import annotations

import argparse
import base64
import html
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


ACCOUNT_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
RESERVED_NAMES = {"account"}
CONFIG_ENV = "GWSX_CONFIG_DIR"
GWS_CONFIG_ENV = "GOOGLE_WORKSPACE_CLI_CONFIG_DIR"
AUTH_OVERRIDE_ENVS = (
    "GOOGLE_WORKSPACE_CLI_TOKEN",
    "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
    "GOOGLE_APPLICATION_CREDENTIALS",
)
DEFAULT_ACTIVE_QUERY = "is:unread in:inbox"
DEFAULT_ACTIVE_MAX = 50
DEFAULT_MAX_BODY_CHARS = 20_000
DEFAULT_MAX_THREAD_CHARS = 50_000
COMMAND_HELP = """gwsx - Google Workspace CLI with explicit account profiles
Usage:
  gwsx account add <alias>
  gwsx account delete <alias>
  gwsx account list
  gwsx <alias> gmail +active-threads [options]
  gwsx <alias> gmail +thread --id <thread-id> [options]
  gwsx <alias> <gws arguments...>

Examples:
  gwsx account add private
  gwsx account delete private
  gwsx private gmail +active-threads
  gwsx private gmail +thread --id 18f1a2b3c4d
  gwsx private drive files list --params '{"pageSize": 5}'
  gwsx private auth login --scopes drive,gmail
"""


class GwsxError(RuntimeError):
    """Raised for invalid or unsafe gwsx operations."""


def config_root() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "gwsx"


def accounts_root() -> Path:
    return config_root() / "accounts"


def validate_alias(alias: str) -> str:
    if not ACCOUNT_NAME.fullmatch(alias) or alias in RESERVED_NAMES:
        raise GwsxError(
            "Account aliases must start with a lowercase letter and contain "
            "only lowercase letters, digits, and hyphens."
        )
    return alias


def profile_dir(alias: str) -> Path:
    return accounts_root() / validate_alias(alias)


def configured_accounts() -> list[Path]:
    root = accounts_root()
    if not root.is_dir():
        return []
    return sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir()
            and ACCOUNT_NAME.fullmatch(path.name)
            and path.name not in RESERVED_NAMES
        ),
        key=lambda path: path.name,
    )


def find_gws() -> str:
    executable = shutil.which("gws")
    if executable is None:
        raise GwsxError(
            "The gws command is not installed or is not on PATH. "
            "Install it with 'brew install googleworkspace-cli'."
        )
    return executable


def _dotenv_auth_overrides(start: Path | None = None) -> list[str]:
    """Return account-bypassing variables set by gws's nearest .env file."""
    directory = (start or Path.cwd()).resolve()
    candidates = [directory, *directory.parents]
    for parent in candidates:
        dotenv = parent / ".env"
        if not dotenv.is_file():
            continue
        try:
            contents = dotenv.read_text()
        except OSError:
            return []

        found: list[str] = []
        for line in contents.splitlines():
            match = re.match(
                r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=",
                line,
            )
            if match and match.group(1) in AUTH_OVERRIDE_ENVS:
                found.append(match.group(1))
        return sorted(set(found))
    return []


def profile_environment(profile: Path) -> dict[str, str]:
    dotenv_overrides = _dotenv_auth_overrides()
    if dotenv_overrides:
        names = ", ".join(dotenv_overrides)
        raise GwsxError(
            f"The nearest .env sets {names}, which would override the selected "
            "gwsx account. Remove those settings before using gwsx."
        )

    env = os.environ.copy()
    for name in AUTH_OVERRIDE_ENVS:
        env.pop(name, None)
    env[GWS_CONFIG_ENV] = str(profile)
    return env


def rewrite_arguments(arguments: list[str]) -> list[str]:
    """Translate future gwsx convenience commands into ordinary gws arguments."""
    return list(arguments)


def run_gws(
    arguments: list[str],
    profile: Path,
    *,
    executable: str | None = None,
) -> int:
    command = executable or find_gws()
    result = subprocess.run(
        [command, *rewrite_arguments(arguments)],
        env=profile_environment(profile),
        check=False,
    )
    if result.returncode < 0:
        return 128 - result.returncode
    return result.returncode


def invoke_gws_json(
    arguments: list[str],
    profile: Path,
    *,
    executable: str | None = None,
) -> Any:
    """Run gws and parse JSON stdout. Diagnostics may appear on stderr."""
    command = executable or find_gws()
    result = subprocess.run(
        [command, *arguments],
        env=profile_environment(profile),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode < 0:
        raise GwsxError(f"gws terminated by signal {-result.returncode}.")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if detail:
            raise GwsxError(f"gws failed ({result.returncode}): {detail}")
        raise GwsxError(f"gws failed with exit status {result.returncode}.")
    stdout = result.stdout.strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise GwsxError(f"gws returned invalid JSON: {error}") from error


def add_account(alias: str) -> int:
    profile = profile_dir(alias)
    executable = find_gws()
    env = profile_environment(profile)
    if profile.exists():
        raise GwsxError(
            f"Account '{alias}' already exists. "
            f"Re-run setup with 'gwsx {alias} auth setup'."
        )

    profile.mkdir(mode=0o700, parents=True)
    profile.chmod(0o700)
    print(f"Created account '{alias}' at {profile}.", flush=True)
    result = subprocess.run(
        [executable, "auth", "setup"],
        env=env,
        check=False,
    )
    if result.returncode:
        print(
            f"Setup did not complete. The profile was retained; retry with "
            f"'gwsx {alias} auth setup'.",
            file=sys.stderr,
        )
    return result.returncode


def list_accounts() -> int:
    accounts = configured_accounts()
    if not accounts:
        print("No accounts configured. Add one with 'gwsx account add <alias>'.")
        return 0

    for profile in accounts:
        authenticated = any(
            (profile / filename).is_file()
            for filename in ("credentials.enc", "credentials.json")
        )
        status = "authenticated" if authenticated else "setup incomplete"
        print(f"{profile.name}\t{status}")
    return 0


def delete_account(alias: str) -> int:
    profile = profile_dir(alias)
    if profile.is_symlink():
        raise GwsxError(
            f"Refusing to delete account '{alias}' because its profile is a symlink."
        )
    if not profile.is_dir():
        raise GwsxError(f"Unknown account '{alias}'.")

    shutil.rmtree(profile)
    print(f"Deleted account '{alias}' and its local credentials.")
    return 0


def manage_accounts(arguments: list[str]) -> int:
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(
            "Usage:\n"
            "  gwsx account add <alias>\n"
            "  gwsx account delete <alias>\n"
            "  gwsx account list"
        )
        return 0
    if arguments[0] == "add" and len(arguments) == 2:
        return add_account(arguments[1])
    if arguments[0] == "delete" and len(arguments) == 2:
        return delete_account(arguments[1])
    if arguments == ["list"]:
        return list_accounts()
    raise GwsxError(
        "Usage: gwsx account add <alias> | "
        "gwsx account delete <alias> | "
        "gwsx account list"
    )


def truncate_text(text: str, limit: int) -> tuple[str, bool]:
    if limit < 0:
        raise GwsxError("Character limits must be non-negative.")
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def header_map(headers: list[dict[str, str]] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers or []:
        name = header.get("name")
        value = header.get("value")
        if not name or value is None:
            continue
        key = name.casefold()
        if key not in result:
            result[key] = value
    return result


def decode_body_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return raw.decode("utf-8", errors="replace")


class _HTMLToText(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if lowered in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data:
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def html_to_text(content: str) -> str:
    parser = _HTMLToText()
    parser.feed(content)
    parser.close()
    return parser.text()


def _part_is_attachment(part: dict[str, Any]) -> bool:
    filename = part.get("filename")
    if isinstance(filename, str) and filename.strip():
        return True
    headers = header_map(part.get("headers"))
    disposition = headers.get("content-disposition", "").casefold()
    return disposition.startswith("attachment")


def _collect_body_parts(
    part: dict[str, Any] | None,
    plain: list[str],
    rich: list[str],
) -> None:
    if not part:
        return
    if _part_is_attachment(part):
        return

    mime = str(part.get("mimeType") or "").casefold()
    body = part.get("body") or {}
    data = body.get("data")
    if isinstance(data, str) and data:
        decoded = decode_body_data(data)
        if mime == "text/plain":
            plain.append(decoded)
        elif mime == "text/html":
            rich.append(decoded)

    for child in part.get("parts") or []:
        if isinstance(child, dict):
            _collect_body_parts(child, plain, rich)


def extract_body_text(payload: dict[str, Any] | None) -> str:
    plain: list[str] = []
    rich: list[str] = []
    _collect_body_parts(payload, plain, rich)
    if plain:
        return "\n\n".join(chunk.strip() for chunk in plain if chunk.strip()).strip()
    if rich:
        return "\n\n".join(
            html_to_text(chunk) for chunk in rich if chunk.strip()
        ).strip()
    return ""


def message_internal_date(message: dict[str, Any]) -> int:
    value = message.get("internalDate")
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, int):
        return value
    headers = header_map((message.get("payload") or {}).get("headers"))
    date_header = headers.get("date")
    if date_header:
        try:
            return int(parsedate_to_datetime(date_header).timestamp() * 1000)
        except (TypeError, ValueError, IndexError, OverflowError):
            pass
    return 0


def sort_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(messages))
    indexed.sort(key=lambda item: (message_internal_date(item[1]), item[0]))
    return [message for _, message in indexed]


def is_unread(message: dict[str, Any]) -> bool:
    labels = message.get("labelIds") or []
    return "UNREAD" in labels


def select_active_messages(
    messages: list[dict[str, Any]],
    *,
    include_all: bool,
) -> list[dict[str, Any]]:
    ordered = sort_messages(messages)
    if not ordered:
        return []
    if include_all:
        return ordered
    unread_indexes = [
        index for index, message in enumerate(ordered) if is_unread(message)
    ]
    if not unread_indexes:
        return [ordered[-1]]
    return ordered[unread_indexes[0] :]


def normalize_message(
    message: dict[str, Any],
    *,
    max_body_chars: int,
) -> dict[str, Any]:
    payload = message.get("payload") or {}
    headers = header_map(payload.get("headers"))
    labels = list(message.get("labelIds") or [])
    body = extract_body_text(payload)
    original_chars = len(body)
    truncated_body, truncated = truncate_text(body, max_body_chars)
    return {
        "id": message.get("id"),
        "threadId": message.get("threadId"),
        "date": headers.get("date"),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "cc": headers.get("cc"),
        "subject": headers.get("subject") or "(no subject)",
        "unread": "UNREAD" in labels,
        "inbox": "INBOX" in labels,
        "sent": "SENT" in labels,
        "inReplyTo": headers.get("in-reply-to"),
        "references": headers.get("references"),
        "body": truncated_body,
        "bodyChars": original_chars,
        "bodyTruncated": truncated,
    }


def apply_thread_char_budget(
    messages: list[dict[str, Any]],
    *,
    max_thread_chars: int,
) -> list[dict[str, Any]]:
    if max_thread_chars < 0:
        raise GwsxError("Character limits must be non-negative.")
    if not messages:
        return []

    kept_reversed: list[dict[str, Any]] = []
    remaining = max_thread_chars
    for message in reversed(messages):
        body = str(message.get("body") or "")
        body_len = len(body)
        if remaining <= 0:
            omitted = dict(message)
            omitted["body"] = ""
            omitted["bodyTruncated"] = True
            omitted["omittedForBudget"] = True
            kept_reversed.append(omitted)
            continue
        if body_len <= remaining:
            kept_reversed.append(message)
            remaining -= body_len
            continue
        shortened = dict(message)
        shortened["body"] = body[:remaining]
        shortened["bodyTruncated"] = True
        shortened["omittedForBudget"] = False
        kept_reversed.append(shortened)
        remaining = 0

    kept_reversed.reverse()
    return kept_reversed


def format_active_threads_text(threads: list[dict[str, str]]) -> str:
    lines = [f"{thread['id']}\t{thread['snippet']}" for thread in threads]
    return "\n".join(lines) + ("\n" if lines else "")


def format_thread_text(payload: dict[str, Any]) -> str:
    lines = [
        f"threadId: {payload.get('id')}",
        f"selection: {payload.get('selection')}",
        f"messageCount: {len(payload.get('messages') or [])}",
        "",
    ]
    for index, message in enumerate(payload.get("messages") or [], start=1):
        flags = []
        if message.get("unread"):
            flags.append("unread")
        if message.get("inbox"):
            flags.append("inbox")
        if message.get("sent"):
            flags.append("sent")
        if message.get("bodyTruncated"):
            flags.append("truncated")
        if message.get("omittedForBudget"):
            flags.append("budget-omitted")
        flag_text = f" [{', '.join(flags)}]" if flags else ""
        lines.extend(
            [
                f"--- message {index}{flag_text} ---",
                f"id: {message.get('id')}",
                f"date: {message.get('date') or ''}",
                f"from: {message.get('from') or ''}",
                f"to: {message.get('to') or ''}",
                f"cc: {message.get('cc') or ''}",
                f"subject: {message.get('subject') or ''}",
                f"inReplyTo: {message.get('inReplyTo') or ''}",
                f"bodyChars: {message.get('bodyChars')}",
                "",
                str(message.get("body") or ""),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def summarize_active_threads(
    profile: Path,
    *,
    query: str,
    max_results: int,
    executable: str | None = None,
) -> list[dict[str, str]]:
    """List unread-inbox threads with one threads.list call (id + snippet)."""
    params = {
        "userId": "me",
        "q": query,
        "maxResults": max_results,
        "fields": "threads(id,snippet)",
    }
    payload = invoke_gws_json(
        [
            "gmail",
            "users",
            "threads",
            "list",
            "--params",
            json.dumps(params, separators=(",", ":")),
            "--format",
            "json",
        ],
        profile,
        executable=executable,
    )
    summaries: list[dict[str, str]] = []
    for thread in payload.get("threads") or []:
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            continue
        raw_snippet = thread.get("snippet")
        if isinstance(raw_snippet, str) and raw_snippet.strip():
            snippet = html.unescape(raw_snippet.strip())
        else:
            snippet = "(no snippet)"
        summaries.append({"id": thread_id, "snippet": snippet})
    return summaries


def build_thread_view(
    thread: dict[str, Any],
    *,
    include_all: bool,
    max_body_chars: int,
    max_thread_chars: int,
) -> dict[str, Any]:
    raw_messages = [
        message
        for message in (thread.get("messages") or [])
        if isinstance(message, dict)
    ]
    selected = select_active_messages(raw_messages, include_all=include_all)
    normalized = [
        normalize_message(message, max_body_chars=max_body_chars)
        for message in selected
    ]
    budgeted = apply_thread_char_budget(
        normalized,
        max_thread_chars=max_thread_chars,
    )
    selection = "all" if include_all else "oldest-unread-and-later"
    if not include_all and selected and not any(
        is_unread(message) for message in selected
    ):
        selection = "newest-fallback"
    return {
        "id": thread.get("id"),
        "selection": selection,
        "messages": budgeted,
    }


def fetch_full_thread(
    thread_id: str,
    profile: Path,
    *,
    executable: str | None = None,
) -> dict[str, Any]:
    params = {
        "userId": "me",
        "id": thread_id,
        "format": "full",
    }
    return invoke_gws_json(
        [
            "gmail",
            "users",
            "threads",
            "get",
            "--params",
            json.dumps(params, separators=(",", ":")),
            "--format",
            "json",
        ],
        profile,
        executable=executable,
    )


def parse_active_threads_args(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gwsx <account> gmail +active-threads",
        description="List threads containing unread inbox mail.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=DEFAULT_ACTIVE_MAX,
        help=f"Maximum threads to list (default: {DEFAULT_ACTIVE_MAX})",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_ACTIVE_QUERY,
        help=f'Gmail search query (default: "{DEFAULT_ACTIVE_QUERY}")',
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    return parser.parse_args(arguments)


def parse_thread_args(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gwsx <account> gmail +thread",
        description=(
            "Read a thread for reasoning. Default selection is the oldest "
            "unread message plus every later message."
        ),
    )
    parser.add_argument("--id", required=True, help="Gmail thread ID")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include every message in the thread",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--max-body-chars",
        type=int,
        default=DEFAULT_MAX_BODY_CHARS,
        help=f"Per-message body limit (default: {DEFAULT_MAX_BODY_CHARS})",
    )
    parser.add_argument(
        "--max-thread-chars",
        type=int,
        default=DEFAULT_MAX_THREAD_CHARS,
        help=f"Aggregate body limit (default: {DEFAULT_MAX_THREAD_CHARS})",
    )
    return parser.parse_args(arguments)


def run_active_threads(
    arguments: list[str],
    profile: Path,
    *,
    executable: str | None = None,
) -> int:
    args = parse_active_threads_args(arguments)
    if args.max < 1:
        raise GwsxError("--max must be at least 1.")
    threads = summarize_active_threads(
        profile,
        query=args.query,
        max_results=args.max,
        executable=executable,
    )
    if args.format == "json":
        print(
            json.dumps(
                {"query": args.query, "threads": threads},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        sys.stdout.write(format_active_threads_text(threads))
    return 0


def run_thread(
    arguments: list[str],
    profile: Path,
    *,
    executable: str | None = None,
) -> int:
    args = parse_thread_args(arguments)
    if args.max_body_chars < 0 or args.max_thread_chars < 0:
        raise GwsxError("Character limits must be non-negative.")
    thread = fetch_full_thread(args.id, profile, executable=executable)
    view = build_thread_view(
        thread,
        include_all=args.all,
        max_body_chars=args.max_body_chars,
        max_thread_chars=args.max_thread_chars,
    )
    if args.format == "text":
        sys.stdout.write(format_thread_text(view))
    else:
        print(json.dumps(view, indent=2, ensure_ascii=False))
    return 0


def dispatch_account_command(
    arguments: list[str],
    profile: Path,
    *,
    executable: str | None = None,
) -> int:
    if len(arguments) >= 2 and arguments[0] == "gmail":
        helper = arguments[1]
        helper_args = arguments[2:]
        if helper == "+active-threads":
            return run_active_threads(
                helper_args,
                profile,
                executable=executable,
            )
        if helper == "+thread":
            return run_thread(helper_args, profile, executable=executable)
    return run_gws(arguments, profile, executable=executable)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(COMMAND_HELP)
        return 0

    try:
        if arguments[0] == "account":
            return manage_accounts(arguments[1:])

        alias, *gws_arguments = arguments
        profile = profile_dir(alias)
        if not profile.is_dir():
            raise GwsxError(
                f"Unknown account '{alias}'. "
                "Configure it with 'gwsx account add "
                f"{alias}'."
            )
        return dispatch_account_command(gws_arguments, profile)
    except GwsxError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

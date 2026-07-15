#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Run Google Workspace CLI commands against explicit account profiles."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ACCOUNT_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
RESERVED_NAMES = {"account"}
CONFIG_ENV = "GWSX_CONFIG_DIR"
GWS_CONFIG_ENV = "GOOGLE_WORKSPACE_CLI_CONFIG_DIR"
AUTH_OVERRIDE_ENVS = (
    "GOOGLE_WORKSPACE_CLI_TOKEN",
    "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
    "GOOGLE_APPLICATION_CREDENTIALS",
)
COMMAND_HELP = """gwsx - Google Workspace CLI with explicit account profiles
Usage:
  gwsx account add <alias>
  gwsx account delete <alias>
  gwsx account list
  gwsx <alias> <gws arguments...>

Examples:
  gwsx account add private
  gwsx account delete private
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
        return run_gws(gws_arguments, profile)
    except GwsxError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

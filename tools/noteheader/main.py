# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Create a meeting notes header with attendees and location."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

GEOLOC_DIR = Path.home() / "dev/myprojects/geoloc"
GEOLOC_SCRIPT = "geoloc.py"


def main() -> int:
    script = GEOLOC_DIR / GEOLOC_SCRIPT
    if not script.is_file():
        print(f"error: geoloc not found at {script}", file=sys.stderr)
        return 1

    # Drop the parent uv script env so geoloc uses its own .venv without a warning.
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    result = subprocess.run(
        ["uv", "run", GEOLOC_SCRIPT],
        cwd=GEOLOC_DIR,
        env=env,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

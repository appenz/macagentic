# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Stage an image or PDF for macAgentic."""

import argparse
import json
import mimetypes
import os
import shutil
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    source = parser.parse_args().path.expanduser()
    root = os.getenv("AGENT_ROOT")
    if not root:
        parser.error("AGENT_ROOT is not set")
    if not source.is_file():
        parser.error(f"not a file: {source}")
    mime = mimetypes.guess_type(source.name)[0] or ""
    if mime != "application/pdf" and not mime.startswith("image/"):
        parser.error(f"unsupported file type: {source}")
    if source.stat().st_size > MAX_BYTES:
        parser.error(f"file exceeds 20 MiB: {source}")

    context = Path(root) / "context"
    context.mkdir(exist_ok=True)
    sequence = max(
        (int(path.name.split("-", 1)[0]) for path in context.iterdir()
         if path.name.split("-", 1)[0].isdigit()),
        default=0,
    ) + 1
    destination = context / f"{sequence:03d}-{source.name}"
    shutil.copyfile(source, destination)
    print(json.dumps({
        "macagentic_context_file": str(destination.relative_to(root)),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

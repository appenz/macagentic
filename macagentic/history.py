from datetime import date
from pathlib import Path


def save_history(
    workspace: Path,
    content: str,
    *,
    today: date | None = None,
) -> Path | None:
    if not content.strip():
        return None

    folder = workspace / "history.local" / str(today or date.today())
    folder.mkdir(parents=True, exist_ok=True)

    number = 1
    while True:
        path = folder / f"session-{number}.md"
        try:
            with path.open("x") as output:
                output.write(content)
            return path
        except FileExistsError:
            number += 1

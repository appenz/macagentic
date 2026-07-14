from pathlib import Path

from macagentic.agent.skills import SkillCatalog


def run_ui(
    workspace: Path,
    *,
    model_name: str | None = None,
    initial_task: str | None = None,
    screenshot_path: Path | None = None,
    custom_instructions: str | None = None,
    tool_instructions: str | None = None,
    skill_catalog: SkillCatalog | None = None,
    show_tool_output: bool = False,
) -> None:
    from macagentic.ui.core import MacAgenticUI

    MacAgenticUI(
        workspace,
        model_name=model_name,
        initial_task=initial_task,
        screenshot_path=screenshot_path,
        custom_instructions=custom_instructions,
        tool_instructions=tool_instructions,
        skill_catalog=skill_catalog,
        show_tool_output=show_tool_output,
    ).start()


__all__ = ["run_ui"]

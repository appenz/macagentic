from pathlib import Path

from macagentic.agent import Agent
from macagentic.agent.skills import EMPTY_SKILL_CATALOG, SkillCatalog


class MacAgenticApp:
    workspace: Path
    model_name: str | None
    custom_instructions: str | None
    tool_instructions: str | None
    skill_catalog: SkillCatalog
    show_tool_output: bool
    screenshot_path: Path | None

    def __init__(self) -> None:
        self.workspace = Path.cwd()
        self.model_name = None
        self.custom_instructions = None
        self.tool_instructions = None
        self.skill_catalog = EMPTY_SKILL_CATALOG
        self.show_tool_output = False
        self.screenshot_path = None

    def configure(
        self,
        *,
        workspace: Path,
        model_name: str | None,
        custom_instructions: str | None,
        tool_instructions: str | None,
        skill_catalog: SkillCatalog,
        show_tool_output: bool,
        screenshot_path: Path | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.model_name = model_name
        self.custom_instructions = custom_instructions
        self.tool_instructions = tool_instructions
        self.skill_catalog = skill_catalog
        self.show_tool_output = show_tool_output
        self.screenshot_path = screenshot_path

    def create_agent(self) -> Agent:
        return Agent(
            self.workspace,
            model_name=self.model_name,
            custom_instructions=self.custom_instructions,
            tool_instructions=self.tool_instructions,
            skill_catalog=self.skill_catalog,
        )


app = MacAgenticApp()

# Application

`MacAgenticApp` is the single global application object. It owns effective
runtime configuration and creates identically configured agents.

```python
class MacAgenticApp:
    workspace: Path
    model_name: str | None
    custom_instructions: str | None
    tool_instructions: str | None
    skill_catalog: SkillCatalog
    show_tool_output: bool
    screenshot_path: Path | None

    def __init__(self) -> None: ...

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
    ) -> None: ...

    def create_agent(self) -> Agent: ...


app = MacAgenticApp()
```

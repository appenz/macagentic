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
    user_mounts: dict[str, str]
    show_tool_output: bool
    screenshot_path: Path | None
    next_agent_id: int

    def __init__(self) -> None: ...

    def configure(
        self,
        *,
        workspace: Path,
        model_name: str | None,
        custom_instructions: str | None,
        tool_instructions: str | None,
        skill_catalog: SkillCatalog,
        user_mounts: dict[str, str],
        show_tool_output: bool,
        screenshot_path: Path | None = None,
    ) -> None: ...

    def create_agent(self) -> Agent: ...


app = MacAgenticApp()
```

`create_agent()` assigns monotonically increasing integer IDs starting at one.
IDs restart with the application, so an agent reuses and wipes the same
`~/.tmpagent/<id>` path on a later application run.

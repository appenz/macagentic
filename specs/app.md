# Application

`MacAgenticApp` is the single global application object. It owns effective
runtime configuration and creates identically configured agents.

```python
class MacAgenticApp:
    workspace: Path
    model_name: str | None
    model_presets: dict[str, str]
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
        model_presets: dict[str, str] | None = None,
    ) -> None: ...

    def create_agent(self) -> Agent: ...


app = MacAgenticApp()
```

`create_agent()` assigns monotonically increasing integer IDs. Restored IDs
resume the sequence, and existing `~/.tmpagent/<id>` roots are reused unchanged.
New agents start with `model_name` from configuration; each agent may later
switch models via its own `model_presets` without changing other tabs.

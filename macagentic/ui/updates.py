from dataclasses import dataclass


@dataclass(frozen=True)
class SetTabTitle:
    tab_id: int
    title: str


@dataclass(frozen=True)
class SetToolCallDescription:
    tab_id: int
    tool_call_id: str
    text: str


@dataclass(frozen=True)
class AgentThreadCompleted:
    tab_id: int
    thread_id: int


UIUpdate = SetTabTitle | SetToolCallDescription | AgentThreadCompleted

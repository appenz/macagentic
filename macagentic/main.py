import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from macagentic.agent import Control
from macagentic.agent.skills import load_available_skills
from macagentic.agent.usage import print_usage
from macagentic.config import MacAgenticConfig, load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the macAgentic harness")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("task", nargs="?", help="Initial task for the agent")
    source.add_argument(
        "--task-file",
        "--spec",
        dest="task_file",
        type=Path,
        help="Read the task from a Markdown file",
    )
    parser.add_argument("--model", help="LiteLLM model name")
    parser.add_argument(
        "--instructions",
        type=Path,
        help="Append custom system instructions from a Markdown file",
    )
    parser.add_argument(
        "--tool-instructions",
        type=Path,
        help="Append generated tool documentation to the system prompt",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Start the optional native macOS UI",
    )
    parser.add_argument(
        "--tooloutput",
        action="store_true",
        help="Show bash commands and their output",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        help="Capture the UI after the initial task completes, then exit",
    )
    return parser.parse_args()


def _initial_task(args: argparse.Namespace) -> str | None:
    if args.task_file:
        task = args.task_file.read_text().strip()
        if not task:
            raise SystemExit("The spec must not be empty.")
        return task
    return args.task


def _custom_instructions(
    args: argparse.Namespace,
    config: MacAgenticConfig,
) -> str | None:
    if args.instructions is None:
        return config.custom_prompt or None
    instructions = args.instructions.read_text()
    if not instructions.strip():
        raise SystemExit("The instructions file must not be empty.")
    return instructions


def _tool_instructions(args: argparse.Namespace) -> str | None:
    if args.tool_instructions is None:
        return None
    instructions = args.tool_instructions.read_text()
    if not instructions.strip():
        raise SystemExit("The tool instructions file must not be empty.")
    return instructions


def main() -> None:
    load_dotenv()
    args = parse_args()
    config = load_config()
    if config.openai_api_key:
        os.environ["OPENAI_API_KEY"] = config.openai_api_key
    task = _initial_task(args)
    custom_instructions = _custom_instructions(args, config)
    tool_instructions = _tool_instructions(args)
    skill_catalog = load_available_skills()
    model_name = args.model or config.model

    if args.ui:
        from macagentic.ui import run_ui

        if args.screenshot and not task:
            raise SystemExit(
                "--screenshot requires an initial task or --task-file."
            )
        run_ui(
            Path.cwd(),
            model_name=model_name,
            initial_task=task,
            screenshot_path=args.screenshot,
            custom_instructions=custom_instructions,
            tool_instructions=tool_instructions,
            skill_catalog=skill_catalog,
            show_tool_output=args.tooloutput,
        )
        return

    if args.screenshot:
        raise SystemExit("--screenshot requires --ui.")

    if task is None:
        try:
            task = input("Task: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
    if not task:
        raise SystemExit("A task or non-empty spec is required.")
    Control(
        Path.cwd(),
        model_name=model_name,
        on_output=lambda content: print(f"\nAgent: {content}"),
        on_tool_output=lambda content: print(f"\n{content}", end=""),
        on_turn_complete=print_usage,
        show_tool_output=args.tooloutput,
        custom_instructions=custom_instructions,
        tool_instructions=tool_instructions,
        skill_catalog=skill_catalog,
    ).start(task)

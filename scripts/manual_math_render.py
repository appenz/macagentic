#!/usr/bin/env python3
"""Manual Cocoa UI math render debug helper.

Opens the Cocoa UI, injects Markdown with surrounding text and math,
takes a window screenshot, and writes artifacts under
/tmp/macagentic-math-debug/ for visual inspection.

Usage:
    uv run python -m scripts.manual_math_render
    uv run python -m scripts.manual_math_render --case one_plus_one
    uv run python -m scripts.manual_math_render --all
"""

from __future__ import annotations

import argparse
from pathlib import Path

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from Foundation import NSDate, NSRunLoop

from macagentic.agent import ConversationLog, UsageTracker
from macagentic.ui.testing import UITestDriver

OUTPUT_DIR = Path("/tmp/macagentic-math-debug")


def _capture_ui_window(ui, path: Path) -> bool:
    """Snapshot the Cocoa window via AppKit view caching (no Screen Recording)."""
    from AppKit import NSBitmapImageRep, NSPNGFileType

    window = ui.window
    if window is None:
        return False
    view = window.contentView()
    if view is None:
        return False
    bounds = view.bounds()
    rep = view.bitmapImageRepForCachingDisplayInRect_(bounds)
    if rep is None:
        return False
    view.cacheDisplayInRect_toBitmapImageRep_(bounds, rep)
    data = rep.representationUsingType_properties_(NSPNGFileType, None)
    if data is None:
        return False
    path.write_bytes(bytes(data))
    return True

CASES: dict[str, tuple[str, str]] = {
    "one_plus_one": (
        "one_plus_one",
        "Compare sizes on one line: text 1+1 vs math $1+1$.\n\n"
        "Display math:\n\n$$\n1+1\n$$\n",
    ),
    "maxwell": (
        "maxwell",
        "Maxwell's equations:\n\n"
        "$$\n"
        r"\begin{aligned}"
        r"\nabla \cdot \mathbf{E} &= \frac{\rho}{\varepsilon_0} \\"
        r"\nabla \cdot \mathbf{B} &= 0 \\"
        r"\nabla \times \mathbf{E} &= -\frac{\partial \mathbf{B}}{\partial t} \\"
        r"\nabla \times \mathbf{B} &= \mu_0\mathbf{J} + \mu_0\varepsilon_0\frac{\partial \mathbf{E}}{\partial t}"
        r"\end{aligned}"
        "\n$$\n\n"
        r"Inline: $\nabla \cdot \mathbf{E} = \rho / \varepsilon_0$."
        "\n",
    ),
    "maxwell_integral_list": (
        "maxwell_integral_list",
        "Here are Maxwell's equations in integral form:\n\n"
        "1. **Gauss's law (electric)**\n"
        "$$\n"
        r"\oint_{\partial V} \mathbf{E}\cdot d\mathbf{A} = \frac{Q_{\mathrm{enc}}}{\varepsilon_0}"
        "\n$$\n\n"
        "2. **Gauss's law (magnetic)**\n"
        "$$\n"
        r"\oint_{\partial V} \mathbf{B}\cdot d\mathbf{A} = 0"
        "\n$$\n\n"
        "3. **Faraday's law**\n"
        "$$\n"
        r"\oint_{\partial S} \mathbf{E}\cdot d\boldsymbol{\ell} = -\frac{d}{dt}\int_S \mathbf{B}\cdot d\mathbf{A}"
        "\n$$\n\n"
        "4. **Ampère–Maxwell law**\n"
        "$$\n"
        r"\oint_{\partial S} \mathbf{B}\cdot d\boldsymbol{\ell}"
        "\n=\n"
        r"\mu_0 I_{\mathrm{enc}}"
        "\n+\n"
        r"\mu_0\varepsilon_0"
        "\n"
        r"\frac{d}{dt}\int_S \mathbf{E}\cdot d\mathbf{A}"
        "\n$$\n",
    ),
    "exp_series": (
        "exp_series",
        "Polynomial expansion of the exponential:\n\n"
        "$$\n"
        r"e^x = 1 + x + \frac{x^2}{2!} + \frac{x^3}{3!} + \frac{x^4}{4!} + \cdots"
        "\n$$\n\n"
        r"Inline: $e^x = \sum_{n=0}^{\infty} \frac{x^n}{n!}$."
        "\n",
    ),
}


class FakeAgent:
    next_id = 1

    def __init__(self, **_kwargs) -> None:
        self.id = FakeAgent.next_id
        FakeAgent.next_id += 1
        self.ui = None
        self.conversation_log = ConversationLog()
        self.usage = UsageTracker()
        self.model_name = "openai/gpt-5-mini"
        self.interrupted = False

    def run_turn(self, text: str) -> None:
        # Assistant-only transcript so screenshots are not duplicated by the
        # echoed user_input line.
        self.conversation_log.append_message(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": text,
                            }
                        ],
                    }
                ],
                "extra": {"actions": []},
            }
        )
        if self.ui is not None:
            self.ui.update()

    def interrupt(self) -> None:
        self.interrupted = True


def _spin(seconds: float = 0.1) -> None:
    NSRunLoop.currentRunLoop().runUntilDate_(
        NSDate.dateWithTimeIntervalSinceNow_(seconds)
    )


def _build_ui(monkey_targets: dict) -> tuple[object, UITestDriver]:
    from macagentic.ui.core import MacAgenticUI

    # Patch UI helpers so the harness needs no network / workspace.
    import macagentic.ui.core as core_mod

    core_mod.save_history = monkey_targets["save_history"]
    core_mod.app.create_agent = monkey_targets["create_agent"]
    core_mod.request_fast_text = monkey_targets["request_fast_text"]

    agent = FakeAgent()
    ui = MacAgenticUI(agent)
    ui.start(dont_run_app=True)
    ui.hotkey_pressed()
    _spin(0.3)
    return ui, UITestDriver(ui)


def render_case(case_key: str) -> Path:
    slug, markdown = CASES[case_key]
    case_dir = OUTPUT_DIR / slug
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "markdown.txt").write_text(markdown, encoding="utf-8")

    FakeAgent.next_id = 1
    ui, driver = _build_ui(
        {
            "save_history": lambda *_a, **_k: None,
            "create_agent": FakeAgent,
            "request_fast_text": lambda **_k: None,
        }
    )

    # Echo the markdown as the assistant reply so the conversation log
    # shows text + math for size comparison.
    agent = ui.active_tab.agent
    agent.run_turn(markdown)
    driver.spin(0.2)
    ui.update()
    driver.wait_for(
        lambda: "\ufffc" in driver.conversation_text()
        or "Compare" in driver.conversation_text()
        or "Maxwell" in driver.conversation_text()
        or "Ampère" in driver.conversation_text()
        or "Polynomial" in driver.conversation_text(),
        timeout=10.0,
    )
    # Allow WebKit math rasterization + layout to settle.
    driver.spin(0.8)

    shot = case_dir / "ui.png"
    ok = _capture_ui_window(ui, shot)
    if not ok:
        raise RuntimeError(f"screenshot failed for {case_key}")
    print(f"wrote {shot} ({shot.stat().st_size} bytes)")

    ui.close_window()
    _spin(0.1)
    return shot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=[*CASES.keys(), "all"],
        default="one_plus_one",
    )
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    keys = list(CASES.keys()) if (args.all or args.case == "all") else [args.case]
    for key in keys:
        print(f"=== {key} ===")
        render_case(key)
    print(f"\nArtifacts in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""UI automation tools for macOS."""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import tempfile
from pathlib import Path


def screenshot(window_name: str | None = None, output_path: str | None = None) -> str:
    """Capture screen as base64 PNG.
    
    Args:
        window_name: If provided, capture specific window (not yet implemented)
        output_path: Optional file path to save screenshot
        
    Returns:
        Base64-encoded PNG image data
    """
    if window_name:
        raise NotImplementedError("Window-specific screenshots not yet implemented")
    
    # Use screencapture (built-in macOS tool)
    if output_path:
        subprocess.run(["screencapture", "-x", output_path], check=True)
        data = Path(output_path).read_bytes()
    else:
        # screencapture -x - doesn't work, use temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(["screencapture", "-x", tmp_path], check=True)
            data = Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    
    return f"<MSWEA_MULTIMODAL_CONTENT><CONTENT_TYPE>image_url</CONTENT_TYPE>data:image/png;base64,{base64.b64encode(data).decode('utf-8')}</MSWEA_MULTIMODAL_CONTENT>"


def ui_click(x: int, y: int) -> None:
    """Simulate mouse click at coordinates.
    
    Args:
        x: Screen X coordinate
        y: Screen Y coordinate
    """
    # Use AppleScript via osascript to click at position
    script = f"""
    tell application "System Events"
        click at position {{{x}, {y}}}
    end tell
    """
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


def ui_type(text: str) -> None:
    """Send keystrokes to focused element.
    
    Args:
        text: Text to type
    """
    # Escape special characters for AppleScript
    escaped = text.replace('"', '').replace('\\', '')
    script = f"""
    tell application "System Events"
        keystroke "{escaped}"
    end tell
    """
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UI automation for macOS")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # screenshot [-o output] <window_name?>
    screen_parser = subparsers.add_parser("screenshot", help="Capture screen as base64 PNG")
    screen_parser.add_argument("-o", "--output", help="Save to file instead of stdout")
    screen_parser.add_argument("window_name", nargs="?", help="Optional window name to capture")
    
    # click x y
    click_parser = subparsers.add_parser("click", help="Click at coordinates")
    click_parser.add_argument("x", type=int, help="X coordinate")
    click_parser.add_argument("y", type=int, help="Y coordinate")
    
    # type <text...>
    type_parser = subparsers.add_parser("type", help="Type text as keystrokes")
    type_parser.add_argument("text", nargs="+", help="Text to type")
    
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    
    try:
        if args.command == "screenshot":
            data = screenshot(args.window_name, args.output)
            if args.output:
                print(f"Saved to {args.output}")
            else:
                # Wrapped in <MSWEA_MULTIMODAL_CONTENT> tags so vision models
                # pick it up automatically when multimodal_regex is configured.
                sys.stdout.write(data)
                sys.stdout.flush()
        elif args.command == "click":
            ui_click(args.x, args.y)
        elif args.command == "type":
            ui_type(" ".join(args.text))
    except NotImplementedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"error: Command failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

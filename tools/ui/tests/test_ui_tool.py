import subprocess


def test_screenshot_returns_base64() -> None:
    """Basic screenshot test - verify it produces valid output format."""
    result = subprocess.run(
        ["uv", "run", "--frozen", "python", "tools/ui/main.py", "screenshot"],
        capture_output=True,
        text=True,
        check=True
    )
    data = result.stdout.strip()
    assert len(data) > 0
    
    # Base64 should decode to reasonable size PNG
    import base64
    decoded = base64.b64decode(data)
    assert len(decoded) > 1000
    
    # Should be valid PNG (starts with magic bytes)
    assert decoded[:8] == b'\x89PNG\r\n\x1a\n', "Output is not valid PNG"


def test_screenshot_save_to_file(tmp_path) -> None:
    """Test screenshot saves to file."""
    output = tmp_path / "screenshot.png"
    result = subprocess.run(
        ["uv", "run", "--frozen", "python", "tools/ui/main.py", "screenshot", "-o", str(output)],
        capture_output=True,
        text=True,
        check=True
    )
    
    assert output.exists()
    assert output.stat().st_size > 1000


def test_ui_click_syntax() -> None:
    """Test that click command parses args (doesn't fail on argument parsing)."""
    result = subprocess.run(
        ["uv", "run", "--frozen", "python", "tools/ui/main.py", "click", "100", "200"],
        capture_output=True,
        text=True
    )
    # Should either succeed or give NotImplementedError (both are valid)
    assert result.returncode in {0, 1}


def test_ui_type_syntax() -> None:
    """Test that type command parses args (doesn't fail on argument parsing)."""
    result = subprocess.run(
        ["uv", "run", "--frozen", "python", "tools/ui/main.py", "type", "hello"],
        capture_output=True,
        text=True
    )
    # Should either succeed or give NotImplementedError (both are valid)
    assert result.returncode in {0, 1}

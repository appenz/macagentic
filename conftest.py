import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--vision-url",
        action="store",
        default="http://192.168.1.157:8080/v1",
        help="Vision model OpenAI-compatible API endpoint",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "hardware: requires real macOS commands (screencapture, osascript)",
    )


@pytest.fixture
def vision_url(request) -> str:
    return request.config.getoption("--vision-url")

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BAT_FILES = ("packaging/install.bat", "packaging/build_exe.bat")


def _pip_req_install_lines(text):
    for raw in text.splitlines():
        line = raw.strip()
        if "pip install" in line and "-r requirements/" in line:
            yield line


@pytest.mark.parametrize("rel", _BAT_FILES)
def test_pip_requirements_install_suppresses_script_location_warning(rel):
    text = (_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    lines = list(_pip_req_install_lines(text))
    assert lines, f"{rel}: no 'pip install -r requirements/' line found"
    for line in lines:
        assert "--no-warn-script-location" in line, (
            f"{rel}: '{line}' must pass --no-warn-script-location so the "
            "one-click build stays quiet when Python's per-user Scripts dir "
            "is not on PATH (Python 3.14 install manager layout)"
        )

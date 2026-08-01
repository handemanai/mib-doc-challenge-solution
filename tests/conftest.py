"""Put the repo root on sys.path so `pytest tests/` works from a clean clone
without an install step."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = Path(__file__).resolve().parents[1]
_MISMATCHES = []


def _pinned():
    """The (package, version) pairs requirements.txt declares."""
    requirements = _ROOT / "requirements.txt"
    if not requirements.exists():
        return []
    pins = []
    for line in requirements.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "==" in line:
            name, _, version = line.partition("==")
            pins.append((name.strip(), version.strip()))
    return pins


def pytest_configure(config):
    """Record any drift from the pinned dependency set.

    The pins are load-bearing: RapidOCR's preprocessing and the recognizer's
    numerics are part of the measured result, so a mismatched environment can
    fail tests for reasons that have nothing to do with this repository. Those
    failures are usually unreadable on their own — older rapidocr-onnxruntime
    releases (1.2.3, for one) subscript `det_dict['model_path']` whenever any
    `det_*` keyword is passed, where 1.4.4 looks it up with `.get()`, so
    constructing the engine raises `KeyError: 'model_path'` from inside
    site-packages before any assertion in this suite runs.

    This only reports. It never skips or fails, so deliberately testing against
    another version stays possible.
    """
    del config
    from importlib.metadata import PackageNotFoundError, version

    _MISMATCHES.clear()
    for name, expected in _pinned():
        try:
            found = version(name)
        except PackageNotFoundError:
            found = "not installed"
        if found != expected:
            _MISMATCHES.append(f"  {name}: expected {expected}, found {found}")


def _warning_lines():
    return [
        "WARNING: installed dependencies do not match requirements.txt",
        *_MISMATCHES,
        "",
        "The scoring image pins these exact versions, so failures above may be",
        "environmental rather than real. Reproduce the pinned environment with",
        "    pip install -r requirements.txt",
        "or run the suite inside the built image (see README.md).",
    ]


def pytest_report_header(config):
    del config
    if not _MISMATCHES:
        return None
    return "\n".join(["=" * 70, *_warning_lines(), "=" * 70])


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Repeat the warning at the end, where -q runs will actually show it."""
    del exitstatus, config
    if not _MISMATCHES:
        return
    terminalreporter.write_sep("=", "dependency mismatch", red=True)
    for line in _warning_lines():
        terminalreporter.write_line(line)

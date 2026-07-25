"""Locate the public challenge checkout (data/, labels, scorer) for dev-time use.

Nothing here ships in the image: the runtime reads only its `/input` argument
and never needs the challenge repo. Tests and dev tooling do need it, and
hardcoding one machine's path makes them unrunnable from a clean checkout, so
resolution is explicit and overridable:

1. ``MIB_CHALLENGE_DIR`` if set,
2. otherwise a ``mib-doc-challenge`` directory beside this repo.

`available()` lets a test skip cleanly when the data is simply not present
rather than failing with a confusing path error.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def challenge_dir():
    override = os.environ.get("MIB_CHALLENGE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (REPO_ROOT.parent / "mib-doc-challenge").resolve()


CHALLENGE = challenge_dir()


def available():
    """True when the challenge data needed by data-backed tests is present."""
    return (CHALLENGE / "data" / "train_labels.csv").is_file()

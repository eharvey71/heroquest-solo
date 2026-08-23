"""Guards against the class of bug that broke Zargon's turn in
production: `VALID_TURN_TYPES` was deleted as collateral by an
unrelated commit, and nothing noticed.

Python resolves module-level names at CALL time, so a missing constant
imports cleanly and only explodes when a player presses the button.
The unit tests didn't catch it either -- they call the _apply_*
functions directly, below the endpoint's argument validation, which is
where the dead name lived. pyflakes reads every line whether a test
reaches it or not.
"""

import subprocess
import sys
from pathlib import Path

FUNCTIONS_DIR = Path(__file__).resolve().parent.parent

TARGETS = ["main.py", "owner.py", "firestore_coords.py", "engine", "validator", "generator", "sim", "tests"]


def test_no_undefined_names():
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", *TARGETS],
        cwd=FUNCTIONS_DIR,
        capture_output=True,
        text=True,
    )
    # "imported but unused" is style, not a live grenade -- this test is
    # only about names that don't exist.
    problems = [
        line
        for line in proc.stdout.splitlines()
        if "undefined name" in line or "may be undefined" in line
    ]
    assert not problems, "undefined names:\n" + "\n".join(problems)

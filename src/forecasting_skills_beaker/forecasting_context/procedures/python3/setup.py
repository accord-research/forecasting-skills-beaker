# Prepare the subkernel for the forecasting skills.
#
# Three jobs, each individually guarded so a failure in one leaves a usable
# notebook rather than a context that refuses to start:
#
#   1. Import the small analysis stack (xarray, numpy) for looking at the
#      envelope Zarrs the skills produce.
#   2. Ensure a local checkout of the forecasting-skills repo. The agent's
#      skill *instructions* are fetched remotely from `main` at session start;
#      the *scripts* those instructions describe have to exist on disk to be
#      run (some carry assets and lockfiles), so a checkout under ~/.cache is
#      cloned once and fast-forwarded at each session start to track the same
#      `main`. Set FORECASTING_SKILLS_NO_SYNC=1 to skip the network entirely,
#      or FORECASTING_SKILLS_HOME to relocate the checkout.
#   3. Define run_skill(), the one call the agent uses to execute a skill.

import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import xarray as xr

FORECASTING_SKILLS_REPO = "https://github.com/rhiza-research/forecasting-skills.git"
FORECASTING_SKILLS_HOME = Path(
    os.environ.get("FORECASTING_SKILLS_HOME")
    or Path.home() / ".cache" / "forecasting-skills-beaker" / "forecasting-skills"
)

# Status notes the environment preview reports verbatim.
_fsb_notes = {}


def _fsb_sync_checkout():
    if os.environ.get("FORECASTING_SKILLS_NO_SYNC"):
        _fsb_notes["checkout"] = "sync skipped (FORECASTING_SKILLS_NO_SYNC is set)"
        return
    if shutil.which("git") is None:
        _fsb_notes["checkout"] = "git not found; cannot sync the skills checkout"
        return
    try:
        if (FORECASTING_SKILLS_HOME / ".git").is_dir():
            subprocess.run(
                ["git", "-C", str(FORECASTING_SKILLS_HOME), "pull", "--ff-only", "--quiet"],
                check=True, capture_output=True, text=True, timeout=120,
            )
            _fsb_notes["checkout"] = "updated"
        else:
            FORECASTING_SKILLS_HOME.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet",
                 FORECASTING_SKILLS_REPO, str(FORECASTING_SKILLS_HOME)],
                check=True, capture_output=True, text=True, timeout=600,
            )
            _fsb_notes["checkout"] = "cloned"
    except Exception as err:  # noqa: BLE001 - report at startup, never raise
        detail = getattr(err, "stderr", "") or str(err)
        state = "stale" if (FORECASTING_SKILLS_HOME / "skills").is_dir() else "absent"
        _fsb_notes["checkout"] = f"sync failed, checkout {state}: {detail.strip()[:200]}"


_fsb_sync_checkout()

if shutil.which("uv") is None:
    _fsb_notes["uv"] = (
        "uv not found on PATH -- run_skill cannot work without it. "
        "Install from https://docs.astral.sh/uv/"
    )


def run_skill(skill, *args, timeout=3600):
    """Run one forecasting skill's script, as its SKILL.md documents.

        run_skill("chirps-fetch", "--start", "2026-01-01", "--end", "2026-01-31",
                  "--output", "chirps.zarr")

    Executes `uv run --script <checkout>/skills/<skill>/scripts/<script>.py`
    with the given arguments (each skill ships exactly one script), prints the
    script's stdout/stderr, and returns the CompletedProcess. CLAUDE_SKILL_DIR
    is set to the skill's directory so commands written against that
    convention resolve as documented.
    """
    # Local imports, deliberately: Beaker runs the context's setup procedure
    # BEFORE PythonSubkernel.setup(), whose init code ends with
    # `del importlib, os, site, sys` -- deleting this module's top-level os and
    # sys from the notebook namespace right after we bound them. A body-level
    # import is immune to any later surgery on the user namespace.
    import os
    import subprocess
    import sys

    skill_dir = FORECASTING_SKILLS_HOME / "skills" / str(skill)
    scripts = sorted((skill_dir / "scripts").glob("*.py"))
    if not scripts:
        available = sorted(
            entry.name for entry in (FORECASTING_SKILLS_HOME / "skills").glob("*/") if entry.is_dir()
        ) if (FORECASTING_SKILLS_HOME / "skills").is_dir() else []
        raise FileNotFoundError(
            f"No script for skill {skill!r} under {skill_dir}. "
            f"Available skills: {available or 'none -- the checkout is missing'}"
        )
    command = ["uv", "run", "--script", str(scripts[0]), *[str(arg) for arg in args]]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "CLAUDE_SKILL_DIR": str(skill_dir)},
    )
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n", file=sys.stderr)
    return proc

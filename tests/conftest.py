import inspect
import json
from pathlib import Path

import pytest

from forecasting_skills_beaker.forecasting_context.context import ForecastingContext

CONTEXT_DIR = Path(inspect.getabsfile(ForecastingContext)).parent
SKILLS_FILE = CONTEXT_DIR / "skills.json"


@pytest.fixture(scope="session")
def context_dir() -> Path:
    """Directory holding context.py -- also where Beaker looks for skills.json."""
    return CONTEXT_DIR


@pytest.fixture(scope="session")
def skill_sources() -> list[str]:
    """The raw entries of skills.json."""
    return json.loads(SKILLS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def skill_provider(context_dir):
    """A provider built the way ForecastingContext builds it at runtime.

    Constructed from skills.json rather than from a hand-written path list, so
    the tests exercise the same file the notebook will. skill_paths is passed
    by keyword for the same cross-version reason as in context.py.

    Hits the network: every skill is remote.
    """
    from beaker_notebook.lib.integrations.skill import SkillIntegrationProvider

    return SkillIntegrationProvider(skill_paths=[str(context_dir / "skills.json")])

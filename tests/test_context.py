"""The context is wired correctly and installs into Beaker.

These run offline. Nothing here starts a kernel; they check the declarations
Beaker reads at discovery and setup time. The setup procedure's network sync
is disabled through its own FORECASTING_SKILLS_NO_SYNC knob.
"""

import inspect

import jinja2
import pytest

from forecasting_skills_beaker.forecasting_context.agent import ForecastingAgent
from forecasting_skills_beaker.forecasting_context.context import ForecastingContext

# Procedures the context asks for by name. get_code() raises if one is absent,
# and the calls sit in setup() and generate_preview(), so a rename that misses
# one only shows up when a session starts.
REQUIRED_PROCEDURES = ("setup", "environment")


def test_context_declares_expected_identity():
    assert ForecastingContext.SLUG == "forecasting"
    assert ForecastingContext.AGENT_CLS is ForecastingAgent
    assert ForecastingContext.compatible_subkernels == ["python3"]


def test_forecasting_is_the_context_a_session_opens_on():
    """Installing this package should make `forecasting` the default context.

    Beaker picks the installed context with the lowest WEIGHT (see
    BeakerKernel.start_default_context) and sorts the dropdown the same way.
    Ties are broken by dict order, so being strictly lower than every other
    installed context is what makes this deterministic.
    """
    from beaker_notebook.lib.context import autodiscover_contexts

    contexts = {
        slug: cls for slug, cls in autodiscover_contexts().items() if cls is not None
    }
    winner = min(contexts.items(), key=lambda item: item[1].WEIGHT)
    assert winner[0] == "forecasting", (
        f"'{winner[0]}' would load first "
        f"({ {s: c.WEIGHT for s, c in contexts.items()} })"
    )
    others = [c.WEIGHT for s, c in contexts.items() if s != "forecasting"]
    assert all(ForecastingContext.WEIGHT < w for w in others), "weight must be strictly lowest"


def test_context_is_discoverable_by_beaker():
    """Beaker finds contexts through entry points written by its build hook.

    This fails when the package is imported but not installed, which is the
    real failure mode: editable installs go stale after the context moves.
    """
    from beaker_notebook.lib.context import autodiscover_contexts

    contexts = autodiscover_contexts()
    assert "forecasting" in contexts, (
        f"'forecasting' not registered; found {sorted(contexts)}. "
        "Run `beaker project update` after moving or adding a context."
    )
    assert contexts["forecasting"] is ForecastingContext


def test_context_and_agent_carry_prompts():
    """Both docstrings are fed to the LLM, so an empty one is a silent defect."""
    assert ForecastingContext.__doc__ and ForecastingContext.__doc__.strip()
    assert ForecastingAgent.__doc__ and ForecastingAgent.__doc__.strip()
    # The one mechanism everything else depends on must be named in the prompt.
    assert "run_skill" in ForecastingAgent.__doc__


async def test_system_preamble_is_present_and_specific():
    context = ForecastingContext.__new__(ForecastingContext)  # no kernel needed to read it
    preamble = await ForecastingContext.system_preamble(context)
    assert preamble
    # The envelope shapes and the helper are what the agent most needs to know.
    assert "run_skill" in preamble
    assert "(time, station_id)" in preamble


@pytest.mark.parametrize("name", REQUIRED_PROCEDURES)
def test_required_procedures_are_registered_for_python3(name):
    """Beaker must actually discover the procedure, not merely have the file.

    get_code() resolves against the discovered set, so a procedure in the wrong
    directory is indistinguishable from a missing one at runtime -- and setup()
    swallows the failure by design.
    """
    procedures = ForecastingContext.discover_procedures()
    assert name in procedures, f"{name} not discovered; found {sorted(procedures)}"
    assert "python3" in procedures[name]["languages"]


@pytest.mark.parametrize("name", REQUIRED_PROCEDURES)
def test_required_procedures_are_valid_python_and_jinja(context_dir, name):
    """Procedures are Jinja templates rendered before execution.

    A stray brace therefore breaks at session start rather than at import.
    """
    path = context_dir / "procedures" / "python3" / f"{name}.py"
    assert path.is_file(), f"missing procedure: {path}"

    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")
    jinja2.Environment().parse(source)


def test_setup_procedure_defines_the_helper_without_network(context_dir, monkeypatch):
    """The preamble must come up offline and leave run_skill defined.

    FORECASTING_SKILLS_NO_SYNC is the supported way to run without touching
    the network; under it the procedure must neither raise nor clone.
    """
    monkeypatch.setenv("FORECASTING_SKILLS_NO_SYNC", "1")
    source = (context_dir / "procedures" / "python3" / "setup.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(source, "setup.py", "exec"), namespace)  # noqa: S102 - fixture under test

    assert "xr" in namespace and "np" in namespace
    assert callable(namespace["run_skill"])
    assert namespace["_fsb_notes"]["checkout"].startswith("sync skipped")


def test_run_skill_names_the_missing_skill(context_dir, monkeypatch, tmp_path):
    """A wrong skill name should fail with the roster, not a bare traceback."""
    monkeypatch.setenv("FORECASTING_SKILLS_NO_SYNC", "1")
    monkeypatch.setenv("FORECASTING_SKILLS_HOME", str(tmp_path / "nowhere"))
    source = (context_dir / "procedures" / "python3" / "setup.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(compile(source, "setup.py", "exec"), namespace)  # noqa: S102 - fixture under test

    with pytest.raises(FileNotFoundError, match="no-such-skill"):
        namespace["run_skill"]("no-such-skill")


def test_environment_procedure_reports_credentials(context_dir):
    """The preview must describe credentials without ever reading them."""
    source = (context_dir / "procedures" / "python3" / "environment.py").read_text(encoding="utf-8")
    namespace: dict = {"_fsb_notes": {"checkout": "sync skipped (test)"}}
    exec(compile(source, "environment.py", "exec"), namespace)  # noqa: S102 - fixture under test
    environment = namespace["_forecasting_environment"]()

    assert "uv" in environment["tools"]
    assert "OPENAQ_API_KEY" in environment["credentials"]
    for entry in environment["credentials"].values():
        assert set(entry) == {"present", "used_for"}
        assert isinstance(entry["present"], bool)
    assert environment["skills_checkout"]["notes"] == {"checkout": "sync skipped (test)"}
    assert "chirps-fetch" in environment["credential_free_fetchers"]

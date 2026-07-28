import inspect
import logging
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, TYPE_CHECKING

from beaker_notebook.lib import BeakerContext

from .agent import ForecastingAgent

if TYPE_CHECKING:
    from beaker_notebook.kernel import BeakerKernel
    from beaker_notebook.lib.integrations.base import BaseIntegrationProvider

logger = logging.getLogger(__name__)


class ForecastingContext(BeakerContext):
    """
    Weather and climate data pipelines built from the rhiza-research
    forecasting skills.

    Gives the agent the full skill set from
    github.com/rhiza-research/forecasting-skills: source-specific fetchers
    (ECMWF S2S, CHIRPS, IMERG, ERA5, CMIP6, stations and more), generic
    transforms over a shared Zarr envelope (clip, aggregate, downscale,
    difference, ...), and plotters. Use it to fetch observations and
    forecasts, build fetch-transform-plot pipelines, and compare sources.
    """

    AGENT_CLS = ForecastingAgent
    SLUG = "forecasting"

    #: Beaker starts whichever installed context has the lowest weight, and
    #: sorts the context dropdown by it. The built-in DefaultContext is 10, so
    #: anything below that makes this the one a session opens on -- which is the
    #: point of installing this package. Set BEAKER_DEFAULT_CONTEXT=default to
    #: override for a single run without uninstalling.
    WEIGHT = 5

    compatible_subkernels = ["python3"]

    #: Whether to also offer the skills installed in the user's global skill
    #: directories (``~/.beaker/skills``, ``~/.agents/skills``, and the
    #: equivalents beside the notebook). Off by default -- see
    #: :meth:`default_integration_providers`. Flip to True to opt back in.
    INCLUDE_GLOBAL_SKILLS: ClassVar[bool] = False

    def __init__(self, beaker_kernel: "BeakerKernel", config: Optional[Dict[str, Any]] = None):
        super().__init__(beaker_kernel, config=config)

    @property
    def default_integration_providers(self) -> "list[BaseIntegrationProvider]":
        """Drop the globally-installed skills unless explicitly opted in.

        Beaker offers every context the skills it finds in the user's global
        directories, on top of the context's own. This context already carries
        thirty-plus skills of its own; mixing in a personal skill library on
        top of that both inflates the system prompt on every session and gives
        the agent a retrieval problem -- skills whose descriptions overlap on
        words like "data" or "fetch" are a genuine source of wrong turns.

        Builds the provider outright rather than filtering Beaker's list,
        because in 2.0.9 the two are not distinguishable: both get a random
        ``id``, and ``display_name`` is written to the *class* by
        ``BaseIntegrationProvider.__init__``, so every instance reports
        whichever name was set last. Filtering on either silently matches
        nothing.

        Passes ``skill_paths`` by keyword and nothing positionally. The first
        positional argument is ``display_name`` in 2.0.9 but ``id`` on the dev
        line, so a positional string quietly changes meaning across versions.
        """
        if self.INCLUDE_GLOBAL_SKILLS:
            return list(super().default_integration_providers)

        from beaker_notebook.lib.integrations.skill import SkillIntegrationProvider

        skills_file = Path(inspect.getabsfile(self.__class__)).parent / "skills.json"
        if not skills_file.is_file():
            logger.warning("No skills.json beside %s; the agent will have no skills.", __name__)
            return []
        return [SkillIntegrationProvider(skill_paths=[str(skills_file)])]

    async def setup(self, context_info=None, parent_header=None):
        """Prepare the subkernel: imports, the skills checkout, and `run_skill`.

        The setup procedure clones or fast-forwards the local checkout of the
        forecasting-skills repo that `run_skill` executes scripts from, so the
        scripts the agent runs track the same `main` its skill instructions
        were fetched from.

        Failure here is not fatal: a user who is offline should still get a
        working notebook (with a stale checkout, or none) rather than a
        context that refuses to start.
        """
        await super().setup()
        try:
            await self.execute(self.get_code("setup"), parent_header=parent_header or {})
            # Also define _forecasting_environment() now: the agent is told to
            # call it for credential questions, and waiting for the preview to
            # define it would make that a race.
            await self.execute(self.get_code("environment"), parent_header=parent_header or {})
        except Exception:
            logger.warning("Forecasting subkernel preamble failed to run; continuing without it.", exc_info=True)

    async def system_preamble(self) -> Optional[str]:
        """Environment facts cached for the lifetime of the session.

        Deliberately short. The substance lives in the skills, which the agent
        loads on demand -- restating flags or date idioms here would occupy
        context whether or not the session ever touches that skill.
        """
        return (
            "This notebook is set up for weather/climate data pipelines built from the "
            "forecasting skills. The subkernel has already imported `xarray as xr`, "
            "`numpy as np`, `os`, and `sys`, and defines `run_skill(skill_name, *args)` plus "
            "`FORECASTING_SKILLS_HOME`, the local checkout of the skills repository; check the "
            "Environment preview for the checkout state and available credentials.\n\n"
            "Skills read and write a shared Zarr envelope: gridded data is "
            "`(number?, step|time, latitude, longitude)` and station data is `(time, station_id)`. "
            "Forecast steps are lead times; use the step-to-time skill before comparing a forecast "
            "against time-based observations. Every skill takes explicit `--input`/`--output` "
            "paths, which is how pipelines chain.\n\n"
            "Consult a skill's instructions before running it."
        )

    async def generate_preview(self):
        """Show the state of the tools, the skills checkout, and credentials.

        A missing credential or an absent `uv` surfaces as a subprocess
        failure partway through a pipeline, so it is worth showing up front.
        """
        try:
            result = await self.evaluate(self.get_code("environment"))
            environment = result.get("return") or {}
        except Exception:
            logger.warning("Could not generate forecasting environment preview.", exc_info=True)
            return {}

        return {
            "Environment": {
                "state": {
                    "application/json": environment,
                }
            },
        }

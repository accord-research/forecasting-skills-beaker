"""The forecasting skills reach the agent.

The skills are loaded remotely at runtime, straight from
rhiza-research/forecasting-skills `main`, so these split into two groups:

* offline checks on skills.json itself, which run everywhere; and
* `network` checks that fetch the live skills, which prove the agent will
  actually get what it needs. CI runs those on a schedule so upstream drift
  surfaces as a notification rather than as an agent that quietly forgets a
  skill exists.
"""

import json
from urllib.parse import urlparse

import pytest

from beaker_notebook.lib.integrations.skill import parse_skill_md
from beaker_notebook.lib.integrations.types import SkillFileResource

# Every skill directory in the upstream repo. Adding a skill upstream means
# adding a line here and in skills.json; test_skills_json_tracks_upstream
# is the network check that notices when upstream moves first.
EXPECTED_SKILLS = {
    "aggregate-temporal",
    "arco-era5-fetch",
    "chirps-fetch",
    "clip-region",
    "cmip6-fetch",
    "coarsen",
    "concat",
    "convert-calendar",
    "deaccumulate",
    "difference",
    "downscale",
    "dynamical-fetch",
    "ecmwf-fetch",
    "email-report",
    "ghcn-daily-fetch",
    "imerg-fetch",
    "oisst-fetch",
    "openaq-fetch",
    "plot",
    "plot-compare",
    "plot-mediogram",
    "plot-timeseries",
    "provenance",
    "reduce",
    "rename",
    "resolve-region",
    "select",
    "smap-fetch",
    "step-to-time",
    "submit-feedback",
    "tahmo-fetch",
    "unit-convert",
}

# Beaker normalizes skill names into slugs with underscores.
EXPECTED_SLUGS = {name.replace("-", "_") for name in EXPECTED_SKILLS}


# --------------------------------------------------------------------------
# Offline
# --------------------------------------------------------------------------


def test_skills_file_is_a_list_of_https_urls(skill_sources):
    assert isinstance(skill_sources, list)
    for source in skill_sources:
        assert isinstance(source, str), "2.0.9 supports only the bare-string entry form"
        parsed = urlparse(source)
        assert parsed.scheme == "https", f"{source} must be https"
        # Beaker appends "SKILL.md" to a directory URL; without the trailing
        # slash it strips the last path segment instead.
        assert source.endswith("/") or source.endswith("SKILL.md"), (
            f"{source} must end in '/' or 'SKILL.md'"
        )


def test_skills_file_covers_every_expected_skill(skill_sources):
    listed = {source.rstrip("/").rsplit("/", 1)[-1] for source in skill_sources}
    assert listed == EXPECTED_SKILLS, (
        f"skills.json and EXPECTED_SKILLS disagree: "
        f"only in skills.json {sorted(listed - EXPECTED_SKILLS)}, "
        f"only in EXPECTED_SKILLS {sorted(EXPECTED_SKILLS - listed)}"
    )


def test_skills_file_is_formatted(context_dir):
    """Keeps diffs meaningful when a skill is added."""
    raw = (context_dir / "skills.json").read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2) + "\n"


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------


@pytest.mark.network
def test_all_skills_load(skill_provider):
    """A skill that fails to fetch is dropped silently, so assert on presence."""
    loaded = {skill.slug for skill in skill_provider._skills}
    assert loaded == EXPECTED_SLUGS, (
        f"missing {sorted(EXPECTED_SLUGS - loaded)}; unexpected {sorted(loaded - EXPECTED_SLUGS)}"
    )


@pytest.mark.network
def test_prompt_advertises_the_skills(skill_provider):
    """What the agent sees is the prompt; an empty one means no skills at all."""
    prompt = skill_provider.prompt
    assert prompt
    for slug in EXPECTED_SLUGS:
        assert slug in prompt


@pytest.mark.network
def test_skills_json_tracks_upstream(skill_sources):
    """Upstream adding or removing a skill should fail loudly here.

    Compares skills.json against the live directory listing of the upstream
    skills/ tree, so drift surfaces on the scheduled CI run rather than as an
    agent that silently lacks a capability.
    """
    import urllib.request

    request = urllib.request.Request(
        "https://api.github.com/repos/rhiza-research/forecasting-skills/contents/skills",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "forecasting-skills-beaker"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        entries = json.load(response)
    upstream = {entry["name"] for entry in entries if entry["type"] == "dir"}
    listed = {source.rstrip("/").rsplit("/", 1)[-1] for source in skill_sources}
    assert listed == upstream, (
        f"upstream has {sorted(upstream - listed)} we do not list; "
        f"we list {sorted(listed - upstream)} upstream no longer has"
    )


@pytest.mark.network
@pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
def test_skill_instructions_are_retrievable(skill_provider, slug):
    skill = skill_provider._find_skill_by_slug(slug)
    frontmatter, body = parse_skill_md(
        skill_provider._fetch_file_content(skill, "SKILL.md")
    )
    assert frontmatter["name"] == slug.replace("_", "-")
    assert frontmatter["description"].strip()
    assert body.strip()


@pytest.mark.network
@pytest.mark.parametrize("slug", sorted(EXPECTED_SLUGS))
def test_every_advertised_resource_resolves(skill_provider, slug):
    """Beaker offers the agent every path it finds in SKILL.md.

    Upstream writes some resource links with a literal `${CLAUDE_SKILL_DIR}/`
    prefix (a Claude Code convention), which Beaker advertises verbatim. The
    agent is instructed to strip that prefix before loading, so this resolves
    the same way the agent would. Unlike accord-beaker, most skills here
    advertise no resources at all -- the scripts do the work -- so an empty
    list is fine.
    """
    skill = skill_provider._find_skill_by_slug(slug)
    advertised = [
        resource.relative_path
        for resource in skill.resources.values()
        if isinstance(resource, SkillFileResource)
    ]

    unresolvable = []
    for relative_path in advertised:
        fetchable = relative_path.removeprefix("${CLAUDE_SKILL_DIR}/")
        try:
            skill_provider._fetch_file_content(skill, fetchable)
        except Exception as exc:  # noqa: BLE001 - collect all failures, not the first
            unresolvable.append(f"{relative_path} ({type(exc).__name__})")
    assert not unresolvable, f"{slug} advertises unreachable resources: {unresolvable}"


@pytest.mark.network
def test_context_exposes_only_its_own_skills():
    """The user's globally-installed skills must not leak into this context.

    Beaker offers every context the skills in ~/.beaker/skills and friends. On
    a machine with a large personal skill library that is both a large
    permanent prompt cost and a retrieval problem.
    """
    from forecasting_skills_beaker.forecasting_context.context import ForecastingContext

    context = ForecastingContext.__new__(ForecastingContext)  # the property needs no kernel
    exposed = {
        skill.slug
        for provider in context.default_integration_providers
        for skill in getattr(provider, "_skills", [])
    }
    assert exposed == EXPECTED_SLUGS


@pytest.mark.network
def test_global_skills_remain_opt_in(monkeypatch):
    """Suppression is a default, not a hard-coded refusal.

    Asserts that opting in stops filtering and hands back whatever Beaker
    attached -- deliberately not which skills those are. Beaker moved that
    around: 2.0.9 returns the context's own skills from this property too,
    while the dev line splits them into `context_integration_providers`. Only
    the "does it filter" question is stable across both.
    """
    from beaker_notebook.lib import BeakerContext

    from forecasting_skills_beaker.forecasting_context.context import ForecastingContext

    context = ForecastingContext.__new__(ForecastingContext)
    attached_by_beaker = list(BeakerContext.default_integration_providers.fget(context))

    monkeypatch.setattr(ForecastingContext, "INCLUDE_GLOBAL_SKILLS", True)
    assert len(list(context.default_integration_providers)) == len(attached_by_beaker)

    monkeypatch.setattr(ForecastingContext, "INCLUDE_GLOBAL_SKILLS", False)
    suppressed = {
        skill.slug
        for provider in context.default_integration_providers
        for skill in getattr(provider, "_skills", [])
    }
    assert suppressed == EXPECTED_SLUGS

    # The behavioural claim, when there is actually something to opt into.
    global_skills = {
        skill.slug
        for provider in attached_by_beaker
        for skill in getattr(provider, "_skills", [])
    } - EXPECTED_SLUGS
    if not global_skills:
        pytest.skip("no global skills installed here, so nothing to opt into")
    monkeypatch.setattr(ForecastingContext, "INCLUDE_GLOBAL_SKILLS", True)
    opted_in = {
        skill.slug
        for provider in context.default_integration_providers
        for skill in getattr(provider, "_skills", [])
    }
    assert global_skills <= opted_in

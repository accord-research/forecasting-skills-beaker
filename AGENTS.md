# Working in forecasting-skills-beaker

This repo is a Beaker **context package**: a thin Python package whose job is to configure an AI
agent, not to implement weather tooling. The tooling lives in
[rhiza-research/forecasting-skills](https://github.com/rhiza-research/forecasting-skills). Keep it
that way — if you find yourself writing data-pipeline logic here, it belongs upstream.

It is a sibling of [accord-beaker](https://github.com/accord-research/accord-beaker) and follows
the same structure; differences are noted below.

## What matters here

**The docstrings are the product.** `ForecastingAgent.__doc__` and
`ForecastingContext.system_preamble()` are fed verbatim to the LLM on every session. Edit them as
prompts, not as documentation. Detail belongs in the upstream skills, which load on demand.

**Skill instructions are loaded remotely, from `main`.** `skills.json` points at raw GitHub URLs —
one entry per upstream skill directory, trailing `/` load-bearing (without it Beaker strips the
last path segment instead of appending `SKILL.md`). A fetch failure is silent: Beaker drops the
skill and the agent simply doesn't know it exists. The `network` tests and the scheduled
`skill-health` workflow exist to catch that.

**Skill *execution* needs local files.** Unlike accord-beaker, these skills are not a Python
library the subkernel imports — each is a standalone script run with `uv run --script`, some with
`assets/` and per-script lockfiles. So the setup procedure
(`procedures/python3/setup.py`) maintains a shallow checkout under
`~/.cache/forecasting-skills-beaker/forecasting-skills`, fast-forwarded at each session start so
scripts track the same `main` the instructions were fetched from, and defines `run_skill()` in the
subkernel. Knobs: `FORECASTING_SKILLS_NO_SYNC=1` skips the network; `FORECASTING_SKILLS_HOME`
relocates the checkout.

**Upstream writes for Claude Code, not Beaker.** Two consequences:

- SKILL.md files invoke scripts as `uv run --script ${CLAUDE_SKILL_DIR}/scripts/x.py`.
  `run_skill()` absorbs that convention (and sets `CLAUDE_SKILL_DIR` for the subprocess).
- Some SKILL.md files link resources with a literal `${CLAUDE_SKILL_DIR}/` prefix, which Beaker
  advertises verbatim and which 404s on remote fetch. The agent docstring tells it to strip the
  prefix; `test_every_advertised_resource_resolves` does the same. The real fix is relative links
  upstream.

**Adding/removing a skill upstream** means editing three places here: `skills.json`,
`EXPECTED_SKILLS` in `tests/test_skills.py`, and nothing else. `test_skills_json_tracks_upstream`
compares `skills.json` against the live GitHub listing of `skills/`, so the scheduled CI run
notices upstream drift before you do.

**Beaker 2.0.9 is the floor.** Slugs are underscored (`chirps_fetch` for `chirps-fetch`);
`SkillIntegrationProvider`'s first positional argument means different things in 2.0.9 and dev, so
always pass `skill_paths` by keyword. The rest of the version-skew notes live in accord-beaker's
AGENTS.md and beaker-notebook's own AGENTS.md; they all apply here.

## After changing the context

The Beaker build hook writes context entry-point metadata at install time, so after moving or
renaming the context run `uv sync --reinstall-package forecasting-skills-beaker` (or
`beaker project update`) before trusting `beaker context list`.

## Tests

```bash
uv run pytest -m "not network"   # offline: wiring, procedures, skills.json shape
uv run pytest                    # + live fetch of all skills, upstream drift check
```

`test_forecasting_is_the_context_a_session_opens_on` asserts this context's WEIGHT is strictly
lowest among everything installed in the venv — it will rightly fail in a venv that also has
another WEIGHT-5 context (like accord-beaker) installed. One default per venv is the intent.

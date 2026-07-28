# Report what the forecasting toolchain looks like in this subkernel, for the
# preview panel. Returns a plain JSON-serializable dict as the cell's value.
#
# The two imports below are namespace repair, not for this file (the function
# imports what it needs locally). Beaker orders session startup as: context
# setup procedure, then PythonSubkernel.setup(), whose init code ends with
# `del importlib, os, site, sys` -- so os and sys imported during context setup
# are deleted again. This procedure also runs at preview generation, which
# happens AFTER subkernel setup, so binding them here makes `os` and `sys`
# reliably available in agent and user cells.
import os
import sys
#
# The credential block is the point of this procedure. Four fetchers need
# environment credentials, and a missing one surfaces as a subprocess failure
# partway through a pipeline. Showing presence up front turns that into
# something the forecaster can fix before starting. Presence only -- never
# read, print, or return the value of a credential.


def _forecasting_environment():
    import os
    import shutil
    import subprocess
    from importlib.metadata import PackageNotFoundError, version
    from pathlib import Path

    tools = {}
    uv_path = shutil.which("uv")
    if uv_path:
        try:
            probe = subprocess.run(
                ["uv", "--version"], capture_output=True, text=True, timeout=10,
            )
            tools["uv"] = probe.stdout.strip() or "present"
        except Exception:
            tools["uv"] = "present"
    else:
        tools["uv"] = "not found -- required to run any skill"
    tools["git"] = "present" if shutil.which("git") else "not found"

    home = globals().get("FORECASTING_SKILLS_HOME")
    checkout = {"path": str(home) if home else "setup did not run"}
    if home and (Path(home) / ".git").is_dir():
        try:
            probe = subprocess.run(
                ["git", "-C", str(home), "log", "-1", "--format=%h %cs"],
                capture_output=True, text=True, timeout=10,
            )
            checkout["commit"] = probe.stdout.strip() or "unknown"
        except Exception:
            checkout["commit"] = "unknown"
    else:
        checkout["commit"] = "no checkout"
    notes = dict(globals().get("_fsb_notes", {}))
    if notes:
        checkout["notes"] = notes

    credentials = {
        "ECMWF_DATASTORES_URL + ECMWF_DATASTORES_KEY": {
            "present": bool(
                (os.environ.get("ECMWF_DATASTORES_URL") and os.environ.get("ECMWF_DATASTORES_KEY"))
                or Path("~/.ecmwfdatastoresrc").expanduser().is_file()
            ),
            "used_for": "ecmwf-fetch (ECMWF S2S via ECDS)",
        },
        "EARTHDATA_USERNAME + EARTHDATA_PASSWORD": {
            "present": bool(
                (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"))
                or Path("~/.netrc").expanduser().is_file()
            ),
            "used_for": "imerg-fetch, smap-fetch (NASA Earthdata; .netrc also works)",
        },
        "OPENAQ_API_KEY": {
            "present": bool(os.environ.get("OPENAQ_API_KEY")),
            "used_for": "openaq-fetch",
        },
        "TAHMO_API_USERNAME + TAHMO_API_PASSWORD": {
            "present": bool(
                os.environ.get("TAHMO_API_USERNAME") and os.environ.get("TAHMO_API_PASSWORD")
            ),
            "used_for": "tahmo-fetch",
        },
    }

    packages = {}
    for dist in ("xarray", "zarr", "matplotlib"):
        try:
            packages[dist] = version(dist)
        except PackageNotFoundError:
            packages[dist] = "not installed"

    return {
        "tools": tools,
        "skills_checkout": checkout,
        "credentials": credentials,
        "credential_free_fetchers": [
            "chirps-fetch", "arco-era5-fetch", "cmip6-fetch",
            "dynamical-fetch", "ghcn-daily-fetch", "oisst-fetch",
        ],
        "packages": packages,
    }


_forecasting_environment()

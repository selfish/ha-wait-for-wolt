"""Resolve each supported HA runtime with its matching test harness."""

import subprocess
import sys

HARNESSES = {"2026.7.0": "0.13.344", "2026.9.3": "0.13.366"}

if __name__ == "__main__":
    runtime = sys.argv[1]
    harness = HARNESSES[runtime]
    code = (
        "from importlib.metadata import version; import pytest; "
        f"assert version('homeassistant') == {runtime!r}; "
        "print('Verified Home Assistant', version('homeassistant'), flush=True); "
        "raise SystemExit(pytest.main(['-q']))"
    )
    raise SystemExit(
        subprocess.call(
            [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--python",
                "3.14",
                "--with",
                f"pytest-homeassistant-custom-component=={harness}",
                "python",
                "-c",
                code,
            ]
        )
    )

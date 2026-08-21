#!/usr/bin/env python3
"""Dependency-free entry point for the herdr-git-diff-tui plugin.

Responsibilities (see SPEC.md, section 3):
  1. Locate a system Python (python3, then python; require >= 3.11).
  2. Ensure the plugin-local virtual environment (<plugin_dir>/.venv) exists;
     (re)build it from requirements.txt if missing or broken.
  3. Launch `python -m herdr_git_diff_tui`, forwarding all argv.

Deliberately dependency-free (stdlib only) since it may run before the venv exists.
"""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = PLUGIN_DIR / ".venv"
REQUIREMENTS = PLUGIN_DIR / "requirements.txt"
MIN_PYTHON = (3, 11)


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def find_system_python() -> str:
    for candidate in ("python3", "python"):
        try:
            out = subprocess.run(
                [candidate, "--version"], capture_output=True, text=True, check=True
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        version_str = (out.stdout or out.stderr).strip().split()[-1]
        major, minor = (int(p) for p in version_str.split(".")[:2])
        if (major, minor) >= MIN_PYTHON:
            return candidate
    raise RuntimeError(f"No Python >= {'.'.join(map(str, MIN_PYTHON))} found on PATH")


def build_venv() -> None:
    system_python = find_system_python()
    if not VENV_DIR.exists():
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"], check=True
    )
    if REQUIREMENTS.exists():
        subprocess.run(
            [str(venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            check=True,
        )
    _ = system_python  # currently unused beyond version validation


def venv_is_healthy() -> bool:
    return venv_python().exists()


def main(argv: list[str]) -> int:
    if "--build" in argv or not venv_is_healthy():
        build_venv()
        if "--build" in argv:
            return 0

    result = subprocess.run(
        [str(venv_python()), "-m", "herdr_git_diff_tui", *argv],
        cwd=str(PLUGIN_DIR),
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

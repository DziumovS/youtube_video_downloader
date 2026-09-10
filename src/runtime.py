"""Locate command-line dependencies when an IDE has a minimal PATH."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterator


_SYSTEM_BIN_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/bin"),
)
_HOMEBREW_OPT_DIRS = (Path("/opt/homebrew/opt"), Path("/usr/local/opt"))
_RUNTIME_VERSIONS = {"node": (22, 0, 0), "deno": (2, 3, 0)}


def hidden_subprocess_options() -> dict[str, Any]:
    """Run directly without opening console windows on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", path.parent.parent.name))


def _executable_candidates(name: str) -> Iterator[str]:
    direct_path = shutil.which(name)
    paths = [Path(direct_path)] if direct_path else []
    paths.extend(directory / name for directory in _SYSTEM_BIN_DIRS)
    if name == "node":
        nvm_dir = Path(os.environ.get("NVM_DIR") or Path.home() / ".nvm")
        paths.extend(sorted(nvm_dir.glob("versions/node/*/bin/node"), key=_version_key, reverse=True))
        for prefix in _HOMEBREW_OPT_DIRS:
            paths.extend(sorted(prefix.glob("node@*/bin/node"), key=_version_key, reverse=True))
    elif name == "deno":
        deno_dir = Path(os.environ.get("DENO_INSTALL") or Path.home() / ".deno")
        paths.append(deno_dir / "bin" / name)

    seen = set()
    for path in paths:
        absolute_path = str(path.absolute())
        if absolute_path not in seen and path.is_file() and os.access(path, os.X_OK):
            seen.add(absolute_path)
            yield absolute_path


def find_executable(name: str) -> str | None:
    """Find an executable through PATH and standard standalone installations."""
    return next(_executable_candidates(name), None)


def require_executable(name: str) -> str:
    executable = find_executable(name)
    if executable is not None:
        return executable
    package = {"ffprobe": "ffmpeg", "aria2c": "aria2"}.get(name, name)
    raise RuntimeError(
        f"{name} is required but was not found. Install {package} and add its bin "
        f"directory to PATH (macOS: brew install {package})."
    )


def javascript_runtimes() -> dict[str, dict[str, str]]:
    """Return a usable yt-dlp runtime, or explain a missing dependency early.

    A JavaScript executable alone is insufficient: yt-dlp also needs its EJS
    solver package. Without it yt-dlp misleadingly reports a missing runtime.
    """
    if importlib.util.find_spec("yt_dlp_ejs") is None:
        raise RuntimeError(
            "YouTube support requires yt-dlp-ejs, even when Node.js is installed. "
            "Run 'uv sync' in the project, or install 'yt-dlp[default]' into the "
            "same Python environment used to launch this app."
        )

    rejected = []
    for runtime, minimum_version in _RUNTIME_VERSIONS.items():
        for executable in _executable_candidates(runtime):
            try:
                process = subprocess.run(
                    [executable, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                    **hidden_subprocess_options(),
                )
            except (OSError, subprocess.SubprocessError) as error:
                rejected.append(f"{executable}: {type(error).__name__}")
                continue
            pattern = r"^v(\d+)\.(\d+)\.(\d+)" if runtime == "node" else r"^deno (\d+)\.(\d+)\.(\d+)"
            match = re.match(pattern, process.stdout.strip())
            if match and tuple(map(int, match.groups())) >= minimum_version:
                return {runtime: {"path": executable}}
            rejected.append(f"{executable}: unsupported version {process.stdout.splitlines()[:1]}")

    detail = " Checked: " + "; ".join(rejected) if rejected else ""
    raise RuntimeError(
        "YouTube requires Node.js 22+ or Deno 2.3+. Install a supported runtime "
        "and add it to PATH (macOS: brew install node; NVM: nvm install 22)."
        + detail
    )

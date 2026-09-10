from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from src import runtime


@pytest.fixture(autouse=True)
def isolated_runtime_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    monkeypatch.setattr(runtime, "_SYSTEM_BIN_DIRS", (tmp_path / "homebrew/bin",))
    monkeypatch.setattr(runtime, "_HOMEBREW_OPT_DIRS", (tmp_path / "homebrew/opt",))
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("NVM_DIR", raising=False)
    monkeypatch.delenv("DENO_INSTALL", raising=False)
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda _: object())
    # Tests never execute a host runtime or depend on its installed version.
    monkeypatch.setattr(runtime.subprocess, "run", Mock(side_effect=AssertionError("unexpected execution")))


def executable(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o755)
    return str(path)


def runtime_output(version: str):
    return subprocess.CompletedProcess([], 0, version + "\n", "")


def test_find_executable_prefers_path_and_returns_absolute_path(monkeypatch, tmp_path):
    path_binary = executable(tmp_path / "custom/ffmpeg")
    executable(tmp_path / "homebrew/bin/ffmpeg")
    monkeypatch.setattr(runtime.shutil, "which", lambda _: path_binary)
    assert runtime.find_executable("ffmpeg") == path_binary


@pytest.mark.parametrize("name", ["ffmpeg", "ffprobe", "mp3gain", "aria2c"])
def test_media_dependencies_are_discovered_without_shell_path(tmp_path, name):
    binary = executable(tmp_path / "homebrew/bin" / name)
    assert runtime.require_executable(name) == binary


def test_non_executable_or_missing_dependency_has_actionable_message(tmp_path):
    path = tmp_path / "homebrew/bin/mp3gain"
    path.parent.mkdir(parents=True)
    path.touch(mode=0o644)
    assert runtime.find_executable("mp3gain") is None
    with pytest.raises(RuntimeError, match="brew install mp3gain"):
        runtime.require_executable("mp3gain")


@pytest.mark.parametrize(("name", "package"), [("ffprobe", "ffmpeg"), ("aria2c", "aria2")])
def test_missing_dependency_reports_correct_package(name, package):
    with pytest.raises(RuntimeError, match=f"brew install {package}"):
        runtime.require_executable(name)


def test_supported_node_uses_explicit_path(monkeypatch, tmp_path):
    node = executable(tmp_path / "custom/node")
    monkeypatch.setattr(runtime.shutil, "which", lambda _: node)
    run = Mock(return_value=runtime_output("v22.0.0"))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.javascript_runtimes() == {"node": {"path": node}}
    run.assert_called_once_with(
        [node, "--version"], capture_output=True, text=True, timeout=5,
        check=True, **runtime.hidden_subprocess_options(),
    )


def test_old_path_and_homebrew_nodes_do_not_shadow_nvm(monkeypatch, tmp_path):
    old_path = executable(tmp_path / "path/node")
    old_brew = executable(tmp_path / "homebrew/bin/node")
    newest = executable(tmp_path / ".nvm/versions/node/v22.10.0/bin/node")
    executable(tmp_path / ".nvm/versions/node/v22.9.0/bin/node")
    monkeypatch.setattr(runtime.shutil, "which", lambda _: old_path)
    outputs = {old_path: "v18.20.8", old_brew: "v20.19.0", newest: "v22.10.0"}
    run = Mock(side_effect=lambda args, **_: runtime_output(outputs[args[0]]))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.javascript_runtimes() == {"node": {"path": newest}}
    assert [call.args[0][0] for call in run.call_args_list] == [old_path, old_brew, newest]


def test_nvm_can_be_in_custom_location(monkeypatch, tmp_path):
    nvm_dir = tmp_path / "custom-nvm"
    node = executable(nvm_dir / "versions/node/v22.23.2/bin/node")
    monkeypatch.setenv("NVM_DIR", str(nvm_dir))
    monkeypatch.setattr(runtime.subprocess, "run", Mock(return_value=runtime_output("v22.23.2")))
    assert runtime.javascript_runtimes() == {"node": {"path": node}}


def test_versioned_homebrew_node_is_found_without_unversioned_symlink(monkeypatch, tmp_path):
    executable(tmp_path / "homebrew/opt/node@20/bin/node")
    node = executable(tmp_path / "homebrew/opt/node@22/bin/node")
    monkeypatch.setattr(runtime.subprocess, "run", Mock(return_value=runtime_output("v22.23.2")))
    assert runtime.javascript_runtimes() == {"node": {"path": node}}


@pytest.mark.parametrize("error", [OSError("cannot execute"), subprocess.TimeoutExpired("node", 5), subprocess.CalledProcessError(1, "node")])
def test_broken_node_falls_back_to_deno(monkeypatch, tmp_path, error):
    executable(tmp_path / "homebrew/bin/node")
    deno = executable(tmp_path / ".deno/bin/deno")
    monkeypatch.setattr(runtime.subprocess, "run", Mock(side_effect=[error, runtime_output("deno 2.3.0\nv8 1.0.0")]))
    assert runtime.javascript_runtimes() == {"deno": {"path": deno}}


@pytest.mark.parametrize("version", ["v18.20.8", "not a runtime", "v21.99.99"])
def test_unsupported_runtime_error_includes_path_and_version(monkeypatch, tmp_path, version):
    node = executable(tmp_path / "homebrew/bin/node")
    monkeypatch.setattr(runtime.subprocess, "run", Mock(return_value=runtime_output(version)))
    with pytest.raises(RuntimeError, match=r"Node.js 22\+") as caught:
        runtime.javascript_runtimes()
    assert node in str(caught.value)
    assert version in str(caught.value)


def test_no_runtime_fails_early_with_installation_hint():
    with pytest.raises(RuntimeError, match="nvm install 22"):
        runtime.javascript_runtimes()


def test_missing_ejs_is_reported_even_when_node_exists(monkeypatch, tmp_path):
    executable(tmp_path / "homebrew/bin/node")
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda _: None)
    with pytest.raises(RuntimeError, match=r"yt-dlp-ejs.*uv sync"):
        runtime.javascript_runtimes()
    runtime.subprocess.run.assert_not_called()


def test_windows_subprocesses_do_not_open_console_windows(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert runtime.hidden_subprocess_options() == {"creationflags": 0x08000000}

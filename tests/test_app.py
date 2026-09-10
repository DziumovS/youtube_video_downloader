import runpy
from unittest.mock import patch

import pytest

import app


@pytest.fixture(autouse=True)
def isolated_download_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DOWNLOAD_DIR", str(tmp_path))


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ([""], "URL cannot be empty."),
        (["url", "bad-mode"], "Invalid download mode"),
        (["url", "v", "not-a-number"], "Invalid choice"),
        (["url", "v", "0"], "Invalid choice"),
        (["url", "v", "2"], "Invalid choice"),
    ],
)
def test_main_rejects_bad_input(tmp_path, capsys, answers, expected):
    with (
        patch("builtins.input", side_effect=answers),
        patch("app.get_formats", return_value=[{"id": "18", "height": 360, "size": 1}]),
        patch("app.download") as downloader,
    ):
        assert app.main() == 2

    assert expected in capsys.readouterr().out
    downloader.assert_not_called()


def test_main_handles_no_formats(tmp_path, capsys):
    with (
        patch("builtins.input", side_effect=["url", "v"]),
        patch("app.get_formats", return_value=[]),
    ):
        assert app.main() == 1
    assert "No available formats found." in capsys.readouterr().out


def test_main_downloads_selected_format(tmp_path, capsys):
    formats = [
        {"id": "18", "height": 360, "size": 1024},
        {"id": "137", "height": 1080, "size": 2048},
    ]
    with (
        patch("builtins.input", side_effect=["url", "", "2"]),
        patch("app.get_formats", return_value=formats),
        patch("app.download") as downloader,
    ):
        assert app.main() == 0

    downloader.assert_called_once_with(
        url="url",
        format_id="137",
        download_dir=str(tmp_path),
        concurrent_fragment_downloads=app.CONCURRENT_FRAGMENT_DOWNLOADS,
        proxy=app.PROXY,
        use_aria2c=app.USE_ARIA2C,
    )
    assert "Downloading 1080p" in capsys.readouterr().out


def test_audio_mode_skips_video_format_listing(tmp_path, capsys):
    final_path = tmp_path / "Gorillaz - Feel Good Inc..mp3"
    with (
        patch("builtins.input", side_effect=["url", " A "]),
        patch("app.get_formats") as formats,
        patch("app.download") as video,
        patch("app.download_audio", return_value=final_path) as audio,
    ):
        assert app.main() == 0
    formats.assert_not_called()
    video.assert_not_called()
    audio.assert_called_once_with(
        url="url", download_dir=str(tmp_path),
        concurrent_fragment_downloads=app.CONCURRENT_FRAGMENT_DOWNLOADS,
        proxy=app.PROXY, use_aria2c=app.USE_ARIA2C,
    )
    assert str(final_path) in capsys.readouterr().out


@pytest.mark.parametrize("failure", [RuntimeError("MP3Gain failed"), OSError("disk full")])
def test_failed_audio_never_reports_done(failure, capsys):
    with (
        patch("builtins.input", side_effect=["url", "a"]),
        patch("app.download_audio", side_effect=failure),
    ):
        assert app.main() == 1
    output = capsys.readouterr().out
    assert str(failure) in output
    assert "Done!" not in output


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), EOFError()])
def test_cancelled_input_is_handled(failure, capsys):
    with patch("builtins.input", side_effect=failure):
        assert app.main() == 130
    assert "Cancelled" in capsys.readouterr().out


def test_script_entrypoint_returns_failure_for_empty_url():
    with patch("builtins.input", return_value=""), pytest.raises(SystemExit) as exc:
        runpy.run_path(app.__file__, run_name="__main__")
    assert exc.value.code == 2

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.downloader import _download_options, _retry_delay, download


@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    monkeypatch.setattr("src.downloader.require_executable", lambda name: f"/usr/bin/{name}")


def test_download_builds_resumable_parallel_options(tmp_path: Path):
    manager = MagicMock()
    manager.__enter__.return_value.download.return_value = 0
    progress = MagicMock()

    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager) as ydl,
    ):
        download(
            "https://example.test/video",
            "137",
            str(tmp_path / "new-directory"),
            concurrent_fragment_downloads=4,
            proxy="http://proxy",
            progress_callback=progress,
        )

    options = ydl.call_args.args[0]
    assert options["format"] == "137+bestaudio/137/best"
    assert options["outtmpl"].endswith("new-directory/%(title)s.%(ext)s")
    assert options["merge_output_format"] == "mkv"
    assert options["postprocessors"] == [
        {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"}
    ]
    assert options["skip_unavailable_fragments"] is False
    assert options["concurrent_fragment_downloads"] == 4
    assert options["continuedl"] is True
    assert options["part"] is True
    assert options["ignoreerrors"] is False
    assert options["js_runtimes"] == {"node": {}}
    assert "http_headers" not in options
    assert options["proxy"] == "http://proxy"
    assert options["progress_hooks"] == [progress]
    assert options["postprocessor_hooks"] == [progress]
    assert "external_downloader" not in options
    assert (tmp_path / "new-directory").is_dir()
    manager.__enter__.return_value.download.assert_called_once_with(
        ["https://example.test/video"]
    )


@pytest.mark.parametrize("concurrency", [0, -1, 17, True, 1.5, "4", None])
def test_download_rejects_unsafe_concurrency(tmp_path: Path, concurrency: int):
    with pytest.raises(ValueError, match="between 1 and 16"):
        download("url", "137", str(tmp_path), concurrency)


def test_download_reports_nonzero_exit_code(tmp_path: Path):
    manager = MagicMock()
    manager.__enter__.return_value.download.return_value = 1
    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager),
        pytest.raises(RuntimeError, match="exit code 1"),
    ):
        download("url", "137", str(tmp_path))


def test_download_configures_aria2c_when_available(tmp_path: Path):
    manager = MagicMock()
    manager.__enter__.return_value.download.return_value = 0
    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager) as ydl,
    ):
        download("url", "137", str(tmp_path), 3, use_aria2c=True)

    options = ydl.call_args.args[0]
    assert options["external_downloader"] == {
        "http": "/usr/bin/aria2c", "https": "/usr/bin/aria2c"
    }
    assert options["external_downloader_args"]["aria2c"] == [
        "--max-connection-per-server",
        "3",
        "--split",
        "3",
        "--max-concurrent-downloads",
        "3",
        "--retry-wait",
        "5",
        "--max-tries",
        "10",
        "--min-split-size",
        "1M",
        "--file-allocation",
        "none",
    ]


def test_download_rejects_missing_aria2c(tmp_path: Path):
    with (
        patch("src.downloader.require_executable", side_effect=RuntimeError("aria2c not installed")),
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        pytest.raises(RuntimeError, match="not installed"),
    ):
        download("url", "137", str(tmp_path), use_aria2c=True)


def test_video_options_register_real_remux_postprocessor(tmp_path, monkeypatch):
    from yt_dlp import YoutubeDL
    from yt_dlp.postprocessor.ffmpeg import FFmpegVideoRemuxerPP

    monkeypatch.setattr("src.downloader._javascript_runtimes", lambda: {})
    options = _download_options("18", str(tmp_path), 4, None, False)
    options.pop("ffmpeg_location")
    with YoutubeDL(options) as ydl:
        assert any(isinstance(pp, FFmpegVideoRemuxerPP) for pp in ydl._pps["post_process"])


def test_retries_back_off_but_remain_bounded():
    assert [_retry_delay(attempt) for attempt in range(1, 8)] == [2, 4, 8, 16, 32, 32, 32]


def test_parallel_worker_failure_is_reported_as_download_failure(tmp_path):
    manager = MagicMock()
    manager.__enter__.return_value.download.side_effect = ValueError("write to closed file")
    with (
        patch("src.downloader._javascript_runtimes", return_value={}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager),
        pytest.raises(RuntimeError, match="Download could not complete"),
    ):
        download("url", "137", str(tmp_path))

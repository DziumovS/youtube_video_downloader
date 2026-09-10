from pathlib import Path

import pytest

from src import video


@pytest.fixture
def fake_video_download(monkeypatch):
    state = {
        "exit_code": 0,
        "report_file": True,
        "write_file": True,
        "filename": "Example.mkv",
        "download_error": None,
    }

    class FakeYDL:
        def __init__(self, options):
            state["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def add_post_processor(self, processor, when):
            assert when == "after_move"
            self.processor = processor

        def download(self, urls):
            state["urls"] = urls
            if state["download_error"]:
                raise state["download_error"]
            path = Path(state["options"]["outtmpl"]).parent / state["filename"]
            if state["write_file"]:
                path.write_bytes(b"final mkv")
            if state["report_file"]:
                self.processor.run({"filepath": str(path)})
            return state["exit_code"]

    monkeypatch.setattr(video.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr("src.downloader.require_executable", lambda _name: "/tools/ffmpeg")
    monkeypatch.setattr("src.downloader._javascript_runtimes", lambda: {"node": {}})
    return state


def test_download_video_returns_exact_final_file(tmp_path, fake_video_download):
    progress_events = []
    result = video.download_video(
        "https://youtu.be/abc",
        "137",
        str(tmp_path),
        concurrent_fragment_downloads=3,
        proxy="http://proxy",
        progress_callback=progress_events.append,
    )
    assert result == tmp_path / "Example.mkv"
    assert result.read_bytes() == b"final mkv"
    assert fake_video_download["urls"] == ["https://youtu.be/abc"]
    options = fake_video_download["options"]
    assert options["format"] == "137+bestaudio/137/best"
    assert options["concurrent_fragment_downloads"] == 3
    assert options["proxy"] == "http://proxy"
    assert options["progress_hooks"] == [progress_events.append]
    assert options["postprocessor_hooks"] == [progress_events.append]
    assert progress_events == [{"status": "processing", "stage": "finalizing"}]
    assert not list(tmp_path.glob(".video-*"))


def test_download_video_never_overwrites_existing_file(tmp_path, fake_video_download):
    (tmp_path / "Example.mkv").write_bytes(b"old")
    (tmp_path / "Example (2).mkv").write_bytes(b"also old")
    result = video.download_video("url", "18", str(tmp_path))
    assert result.name == "Example (3).mkv"
    assert (tmp_path / "Example.mkv").read_bytes() == b"old"


def test_publish_video_falls_back_for_unsafe_empty_stem(tmp_path):
    source = tmp_path / " .mkv"
    source.write_bytes(b"mkv")
    assert video._publish_video(source, tmp_path).name == "video.mkv"


@pytest.mark.parametrize("state_key", ["report_file", "write_file"])
def test_download_video_rejects_missing_output(tmp_path, fake_video_download, state_key):
    fake_video_download[state_key] = False
    with pytest.raises(RuntimeError, match="video file|valid MKV"):
        video.download_video("url", "18", str(tmp_path))
    assert not list(tmp_path.glob("*.mkv"))


def test_download_video_rejects_wrong_extension(tmp_path, fake_video_download):
    fake_video_download["filename"] = "Example.mp4"
    with pytest.raises(RuntimeError, match="valid MKV.*preserved"):
        video.download_video("url", "18", str(tmp_path))
    assert list(tmp_path.glob(".video-*/Example.mp4"))


def test_download_video_reports_exit_code_and_preserves_partial(tmp_path, fake_video_download):
    fake_video_download["exit_code"] = 1
    with pytest.raises(RuntimeError, match="exit code 1.*preserved"):
        video.download_video("url", "18", str(tmp_path))
    assert list(tmp_path.glob(".video-*/Example.mkv"))


def test_download_video_translates_parallel_writer_error(tmp_path, fake_video_download):
    fake_video_download["download_error"] = ValueError("closed file")
    with pytest.raises(RuntimeError, match="Download could not complete"):
        video.download_video("url", "18", str(tmp_path))
    assert not list(tmp_path.glob(".video-*"))

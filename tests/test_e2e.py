import os
import json
import subprocess

import pytest

from src.downloader import download, get_formats
from src.audio import download_audio
from src.runtime import require_executable
from mutagen.apev2 import APEv2


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_YOUTUBE_INTEGRATION") != "1",
        reason="set RUN_YOUTUBE_INTEGRATION=1 to download test media from YouTube",
    ),
]

URL = (
    "https://www.youtube.com/watch?v=HyHNuVaZJ-k"
    "&list=PL6Pd9lCgW0BYCdrI9px5DhoUb8hcyr0EY&index=26"
)


def probe(path):
    result = subprocess.run(
        [require_executable("ffprobe"), "-v", "error", "-show_streams", "-show_format",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def test_youtube_video_with_minimal_ide_path(tmp_path, monkeypatch, capfd):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    formats = get_formats(URL)
    assert formats, "YouTube returned no video formats"
    selected = next(item for item in formats if item["height"] == 1080)
    download(URL, selected["id"], str(tmp_path))
    files = list(tmp_path.glob("*.mkv"))
    assert len(files) == 1
    streams = probe(files[0])["streams"]
    assert any(stream["codec_type"] == "video" and stream["height"] == 1080 for stream in streams)
    assert any(stream["codec_type"] == "audio" for stream in streams)
    assert "No supported JavaScript runtime" not in capfd.readouterr().err


def test_youtube_mp3_and_gain_with_minimal_ide_path(tmp_path, monkeypatch, capfd):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    path = download_audio(URL, str(tmp_path))
    assert path.name == "Gorillaz - Feel Good Inc..mp3"
    assert [stream["codec_name"] for stream in probe(path)["streams"]] == ["mp3"]
    assert "MP3GAIN_UNDO" in APEv2(path)
    assert list(tmp_path.iterdir()) == [path]
    assert "No supported JavaScript runtime" not in capfd.readouterr().err

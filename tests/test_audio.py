import json
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest
import yt_dlp
from mutagen.apev2 import APEv2
from yt_dlp.extractor.common import InfoExtractor

from src import audio
from src.runtime import require_executable


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Gorillaz - Feel Good Inc. (Official Video)", "Gorillaz - Feel Good Inc."),
        ("Artist - Song (Official Music Video) [HD]", "Artist - Song"),
        ("Artist - Song [Lyrics]", "Artist - Song"),
        (
            "Toss A Coin To Your Witcher (Lyric Video from The Witcher "
            "(Music from the Netflix Original Series))",
            "Toss A Coin To Your Witcher",
        ),
        (
            "Song (Official Video from an Album (Deluxe Edition))",
            "Song",
        ),
        ("Artist - Song - Official Video", "Artist - Song"),
        ("Artist - Song (Live at Wembley) [4K]", "Artist - Song (Live at Wembley)"),
        ("Artist - Song (Remix)", "Artist - Song (Remix)"),
        ("Artist - Song (Acoustic Version)", "Artist - Song (Acoustic Version)"),
        ("Artist - Official Video Games", "Artist - Official Video Games"),
        ("Artist - Video", "Artist - Video"),
        ("", "audio"),
    ],
)
def test_clean_audio_title_preserves_meaningful_versions(title, expected):
    assert audio.clean_audio_title(title) == expected


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        (
            {
                "title": "Breaking the Habit (Official Music Video) [HD UPGRADE] – Linkin Park",
                "uploader": "Linkin Park",
            },
            "Linkin Park - Breaking the Habit",
        ),
        (
            {"title": "Breaking the Habit (Official Music Video) [HD UPGRADE] – Linkin Park"},
            "Linkin Park - Breaking the Habit",
        ),
        (
            {"title": "Gorillaz - Feel Good Inc. (Official Video)", "channel": "Gorillaz"},
            "Gorillaz - Feel Good Inc.",
        ),
        (
            {"title": "Song title", "track": "Real Song", "artist": "Real Artist"},
            "Real Artist - Real Song",
        ),
        (
            {
                "title": "Song title",
                "track": "Real Song",
                "artists": ["Artist", "Guest", "Artist"],
            },
            "Artist & Guest - Real Song",
        ),
        (
            {
                "title": "Song title",
                "track": "Real Song",
                "creators": ["Composer A", "Composer B"],
            },
            "Composer A & Composer B - Real Song",
        ),
        (
            {"title": "Song title", "track": "Real Song", "artists": [None], "artist": "Artist"},
            "Artist - Real Song",
        ),
        (
            {"title": "Song (Live)", "creator": "Artist"},
            "Artist - Song (Live)",
        ),
        (
            {"title": "Artist - Song (Remix)", "uploader": "Unrelated Channel"},
            "Artist - Song (Remix)",
        ),
        (
            {"title": "Artist - Song - Extended", "uploader": "Unrelated Channel"},
            "Artist - Song - Extended",
        ),
        (
            {
                "title": "Heaven and Hell - Jeremy Blake",
                "uploader": "LIMO Recording Studio",
                "channel": "LIMO Recording Studio",
                "tags": ["Jeremy Blake", "Cinematic", "Dark"],
            },
            "Jeremy Blake - Heaven and Hell",
        ),
        (
            {
                "title": "Artist - Song",
                "tags": ["Cinematic", 123, "Unrelated topic"],
            },
            "Artist - Song",
        ),
        (
            {"title": "Artist - Song", "tags": "Artist"},
            "Artist - Song",
        ),
        (
            {"title": "Artist - Song", "uploader": "Artist - Topic"},
            "Artist - Song",
        ),
        ({"id": "video-id"}, "video-id"),
        ({}, "audio"),
    ],
)
def test_audio_file_title_uses_artist_track_order(info, expected):
    assert audio.audio_file_title(info) == expected


@pytest.fixture
def fake_download(monkeypatch):
    state = {"exit_code": 0, "report_file": True, "write_file": True, "info": {}}

    class FakeYDL:
        def __init__(self, options):
            state["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def add_post_processor(self, pp, when):
            assert when == "after_move"
            self.capture = pp

        def download(self, urls):
            state["urls"] = urls
            path = Path(state["options"]["outtmpl"]).parent / "converted.mp3"
            if state["write_file"]:
                path.write_bytes(b"downloaded mp3")
            if state["report_file"]:
                self.capture.run(
                    {
                        "filepath": str(path),
                        "title": "Gorillaz - Feel Good Inc. (Official Video)",
                        "ext": "mp3",
                        **state["info"],
                    }
                )
            return state["exit_code"]

    monkeypatch.setattr(audio.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(audio, "require_executable", lambda name: f"/tools/{name}")
    monkeypatch.setattr(audio, "lookup_track_credit", lambda *_args: None)
    monkeypatch.setattr("src.downloader._javascript_runtimes", lambda: {"node": {}})
    # Runtime preflight in shared video options is outside these tests' scope.
    monkeypatch.setattr("src.downloader.require_executable", lambda name: f"/tools/{name}", raising=False)
    state["calls"] = []
    monkeypatch.setattr(
        audio.subprocess, "run", lambda *args, **kwargs: state["calls"].append((args, kwargs))
    )
    return state


def test_download_audio_normalizes_only_new_file_without_a_shell(tmp_path, fake_download):
    existing = tmp_path / "unrelated.mp3"
    existing.write_bytes(b"existing song")
    progress_events = []
    result = audio.download_audio(
        "https://example.test/song",
        str(tmp_path),
        3,
        proxy="http://proxy",
        progress_callback=progress_events.append,
    )

    assert result == tmp_path / "Gorillaz - Feel Good Inc..mp3"
    assert result.read_bytes() == b"downloaded mp3"
    assert existing.read_bytes() == b"existing song"
    assert fake_download["urls"] == ["https://example.test/song"]
    options = fake_download["options"]
    assert options["format"] == "bestaudio"
    assert options["concurrent_fragment_downloads"] == 3
    assert options["proxy"] == "http://proxy"
    assert options["progress_hooks"] == [progress_events.append]
    assert options["postprocessor_hooks"] == [progress_events.append]
    assert options["postprocessors"] == [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
    ]
    assert "merge_output_format" not in options
    assert "remuxvideo" not in options
    args, kwargs = fake_download["calls"][0]
    assert args[0] == ["/tools/mp3gain", "-r", "-d", "10.5", "-f", str(result)]
    assert kwargs["shell"] is False
    assert kwargs["check"] is True
    assert kwargs["capture_output"] is True
    assert kwargs["input"] == "y\n"
    assert "stdin" not in kwargs
    assert progress_events == [
        {"status": "processing", "stage": "finalizing"},
        {"status": "processing", "stage": "normalizing_audio"},
    ]
    assert not list(tmp_path.glob(".audio-*"))


def test_audio_name_collision_never_overwrites_a_song(tmp_path, fake_download):
    existing = tmp_path / "Gorillaz - Feel Good Inc..mp3"
    existing.write_bytes(b"original")
    second = tmp_path / "Gorillaz - Feel Good Inc. (2).mp3"
    second.write_bytes(b"second original")
    result = audio.download_audio("url", str(tmp_path))
    assert result.name == "Gorillaz - Feel Good Inc. (3).mp3"
    assert existing.read_bytes() == b"original"
    assert second.read_bytes() == b"second original"


def test_download_audio_publishes_requested_artist_first_name(tmp_path, fake_download):
    fake_download["info"] = {
        "title": "Breaking the Habit (Official Music Video) [HD UPGRADE] – Linkin Park",
        "uploader": "Linkin Park",
    }
    result = audio.download_audio("url", str(tmp_path))
    assert result.name == "Linkin Park - Breaking the Habit.mp3"


def test_download_audio_uses_exact_artist_tag_from_non_artist_channel(tmp_path, fake_download):
    fake_download["info"] = {
        "title": "Heaven and Hell - Jeremy Blake",
        "uploader": "LIMO Recording Studio",
        "tags": ["Jeremy Blake", "Cinematic", "Dark"],
    }
    result = audio.download_audio("url", str(tmp_path))
    assert result.name == "Jeremy Blake - Heaven and Hell.mp3"


def test_download_audio_uses_catalog_fallback_for_all_artists(tmp_path, fake_download, monkeypatch):
    fake_download["info"] = {
        "title": "Toss A Coin To Your Witcher "
        "(Lyric Video from The Witcher (Music from the Netflix Original Series))",
        "duration": 190,
        "tags": ["sonya belousova", "giona ostinelli", "joey batey"],
    }
    monkeypatch.setattr(
        audio,
        "lookup_track_credit",
        lambda *_args: (
            "Sonya Belousova & Giona Ostinelli ft. Joey Batey",
            "Toss a Coin to Your Witcher",
        ),
    )
    result = audio.download_audio("url", str(tmp_path))
    assert result.name == (
        "Sonya Belousova & Giona Ostinelli ft. Joey Batey - "
        "Toss a Coin to Your Witcher.mp3"
    )


def test_mp3gain_failure_reports_and_preserves_download(tmp_path, fake_download, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="cannot update gain")

    monkeypatch.setattr(audio.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="cannot update gain.*preserved at"):
        audio.download_audio("url", str(tmp_path))
    assert (tmp_path / "Gorillaz - Feel Good Inc..mp3").read_bytes() == b"downloaded mp3"
    assert not list(tmp_path.glob(".audio-*"))


def test_missing_mp3gain_fails_before_download(tmp_path, fake_download, monkeypatch):
    def require(name):
        if name == "mp3gain":
            raise RuntimeError("mp3gain is not installed")
        return f"/tools/{name}"

    monkeypatch.setattr(audio, "require_executable", require)
    with pytest.raises(RuntimeError, match="mp3gain is not installed"):
        audio.download_audio("url", str(tmp_path))
    assert "urls" not in fake_download
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("state_key", ["report_file", "write_file"])
def test_incomplete_postprocessing_does_not_claim_success(tmp_path, fake_download, state_key):
    fake_download[state_key] = False
    with pytest.raises(RuntimeError, match="MP3 file"):
        audio.download_audio("url", str(tmp_path))
    assert fake_download["calls"] == []
    assert not list(tmp_path.glob("*.mp3"))


def test_failed_download_preserves_partial_file(tmp_path, fake_download):
    fake_download["exit_code"] = 1
    with pytest.raises(RuntimeError, match="exit code 1.*preserved at"):
        audio.download_audio("url", str(tmp_path))
    partial_files = list(tmp_path.glob(".audio-*/converted.mp3"))
    assert len(partial_files) == 1
    assert partial_files[0].read_bytes() == b"downloaded mp3"
    assert fake_download["calls"] == []


def test_published_title_cannot_escape_download_directory(tmp_path):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"mp3")
    result = audio._publish_mp3(source, tmp_path, "../../outside (Official Video)")
    assert result.parent == tmp_path
    assert result.read_bytes() == b"mp3"


@pytest.mark.parametrize("title", [".", "..", " . "])
def test_title_without_usable_filename_has_safe_fallback(tmp_path, title):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"mp3")
    result = audio._publish_mp3(source, tmp_path, title)
    assert result.name == "audio.mp3"


def test_mp3gain_os_error_preserves_the_new_mp3(tmp_path, fake_download, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(audio.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="permission denied.*preserved at"):
        audio.download_audio("url", str(tmp_path))
    assert (tmp_path / "Gorillaz - Feel Good Inc..mp3").is_file()


def test_real_audio_download_conversion_and_gain_with_local_fixture(tmp_path, monkeypatch):
    """Exercise real yt-dlp postprocessors and installed binaries without YouTube."""
    try:
        ffprobe = require_executable("ffprobe")
        require_executable("ffmpeg")
        require_executable("mp3gain")
    except RuntimeError as error:
        pytest.skip(str(error))
    fixture = tmp_path / "fixture.wav"
    with wave.open(str(fixture), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(
            b"".join(
                struct.pack("<h", int(2000 * math.sin(2 * math.pi * 440 * sample / 44100)))
                for sample in range(44100 * 2)
            )
        )

    class AudioFixtureIE(InfoExtractor):
        _VALID_URL = r"audiofixture:(?P<id>\w+)"

        def _real_extract(self, url):
            return {
                "id": self._match_id(url),
                "title": "Fixture - Song (Official Video)",
                "url": fixture.as_uri(),
                "ext": "wav",
                "vcodec": "none",
                "acodec": "pcm_s16le",
            }

    real_ydl = yt_dlp.YoutubeDL
    file_responses = []

    def local_ydl(options):
        ydl = real_ydl({**options, "enable_file_urls": True, "quiet": True}, auto_init=False)
        ydl.add_info_extractor(AudioFixtureIE())
        urlopen = ydl.urlopen

        def track_file_response(request):
            response = urlopen(request)
            file_responses.append(response)
            return response

        ydl.urlopen = track_file_response
        return ydl

    monkeypatch.setattr(audio.yt_dlp, "YoutubeDL", local_ydl)
    progress_events = []
    try:
        result = audio.download_audio(
            "audiofixture:test",
            str(tmp_path / "downloads"),
            progress_callback=progress_events.append,
        )
    finally:
        # file:// is enabled only in this fixture. Its urllib response needs
        # explicit closure when yt-dlp reads exactly the reported file length.
        for response in file_responses:
            response.close()
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(result)],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(probe.stdout)
    assert result.name == "Fixture - Song.mp3"
    assert [stream["codec_name"] for stream in metadata["streams"]] == ["mp3"]
    assert float(metadata["format"]["duration"]) >= 2
    # MP3Gain writes APEv2 tags; ffprobe only exposes the ID3 tags here.
    assert "MP3GAIN_UNDO" in APEv2(result)
    assert not list(result.parent.glob(".audio-*"))
    assert any(event.get("status") == "downloading" for event in progress_events)
    assert any(event.get("status") == "finished" for event in progress_events)
    assert any(event.get("postprocessor") == "ExtractAudio" for event in progress_events)
    assert {event.get("stage") for event in progress_events} >= {
        "finalizing",
        "normalizing_audio",
    }

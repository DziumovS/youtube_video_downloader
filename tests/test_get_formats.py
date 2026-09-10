from unittest.mock import MagicMock, patch

import pytest

from src.downloader import _embedded_content_length, get_formats


def youtube_dl_returning(info):
    manager = MagicMock()
    manager.__enter__.return_value.extract_info.return_value = info
    return manager


def test_get_formats_selects_best_stream_and_counts_audio_regardless_of_order():
    info = {
        "formats": [
            {
                "format_id": "720-muxed",
                "height": 720,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "filesize": 80,
                "fps": 30,
                "tbr": 800,
            },
            {
                "format_id": "1080-low",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": 200,
                "fps": 30,
                "tbr": 1000,
            },
            {
                "format_id": "audio",
                "vcodec": "none",
                "acodec": "opus",
                "filesize_approx": 25,
            },
            {
                "format_id": "1080-high",
                "height": 1080.0,
                "vcodec": "vp9",
                "acodec": "none",
                "filesize": 190,
                "fps": 60,
                "tbr": 900,
            },
            {
                "format_id": "1080-worse",
                "height": 1080,
                "vcodec": "vp9",
                "acodec": "none",
                "filesize": 180,
                "fps": 30,
                "tbr": 700,
            },
            {"format_id": "storyboard", "vcodec": "none", "acodec": "none"},
        ]
    }

    manager = youtube_dl_returning(info)
    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager) as ydl,
    ):
        formats = get_formats("https://example.test/video", proxy="http://proxy")

    assert formats == [
        {"id": "720-muxed", "height": 720, "size": 80},
        {"id": "1080-high", "height": 1080, "size": 215},
    ]
    ydl.assert_called_once_with(
        {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "js_runtimes": {"node": {}},
            "proxy": "http://proxy",
        }
    )
    manager.__enter__.return_value.extract_info.assert_called_once_with(
        "https://example.test/video", download=False
    )


@pytest.mark.parametrize(
    "info", [None, {}, {"formats": None}, {"formats": "bad"}, {"formats": []}]
)
def test_get_formats_handles_missing_format_data(info):
    manager = youtube_dl_returning(info)
    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager),
    ):
        assert get_formats("https://example.test/video") == []


def test_get_formats_ignores_malformed_streams_and_unknown_sizes():
    info = {
        "formats": [
            None,
            {"format_id": "bad-height", "height": "720", "vcodec": "avc1"},
            {"height": 720, "vcodec": "avc1"},
            {
                "format_id": 123,
                "height": 360,
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": -1,
            },
        ]
    }
    manager = youtube_dl_returning(info)
    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager),
    ):
        assert get_formats("https://example.test/video") == [
            {"id": "123", "height": 360, "size": 0}
        ]


def test_get_formats_estimates_missing_sizes_from_duration_and_bitrate():
    info = {
        "duration": 80,
        "formats": [
            {
                "format_id": "audio",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 100,
            },
            {
                "format_id": "video",
                "height": 720,
                "vcodec": "vp9",
                "acodec": "none",
                "tbr": 900,
            },
        ],
    }
    manager = youtube_dl_returning(info)
    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager),
    ):
        assert get_formats("https://example.test/video") == [
            {"id": "video", "height": 720, "size": 10_000_000}
        ]


def test_get_formats_prefers_encoded_hls_content_length_over_bitrate_estimate():
    info = {
        "duration": 3008,
        "formats": [
            {
                "format_id": "audio",
                "vcodec": "none",
                "acodec": "opus",
                "filesize": 48_133_761,
            },
            {
                "format_id": "616",
                "height": 1080,
                "vcodec": "vp9",
                "acodec": "none",
                "tbr": 5013.123,
                "filesize_approx": 1_884_826_238,
                "url": "https://example.test/sgovp/"
                "clen%3D898537143%3Bdur%3D3007.708/playlist/index.m3u8",
            },
        ],
    }
    manager = youtube_dl_returning(info)
    with (
        patch("src.downloader._javascript_runtimes", return_value={"node": {}}),
        patch("src.downloader.yt_dlp.YoutubeDL", return_value=manager),
    ):
        assert get_formats("https://example.test/video") == [
            {"id": "616", "height": 1080, "size": 946_670_904}
        ]


@pytest.mark.parametrize(
    ("stream", "expected"),
    [
        ({"url": "https://example.test/clen/12345/file"}, 12345),
        ({"url": "unrelated", "manifest_url": "https://x/clen=6789&x=1"}, 6789),
        ({"url": "https://example.test/clen=0;dur=1"}, 0),
        ({"url": 123, "manifest_url": None}, 0),
    ],
)
def test_embedded_content_length_handles_supported_and_invalid_values(stream, expected):
    assert _embedded_content_length(stream) == expected

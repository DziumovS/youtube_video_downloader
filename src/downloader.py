from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote

import yt_dlp

from .models import VideoFormat
from .runtime import javascript_runtimes as _javascript_runtimes, require_executable


DEFAULT_CONCURRENT_DOWNLOADS = 4
MAX_CONCURRENT_DOWNLOADS = 16
ProgressCallback = Callable[[dict[str, Any]], None]
_CONTENT_LENGTH = re.compile(r"(?:^|[/;?&])clen(?:=|/)(\d+)(?=$|[/;?&])")


def format_size(size: Optional[int]) -> str:
    """Format an estimated byte count for display."""
    if not size or size <= 0:
        return "unknown"
    return f"~{size / 1_000_000:.0f} MB"


def _embedded_content_length(stream: dict[str, Any]) -> int:
    """Read YouTube's encoded content length when yt-dlp omits filesize."""
    for field in ("url", "manifest_url"):
        value = stream.get(field)
        if not isinstance(value, str):
            continue
        match = _CONTENT_LENGTH.search(unquote(value))
        if match:
            size = int(match.group(1))
            if size > 0:
                return size
    return 0


def _stream_size(stream: dict[str, Any], duration: Any = None) -> int:
    """Return the best non-negative size reported by yt-dlp."""
    size = stream.get("filesize") or 0
    if isinstance(size, (int, float)) and size > 0:
        return int(size)

    embedded_size = _embedded_content_length(stream)
    if embedded_size:
        return embedded_size

    size = stream.get("filesize_approx") or 0
    if isinstance(size, (int, float)) and size > 0:
        return int(size)

    bitrate = stream.get("tbr") or stream.get("abr") or 0
    if (
        isinstance(bitrate, (int, float))
        and bitrate > 0
        and isinstance(duration, (int, float))
        and duration > 0
    ):
        return int(bitrate * 1000 * duration / 8)
    return 0


def _video_score(stream: dict[str, Any]) -> tuple[int, float, float, int]:
    """Prefer video-only, high frame-rate/bitrate streams at one resolution."""
    return (
        int(stream.get("acodec") == "none"),
        float(stream.get("fps") or 0),
        float(stream.get("tbr") or 0),
        _stream_size(stream),
    )


def get_formats(url: str, proxy: Optional[str] = None) -> list[VideoFormat]:
    """Return the best downloadable video stream for each available height."""
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "js_runtimes": _javascript_runtimes(),
    }
    if proxy:
        ydl_opts["proxy"] = proxy

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        return []

    formats = info.get("formats")
    if not isinstance(formats, list):
        return []

    duration = info.get("duration")
    audio_sizes = [
        _stream_size(stream, duration)
        for stream in formats
        if isinstance(stream, dict)
        and stream.get("acodec") not in (None, "none")
        and stream.get("vcodec") == "none"
    ]
    best_audio_size = max(audio_sizes, default=0)

    videos_by_height: dict[int, dict[str, Any]] = {}
    for stream in formats:
        if not isinstance(stream, dict):
            continue
        height = stream.get("height")
        format_id = stream.get("format_id")
        if (
            stream.get("vcodec") in (None, "none")
            or not isinstance(height, (int, float))
            or height <= 0
            or format_id is None
        ):
            continue

        height = int(height)
        current = videos_by_height.get(height)
        if current is None or _video_score(stream) > _video_score(current):
            videos_by_height[height] = stream

    result = [
        VideoFormat(
            id=str(stream["format_id"]),
            height=height,
            size=_stream_size(stream, duration)
            + (best_audio_size if stream.get("acodec") == "none" else 0),
        )
        for height, stream in videos_by_height.items()
    ]
    return sorted(result, key=lambda stream: stream["height"])


def _retry_delay(attempt: int) -> float:
    """Avoid immediately hammering a server after transient HTTP failures."""
    return 2 ** min(attempt, 5)


def _download_options(
    format_id: str,
    download_dir: str,
    concurrent_fragment_downloads: int,
    proxy: Optional[str],
    use_aria2c: bool,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    if (
        type(concurrent_fragment_downloads) is not int
        or not 1 <= concurrent_fragment_downloads <= MAX_CONCURRENT_DOWNLOADS
    ):
        raise ValueError(
            f"concurrent_fragment_downloads must be between 1 and "
            f"{MAX_CONCURRENT_DOWNLOADS}"
        )

    options: dict[str, Any] = {
        "format": f"{format_id}+bestaudio/{format_id}/best",
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "merge_output_format": "mkv",
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"}],
        "ffmpeg_location": str(Path(require_executable("ffmpeg")).parent),
        "concurrent_fragment_downloads": concurrent_fragment_downloads,
        "continuedl": True,
        "part": True,
        "retries": 10,
        "fragment_retries": 10,
        "skip_unavailable_fragments": False,
        "retry_sleep_functions": {"http": _retry_delay, "fragment": _retry_delay},
        "file_access_retries": 3,
        "js_runtimes": _javascript_runtimes(),
        "writesubtitles": False,
        "keepvideo": False,
        "ignoreerrors": False,
        "noplaylist": True,
    }
    if proxy:
        options["proxy"] = proxy

    if progress_callback:
        options["progress_hooks"] = [progress_callback]
        options["postprocessor_hooks"] = [progress_callback]

    if use_aria2c:
        aria2c = require_executable("aria2c")
        options.update(
            {
                # Keep HLS/DASH fragments on yt-dlp's bounded native pool.
                "external_downloader": {"http": aria2c, "https": aria2c},
                "external_downloader_args": {
                    "aria2c": [
                        "--max-connection-per-server",
                        str(concurrent_fragment_downloads),
                        "--split",
                        str(concurrent_fragment_downloads),
                        "--max-concurrent-downloads",
                        str(concurrent_fragment_downloads),
                        "--retry-wait",
                        "5",
                        "--max-tries",
                        "10",
                        "--min-split-size",
                        "1M",
                        "--file-allocation",
                        "none",
                    ]
                },
            }
        )

    return options


def download(
    url: str,
    format_id: str,
    download_dir: str,
    concurrent_fragment_downloads: int = DEFAULT_CONCURRENT_DOWNLOADS,
    proxy: Optional[str] = None,
    use_aria2c: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Download one video and fail loudly if yt-dlp cannot complete it."""
    options = _download_options(
        format_id,
        download_dir,
        concurrent_fragment_downloads,
        proxy,
        use_aria2c,
        progress_callback,
    )
    os.makedirs(download_dir, exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            exit_code = ydl.download([url])
    except ValueError as error:
        # A failed parallel fragment can close the shared output while another
        # worker is appending. yt-dlp then raises ValueError instead of DownloadError.
        raise RuntimeError(f"Download could not complete: {error}") from error
    if exit_code:
        raise RuntimeError(f"yt-dlp failed with exit code {exit_code}")

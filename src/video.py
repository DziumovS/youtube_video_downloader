from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.postprocessor import PostProcessor

from .downloader import DEFAULT_CONCURRENT_DOWNLOADS, ProgressCallback, _download_options


class _CaptureVideoPP(PostProcessor):
    """Capture yt-dlp's final path after merge/remux and file moves."""

    def __init__(self) -> None:
        super().__init__()
        self.result: dict[str, Any] | None = None

    def run(self, information: dict[str, Any]):
        self.result = information.copy()
        return [], information


def _publish_video(source: Path, directory: Path) -> Path:
    stem = source.stem.encode("utf-8")[:220].decode("utf-8", errors="ignore").strip()
    if stem in {"", ".", ".."}:
        stem = "video"
    index = 1
    while True:
        suffix = "" if index == 1 else f" ({index})"
        destination = directory / f"{stem}{suffix}.mkv"
        try:
            os.link(source, destination)
            return destination
        except FileExistsError:
            index += 1


def download_video(
    url: str,
    format_id: str,
    download_dir: str,
    concurrent_fragment_downloads: int = DEFAULT_CONCURRENT_DOWNLOADS,
    proxy: str | None = None,
    use_aria2c: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Download, merge and atomically publish one MKV, returning its exact path."""
    directory = Path(download_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".video-", dir=directory))
    options = _download_options(
        format_id,
        str(staging),
        concurrent_fragment_downloads,
        proxy,
        use_aria2c,
        progress_callback,
    )
    capture = _CaptureVideoPP()
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.add_post_processor(capture, when="after_move")
            try:
                exit_code = ydl.download([url])
            except ValueError as error:
                raise RuntimeError(f"Download could not complete: {error}") from error
        if exit_code:
            raise RuntimeError(f"yt-dlp failed with exit code {exit_code}")
        if progress_callback:
            progress_callback({"status": "processing", "stage": "finalizing"})
        info = capture.result
        if not info or not isinstance(info.get("filepath"), str):
            raise RuntimeError("yt-dlp did not report a completed video file")
        source = Path(info["filepath"]).resolve()
        if (
            not source.is_relative_to(staging.resolve())
            or source.suffix.lower() != ".mkv"
            or not source.is_file()
            or source.stat().st_size == 0
        ):
            raise RuntimeError("yt-dlp did not produce a valid MKV file")
        destination = _publish_video(source, directory)
    except Exception as error:
        if any(staging.iterdir()):
            raise RuntimeError(
                f"{error}. Partial video files are preserved at: {staging}"
            ) from error
        staging.rmdir()
        raise
    shutil.rmtree(staging)
    return destination

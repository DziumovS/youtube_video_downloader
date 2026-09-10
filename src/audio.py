from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.postprocessor import PostProcessor
from yt_dlp.utils import sanitize_filename

from .downloader import DEFAULT_CONCURRENT_DOWNLOADS, ProgressCallback, _download_options
from .metadata import lookup_track_credit
from .runtime import hidden_subprocess_options, require_executable


_COSMETIC_LABEL = re.compile(
    r"(?:official\s+)?(?:music\s+)?video(?:\s+(?:hd|hq|uhd|4k|8k))?"
    r"|official\s+audio"
    r"|(?:official\s+)?lyrics?(?:\s+video)?"
    r"|(?:hd|hq|uhd|4k|8k|1080p|720p)"
    r"(?:\s+(?:upgrade|upscaled?|remaster(?:ed)?))?",
    re.IGNORECASE,
)
_BRACKET_SUFFIX = re.compile(r"\s*(?:\(([^()]*)\)|\[([^\[\]]*)\])\s*$")
_PLAIN_SUFFIX = re.compile(
    r"\s+(?:[-–—|]\s*)?(?:official\s+(?:music\s+video|video|audio|lyric\s+video)"
    r"|lyric\s+video)\s*$",
    re.IGNORECASE,
)
_VIDEO_CONTEXT_SUFFIX = re.compile(
    r"\s*\((?:(?:official\s+)?(?:music|lyric)\s+video|official\s+video)\b.*\)\s*$",
    re.IGNORECASE,
)
_TITLE_SEPARATOR = re.compile(r"\s+[-–—|]\s+")
_CHANNEL_SUFFIX = re.compile(r"\s*[-–—]\s*topic\s*$", re.IGNORECASE)


def clean_audio_title(title: str) -> str:
    """Remove cosmetic video suffixes, preserving live/mix/version descriptions."""
    cleaned = title.strip()
    while cleaned:
        without_video_context = _VIDEO_CONTEXT_SUFFIX.sub("", cleaned).rstrip()
        if without_video_context != cleaned:
            cleaned = without_video_context
            continue
        match = _BRACKET_SUFFIX.search(cleaned)
        if match and _COSMETIC_LABEL.fullmatch((match[1] or match[2] or "").strip()):
            cleaned = cleaned[: match.start()].rstrip()
            continue
        without_plain_suffix = _PLAIN_SUFFIX.sub("", cleaned).rstrip()
        if without_plain_suffix == cleaned:
            break
        cleaned = without_plain_suffix
    return cleaned or title.strip() or "audio"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _artist_name(value: Any) -> str:
    artist = _text(value)
    return _CHANNEL_SUFFIX.sub("", clean_audio_title(artist)).strip() if artist else ""


def _artist_credit(info: dict[str, Any], plural: str, singular: str) -> str:
    values = info.get(plural)
    if isinstance(values, list):
        artists = list(
            dict.fromkeys(_artist_name(value) for value in values if _artist_name(value))
        )
        if artists:
            return " & ".join(artists)
    return _artist_name(info.get(singular))


def audio_file_title(info: dict[str, Any]) -> str:
    """Build an ``Artist - Track`` title from metadata and common video titles."""
    raw_title = _text(info.get("title")) or _text(info.get("id")) or "audio"
    track = clean_audio_title(_text(info.get("track"))) if _text(info.get("track")) else ""

    metadata_artist = _artist_credit(info, "artists", "artist") or _artist_credit(
        info, "creators", "creator"
    )
    if metadata_artist and track:
        return f"{metadata_artist} - {track}"

    # Uploader/channel is less authoritative than the artist field. Use it only
    # when the visible title itself confirms which side contains the artist.
    artist_candidates = [
        candidate
        for candidate in (
            metadata_artist,
            _artist_name(info.get("uploader")),
            _artist_name(info.get("channel")),
        )
        if candidate
    ]
    parts = _TITLE_SEPARATOR.split(raw_title)
    if len(parts) >= 2:
        # Some non-artist channels omit structured music metadata but include
        # the artist as a tag. Accept a tag only when it exactly matches one
        # side of the visible title; unrelated genre/topic tags are ignored.
        title_sides = {clean_audio_title(part).casefold() for part in parts}
        tags = info.get("tags")
        if isinstance(tags, list):
            artist_candidates.extend(
                tag
                for value in tags
                if (tag := _artist_name(value)) and tag.casefold() in title_sides
            )

        for artist in dict.fromkeys(artist_candidates):
            if clean_audio_title(parts[0]).casefold() == artist.casefold():
                song = clean_audio_title(" - ".join(parts[1:]))
                return f"{artist} - {song}"
            if clean_audio_title(parts[-1]).casefold() == artist.casefold():
                song = clean_audio_title(" - ".join(parts[:-1]))
                return f"{artist} - {song}"

        # Some uploads contain no artist metadata. A cosmetic marker identifies
        # the song side without guessing from the separator alone.
        if len(parts) == 2:
            left, right = (part.strip() for part in parts)
            clean_left = clean_audio_title(left)
            clean_right = clean_audio_title(right)
            if clean_left != left and clean_right == right:
                return f"{clean_right} - {clean_left}"

    if metadata_artist:
        return f"{metadata_artist} - {clean_audio_title(raw_title)}"
    return clean_audio_title(raw_title)


class _CaptureAudioPP(PostProcessor):
    """Record yt-dlp's actual final file after conversion and file moves."""

    def __init__(self) -> None:
        super().__init__()
        self.result: dict[str, Any] | None = None

    def run(self, information: dict[str, Any]):
        self.result = information.copy()
        return [], information


def _publish_mp3(source: Path, directory: Path, title: str) -> Path:
    # Keep room for collision suffixes and the extension on common filesystems.
    stem = sanitize_filename(clean_audio_title(title), restricted=False).strip()
    stem = stem.encode("utf-8")[:200].decode("utf-8", errors="ignore")
    if stem in {"", ".", ".."}:
        stem = "audio"
    index = 1
    while True:
        suffix = "" if index == 1 else f" ({index})"
        destination = directory / f"{stem}{suffix}.mp3"
        try:
            # Staging is on the same filesystem. link() publishes exclusively,
            # without a check/rename race that could overwrite another song.
            os.link(source, destination)
            return destination
        except FileExistsError:
            index += 1


def _normalize_mp3(path: Path, executable: str) -> None:
    try:
        subprocess.run(
            [executable, "-r", "-d", "10.5", "-f", str(path)],
            check=True,
            shell=False,
            # Confirm MP3Gain's clipping question for the user's requested
            # +10.5 dB target. EOF alone exits successfully without applying it.
            input="y\n",
            capture_output=True,
            text=True,
            errors="replace",
            **hidden_subprocess_options(),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        details = (
            (error.stderr or error.stdout or str(error)).strip()[-2000:]
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        raise RuntimeError(
            f"mp3gain could not normalize the audio: {details}. "
            f"The downloaded MP3 is preserved at: {path}"
        ) from error


def download_audio(
    url: str,
    download_dir: str,
    concurrent_fragment_downloads: int = DEFAULT_CONCURRENT_DOWNLOADS,
    proxy: str | None = None,
    use_aria2c: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Download the best audio, convert to MP3 V0, then apply track gain +10.5 dB."""
    options = _download_options(
        "bestaudio",
        download_dir,
        concurrent_fragment_downloads,
        proxy,
        use_aria2c,
        progress_callback,
    )
    ffmpeg = require_executable("ffmpeg")
    require_executable("ffprobe")
    mp3gain = require_executable("mp3gain")
    directory = Path(download_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".audio-", dir=directory))
    options.pop("merge_output_format", None)
    options.pop("remuxvideo", None)
    options.update(
        {
            "format": "bestaudio",
            "outtmpl": str(staging / "source.%(ext)s"),
            "ffmpeg_location": str(Path(ffmpeg).parent),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                }
            ],
        }
    )
    capture = _CaptureAudioPP()
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.add_post_processor(capture, when="after_move")
            exit_code = ydl.download([url])
        if exit_code:
            raise RuntimeError(f"yt-dlp failed with exit code {exit_code}")
        if progress_callback:
            progress_callback({"status": "processing", "stage": "finalizing"})
        info = capture.result
        if not info or not isinstance(info.get("filepath"), str):
            raise RuntimeError("yt-dlp did not report a completed MP3 file")
        source = Path(info["filepath"]).resolve()
        if (
            not source.is_relative_to(staging.resolve())
            or source.suffix.lower() != ".mp3"
            or not source.is_file()
            or source.stat().st_size == 0
        ):
            raise RuntimeError("yt-dlp did not produce a valid MP3 file in its download directory")
        title = audio_file_title(info)
        raw_title = clean_audio_title(_text(info.get("title")) or _text(info.get("id")) or "audio")
        if title == raw_title:
            matched_credit = lookup_track_credit(
                raw_title, info.get("duration"), info.get("tags")
            )
            if matched_credit:
                artist, track = matched_credit
                title = f"{artist} - {track}"
        destination = _publish_mp3(source, directory, title)
    except Exception as error:
        if any(staging.iterdir()):
            raise RuntimeError(
                f"{error}. Partial audio files are preserved at: {staging}"
            ) from error
        staging.rmdir()
        raise
    shutil.rmtree(staging)
    if progress_callback:
        progress_callback({"status": "processing", "stage": "normalizing_audio"})
    _normalize_mp3(destination, mp3gain)
    return destination

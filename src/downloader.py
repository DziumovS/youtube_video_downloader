from typing import Any, Dict, List, Optional
import yt_dlp
from .models import VideoFormat


def format_size(size: Optional[int]) -> str:
    if not size or size <= 0:
        return "unknown"

    average_statistical_error: float = 0.03  # 3%
    pure_mb: float = size / (1024 * 1024)
    mb: float = pure_mb * (1 + average_statistical_error)

    return f"~{mb:.0f}mb"


def get_formats(url: str, proxy: Optional[str] = None) -> List[VideoFormat]:
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "skip_download": True,
        "proxy": proxy
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info: Dict[str, Any] = ydl.extract_info(url, download=False)

    formats: List[Dict[str, Any]] = info.get("formats", [])
    best_audio_size: int = 0
    unique_videos: Dict[int, VideoFormat] = {}

    for f in formats:
        acodec = f.get("acodec")
        vcodec = f.get("vcodec")
        filesize = f.get("filesize") or f.get("filesize_approx") or 0
        height = f.get("height")

        if acodec != "none" and vcodec == "none":
            best_audio_size = max(best_audio_size, filesize)
        elif vcodec != "none" and height:
            total_size = filesize + best_audio_size
            if height not in unique_videos or total_size > unique_videos[height]["size"]:
                unique_videos[height] = {
                    "id": str(f["format_id"]),
                    "height": int(height),
                    "size": total_size
                }

    return sorted(unique_videos.values(), key=lambda x: x["height"])


def download(
    url: str,
    format_id: str,
    download_dir: str,
    concurrent_fragment_downloads: int = 1,
    proxy: Optional[str] = None
) -> None:
    ydl_opts: Dict[str, Any] = {
        "format": f"{format_id}+bestaudio/best",
        "outtmpl": f"{download_dir}/%(title)s.%(ext)s",

        "merge_output_format": "mkv",

        "concurrent_fragment_downloads": concurrent_fragment_downloads,

        "writesubtitles": False,

        "keepvideo": False,
        "ignoreerrors": True,

        "http_headers": {"User-Agent": "Mozilla/5.0"},
        "proxy": proxy,
        "noplaylist": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

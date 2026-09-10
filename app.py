import os
from typing import Optional

from yt_dlp.utils import DownloadError

from src.audio import download_audio
from src.models import VideoFormat
from src.downloader import (
    DEFAULT_CONCURRENT_DOWNLOADS,
    download,
    format_size,
    get_formats,
)


DOWNLOAD_DIR: str = os.path.join(os.path.dirname(__file__), "downloads")
PROXY: Optional[str] = None
CONCURRENT_FRAGMENT_DOWNLOADS: int = DEFAULT_CONCURRENT_DOWNLOADS
USE_ARIA2C: bool = False


def _run() -> int:
    url: str = input("Paste the link to the YouTube video: ").strip()

    if not url:
        print("URL cannot be empty.")
        return 2

    mode = input("Download video [v] or audio only as MP3 [a]? [v]: ").strip().lower()
    if mode not in ("", "v", "a"):
        print("Invalid download mode: enter v or a.")
        return 2

    print(
        f"Parallel fragments: up to {CONCURRENT_FRAGMENT_DOWNLOADS} workers "
        "(one combined progress bar)."
    )
    if mode == "a":
        print("Downloading the best audio, converting to MP3 and applying MP3Gain...")
        path = download_audio(
            url=url,
            download_dir=DOWNLOAD_DIR,
            concurrent_fragment_downloads=CONCURRENT_FRAGMENT_DOWNLOADS,
            proxy=PROXY,
            use_aria2c=USE_ARIA2C,
        )
        print(f'\nDone! MP3 saved to "{path}".')
        return 0

    formats: list[VideoFormat] = get_formats(url, PROXY)

    if not formats:
        print("No available formats found.")
        return 1

    print("\nAvailable formats:")
    for i, f in enumerate(formats):
        size: str = format_size(f["size"])
        print(f"{i + 1}. {f['height']}p (mkv, {size})")

    try:
        choice = int(input("\nSelect a number: ")) - 1
    except ValueError:
        print("Invalid choice")
        return 2
    if choice < 0 or choice >= len(formats):
        print("Invalid choice")
        return 2

    selected: VideoFormat = formats[choice]
    print(f"\nDownloading {selected['height']}p...\n")

    download(
        url=url,
        format_id=selected["id"],
        download_dir=DOWNLOAD_DIR,
        concurrent_fragment_downloads=CONCURRENT_FRAGMENT_DOWNLOADS,
        proxy=PROXY,
        use_aria2c=USE_ARIA2C,
    )
    print(f"\nDone! The video is in the \"{DOWNLOAD_DIR}\" folder.")
    return 0


def main() -> int:
    try:
        return _run()
    except (DownloadError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

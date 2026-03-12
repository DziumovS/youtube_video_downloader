import os
from typing import List, Optional

from src.models import VideoFormat
from src.downloader import download, get_formats, format_size


DOWNLOAD_DIR: str = os.path.join(os.path.dirname(__file__), "downloads")
PROXY: Optional[str] = None
CONCURRENT_FRAGMENT_DOWNLOADS: int = 6


def main() -> None:
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    url: str = input("Paste the link to the YouTube video: ").strip()

    formats: List[VideoFormat] = get_formats(url, PROXY)

    if not formats:
        print("No available formats found.")
        return

    print("\nAvailable formats:")
    for i, f in enumerate(formats):
        size: str = format_size(f["size"])
        print(f"{i + 1}. {f['height']}p (mkv, {size})")

    choice: int = int(input("\nSelect a number: ")) - 1
    if choice < 0 or choice >= len(formats):
        print("Invalid choice")
        return

    selected: VideoFormat = formats[choice]
    print(f"\nDownloading {selected['height']}p...\n")

    download(
        url=url,
        format_id=selected["id"],
        download_dir=DOWNLOAD_DIR,
        concurrent_fragment_downloads=CONCURRENT_FRAGMENT_DOWNLOADS,
        proxy=PROXY
    )
    print(f"\nDone! The video is in the \"{DOWNLOAD_DIR}\" folder.")


if __name__ == "__main__":
    main()

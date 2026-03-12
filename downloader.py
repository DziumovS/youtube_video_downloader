import os
import yt_dlp


DOWNLOAD_DIR = "downloads"

PROXY = None
CONCURRENT_FRAGMENT_DOWNLOADS = 6


def format_size(size):
    if not size:
        return "unknown"

    average_statistical_error = 0.03  # 3%

    pure_mb = size / (1024 * 1024)
    mb = pure_mb + pure_mb * average_statistical_error

    return f"~{mb:.0f}mb"


def get_formats(url):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "proxy": PROXY
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = info["formats"]

    videos = []
    best_audio_size = 0

    for f in formats:
        if f.get("acodec") != "none" and f.get("vcodec") == "none":
            size = f.get("filesize") or f.get("filesize_approx") or 0
            if size > best_audio_size:
                best_audio_size = size

    for f in formats:
        if f.get("height") and f.get("vcodec") != "none":
            video_size = f.get("filesize") or f.get("filesize_approx") or 0
            total_size = video_size + best_audio_size
            videos.append({
                "id": f["format_id"],
                "height": f["height"],
                "size": total_size
            })

    unique = {}
    for v in videos:
        unique[v["height"]] = v

    videos = sorted(unique.values(), key=lambda x: x["height"])

    return videos


def download(url, format_id):
    ydl_opts = {
        "format": f"{format_id}+bestaudio/best",
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s.%(ext)s",

        "merge_output_format": "mkv",

        "concurrent_fragment_downloads": CONCURRENT_FRAGMENT_DOWNLOADS,

        "writesubtitles": True,
        "writeautomaticsub": False,
        "embedsubtitles": True,
        "convert_subtitles": "srt",

        "keepvideo": False,

        "ignoreerrors": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0"
        },

        "proxy": PROXY,
        "noplaylist": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def main():
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    url = input("Paste the link to the YouTube video: ")

    formats = get_formats(url)

    print("\nAvailable formats:")

    for i, f in enumerate(formats):
        size = format_size(f["size"])
        print(f"{i + 1}. {f['height']}p (mkv, {size})")

    choice = int(input("\nSelect a number: ")) - 1

    selected = formats[choice]

    print(f"\nDownloading {selected['height']}p...\n")

    download(url, selected["id"])

    print("\nDone! The video is in the \"downloads\" folder..")


if __name__ == "__main__":
    main()

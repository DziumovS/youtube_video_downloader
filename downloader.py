import os
import yt_dlp


DOWNLOAD_DIR = "downloads"

PROXY = None


def get_formats(url):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "proxy": PROXY
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = []

    for f in info["formats"]:
        if f.get("height") and f.get("vcodec") != "none":
            formats.append({
                "id": f["format_id"],
                "height": f["height"],
                "ext": f["ext"]
            })

    unique = {}
    for f in formats:
        unique[f["height"]] = f

    sorted_formats = sorted(unique.values(), key=lambda x: x["height"])

    return sorted_formats


def download_video(url, format_id):
    ydl_opts = {
        "format": f"{format_id}+bestaudio/best",
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s.%(ext)s",
        "noplaylist": True,
        "concurrent_fragment_downloads": 8,
        "proxy": PROXY,
        "merge_output_format": "mp4",
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
        print(f"{i + 1}. {f['height']}p ({f['ext']})")

    choice = int(input("\nSelect a number: ")) - 1

    selected = formats[choice]

    print(f"\nDownloading {selected['height']}p...\n")

    download_video(url, selected["id"])

    print("\nDone! The video is in the \"downloads\" folder..")


if __name__ == "__main__":
    main()

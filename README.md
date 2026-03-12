# 🎬 YouTube Video Downloader

A simple CLI application for downloading **YouTube videos in MKV
format** with the best available audio and embedded subtitles.

The program displays available video resolutions, estimates the final
file size, and downloads the selected format.

------------------------------------------------------------------------

# ✨ Features

-   📺 Download YouTube videos in multiple resolutions
-   🔊 Automatically merges **best audio + selected video**
-   📝 Downloads and **embeds subtitles** into the final video file
-   📦 Outputs a single **MKV file**
-   📊 Shows **approximate final file size** before downloading
-   ⚡ Parallel fragment downloads for faster downloading
-   🧠 Automatically selects the **best available audio stream**
-   🧩 Built on top of the powerful `yt-dlp`

------------------------------------------------------------------------

# 📷 Example

``` text
Paste the link to the YouTube video: https://www.youtube.com/watch?v=example

Available formats:
1. 144p (mkv, ~117mb)
2. 240p (mkv, ~129mb)
3. 360p (mkv, ~154mb)
4. 480p (mkv, ~186mb)
5. 720p (mkv, ~250mb)
6. 1080p (mkv, ~317mb)

Select a number: 6

Downloading 1080p...

Done! The video is in the "downloads" folder.
```

------------------------------------------------------------------------

# 🏗 Project Structure

    youtube_video_downloader/
    │
    ├── downloader.py
    ├── pyproject.toml
    ├── README.md
    └── downloads/

-   **downloader.py** --- main application script\
-   **downloads/** --- directory where downloaded videos are saved\
-   **pyproject.toml** --- project metadata and dependencies

------------------------------------------------------------------------

# ⚙️ Requirements

-   Python **3.14+**
-   `ffmpeg`
-   `uv`

`ffmpeg` is required for merging video/audio streams and embedding
subtitles.

------------------------------------------------------------------------

# 🚀 Installation

## 1. Install uv

If you don't have it:

``` bash
pip install uv
```

or (macOS):

``` bash
brew install uv
```

------------------------------------------------------------------------

## 2. Clone the repository

``` bash
git clone https://github.com/yourusername/youtube-video-downloader.git
cd youtube-video-downloader
```

------------------------------------------------------------------------

## 3. Install dependencies

``` bash
uv sync
```

This installs the required packages listed in **pyproject.toml**:

-   `yt-dlp`
-   `curl-cffi`

------------------------------------------------------------------------

# ▶️ Usage

Run the downloader:

``` bash
uv run downloader.py
```

Then:

1.  Paste the YouTube video URL
2.  Select the desired resolution
3.  Wait for the download to complete

Downloaded files will appear in:

    downloads/

------------------------------------------------------------------------

# 📦 Dependencies

## yt-dlp

Core engine used to extract and download media from YouTube.

Provides:

-   format extraction
-   DASH stream downloading
-   subtitle downloading
-   stream merging
-   metadata processing

Project:\
https://github.com/yt-dlp/yt-dlp

------------------------------------------------------------------------

## curl-cffi

Used by `yt-dlp` for improved networking and browser-like TLS
impersonation.

This helps reduce issues such as:

-   HTTP 429 (Too Many Requests)
-   YouTube rate limiting

------------------------------------------------------------------------

# 🧠 How It Works

The downloader performs the following steps.

------------------------------------------------------------------------

## 1. Extract video information

The program first retrieves metadata from YouTube without downloading
the video:

``` python
info = ydl.extract_info(url, download=False)
```

This returns information about all available formats.

------------------------------------------------------------------------

## 2. Detect best audio stream

The script finds the largest **audio-only stream**:

    acodec != none
    vcodec == none

This audio track will be merged with the selected video stream.

------------------------------------------------------------------------

## 3. Build available resolution list

Video formats are filtered by:

    vcodec != none
    height is present

Duplicate resolutions are removed so each resolution appears once.

------------------------------------------------------------------------

## 4. Estimate final file size

The estimated file size is calculated as:

    video_size + best_audio_size

A **3% statistical margin** is added to account for:

-   container overhead
-   subtitle streams
-   metadata

------------------------------------------------------------------------

## 5. Download and merge streams

YouTube provides video and audio as separate streams.

`yt-dlp` downloads them individually and merges them with **ffmpeg**:

    video stream
       +
    audio stream
       +
    subtitles
       ↓
    final MKV file

------------------------------------------------------------------------

## 6. Subtitle handling

The downloader:

-   downloads available subtitles
-   converts them to `.srt`
-   embeds them into the final MKV container

This allows switching subtitles inside the video player.

------------------------------------------------------------------------

# 📂 Output Format

All videos are saved as:

    MKV (Matroska)

This container supports:

-   multiple audio tracks
-   multiple subtitle tracks
-   high compatibility with modern media players

Recommended players:

-   VLC
-   MPV
-   IINA
-   MPC-HC

------------------------------------------------------------------------

# ⚡ Performance

The downloader uses parallel fragment downloads:

    concurrent_fragment_downloads

This allows faster downloads when YouTube serves segmented streams.

------------------------------------------------------------------------

# 🔧 Configuration

Inside `downloader.py` you can adjust several parameters.

### Proxy

``` python
PROXY = None
```

Example:

``` python
PROXY = "http://127.0.0.1:8080"
```

------------------------------------------------------------------------

### Download directory

``` python
DOWNLOAD_DIR = "downloads"
```

------------------------------------------------------------------------

### Download concurrency

``` python
CONCURRENT_FRAGMENT_DOWNLOADS = 6
```

------------------------------------------------------------------------

# ⚠️ Notes

-   Displayed file size is **approximate** (±3-5%)
-   Some videos may not provide subtitles
-   YouTube may occasionally rate-limit requests

------------------------------------------------------------------------

# 📜 License

MIT License

------------------------------------------------------------------------

# 🙌 Acknowledgements

-   https://github.com/yt-dlp/yt-dlp
-   https://github.com/astral-sh/uv
-   YouTube DASH streaming system

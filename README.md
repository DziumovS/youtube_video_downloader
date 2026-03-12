# 🎬 YouTube Video Downloader

A simple CLI application for downloading **YouTube videos in MKV format** with the **best available audio**.

The program displays available video resolutions, estimates the final file size, and downloads the selected format.

------------------------------------------------------------------------

# ✨ Features

- 📺 Download YouTube videos in multiple resolutions
- 🔊 Automatically merges **best audio + selected video**
- 📦 Outputs a single **MKV file**
- 📊 Shows **approximate final file size** before downloading
- ⚡ Parallel fragment downloads for faster downloading
- 🧠 Automatically selects the **best available audio stream**
- 🧩 Built on top of the powerful `yt-dlp`

------------------------------------------------------------------------

# 📷 Example

```text
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

```
youtube_video_downloader/
│
├── downloads/             # Directory where downloaded videos are saved
├── src/
│   ├── __init__.py        # Exports main downloader functions and models
│   ├── downloader.py      # Core logic for format extraction and downloading
│   └── models.py          # TypedDict for video formats
├── tests/                 # Unit and E2E tests
├── app.py                 # CLI entry point
├── pyproject.toml         # Project metadata and dependencies
├── pytest.ini             # Pytest configuration
└── README.md              # README
```

------------------------------------------------------------------------

# ⚙️ Requirements

- Python **3.14+**
- `ffmpeg` (for merging video/audio streams)
- `uv` (CLI tool to run the app)

------------------------------------------------------------------------

# 🚀 Installation

## 1. Install uv

```bash
pip install uv
```

or (macOS):

```bash
brew install uv
```

------------------------------------------------------------------------

## 2. Clone the repository

```bash
git clone https://github.com/yourusername/youtube-video-downloader.git
cd youtube-video-downloader
```

------------------------------------------------------------------------

## 3. Install dependencies

```bash
uv sync
```

This installs the required packages listed in **pyproject.toml**:

- `yt-dlp`
- `curl-cffi`

------------------------------------------------------------------------

# ▶️ Usage

Run the downloader:

```bash
uv run app.py
```

Then:

1. Paste the YouTube video URL
2. Select the desired resolution
3. Wait for the download to complete

Downloaded files will appear in:

```
downloads/
```

------------------------------------------------------------------------

# 📦 Dependencies

## yt-dlp

- Core engine used to extract and download media from YouTube
- Provides format extraction, DASH stream downloading, stream merging, metadata processing
- Project: https://github.com/yt-dlp/yt-dlp

## curl-cffi

- Used by `yt-dlp` for improved networking and TLS impersonation
- Reduces issues like HTTP 429 and YouTube rate limiting

------------------------------------------------------------------------

# 🧠 How It Works

1. **Extract video information**

   Retrieves all formats without downloading:

   ```python
   info = ydl.extract_info(url, download=False)
   ```

2. **Detect best audio stream**

   The script finds the largest audio-only stream:

   ```python
   acodec != none
   vcodec == none
   ```

   This audio track will be merged with the selected video stream.

3. **Build available resolution list**

   Video formats are filtered by:

   ```python
   vcodec != none
   height is present
   ```

   Only unique heights are kept. Best audio is automatically paired.

4. **Estimate final file size**

   Final size = video size + best audio size + 3% statistical margin

5. **Download and merge streams**

   `yt-dlp` downloads video and audio separately, merges them into MKV:

   ```text
   video stream + audio stream → final MKV file
   ```

6. **Subtitles**

   Subtitles are **not downloaded** in this version.

------------------------------------------------------------------------

# 📂 Output Format

- All videos are saved as **MKV (Matroska)**
- Recommended players:
  - VLC
  - MPV
  - IINA
  - MPC-HC

------------------------------------------------------------------------

# ⚡ Performance

- Parallel fragment downloads configurable via `CONCURRENT_FRAGMENT_DOWNLOADS`
- Ensures faster downloads when YouTube serves segmented streams

------------------------------------------------------------------------

# 🔧 Configuration

### Proxy

```python
PROXY = None
```

Example:

```python
PROXY = "http://127.0.0.1:8080"
```

### Download directory

```python
DOWNLOAD_DIR = "downloads"
```

### Download concurrency

```python
CONCURRENT_FRAGMENT_DOWNLOADS = 6
```

------------------------------------------------------------------------

# ⚠️ Notes

- Displayed file size is **approximate** (±3%)
- Subtitles are no longer downloaded
- YouTube may occasionally rate-limit requests

------------------------------------------------------------------------

# 📜 License

MIT License

------------------------------------------------------------------------

# 🙌 Acknowledgements

- https://github.com/yt-dlp/yt-dlp
- https://github.com/astral-sh/uv

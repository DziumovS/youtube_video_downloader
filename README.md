# 🎬 YouTube Video Downloader

A CLI and responsive web application for downloading **YouTube videos in MKV
format** or **audio-only MP3 files** with automatic MP3Gain processing.

The program displays available video resolutions, estimates the final file size, and downloads the selected format.

------------------------------------------------------------------------

# ✨ Features

- 📺 Download YouTube videos in multiple resolutions
- 🔊 Automatically merges **best audio + selected video**
- 📦 Outputs a single **MKV file**
- 🎵 Audio-only MP3: best available source audio → LAME VBR quality 0 → MP3Gain
- 📝 Cleans promotional title suffixes and preserves existing songs
- 📊 Shows **approximate final file size** before downloading
- ⚡ Conservative parallel fragment downloads with retry/resume support
- 🚀 Optional multi-connection downloads through `aria2c`
- 🧠 Automatically selects the **best available audio stream**
- 🧩 Built on top of the powerful `yt-dlp`
- 🌐 Responsive web interface suitable for desktop and mobile browsers
- 🔒 Strict YouTube/YouTube Music URL and per-request format validation

------------------------------------------------------------------------

# 📷 Example

```text
Paste the link to the YouTube video: https://www.youtube.com/watch?v=example
Download video [v] or audio only as MP3 [a]? [v]: v
Parallel fragments: up to 4 workers (one combined progress bar).

Available formats:
1. 144p (mkv, ~117 MB)
2. 240p (mkv, ~129 MB)
3. 360p (mkv, ~154 MB)
4. 480p (mkv, ~186 MB)
5. 720p (mkv, ~250 MB)
6. 1080p (mkv, ~317 MB)

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
│   ├── audio.py           # MP3 conversion, title cleanup and MP3Gain
│   ├── runtime.py         # Runtime/executable discovery for terminal and IDE
│   ├── video.py           # Isolated video download and exact final file capture
│   ├── web.py             # Web API, validation and background job coordinator
│   ├── static/            # Responsive CSS and browser-side workflow
│   ├── templates/         # Web page
│   └── models.py          # TypedDict for video formats
├── tests/                 # Unit and E2E tests
├── app.py                 # CLI entry point
├── web_app.py             # Waitress web-server entry point
├── pyproject.toml         # Project metadata and dependencies
├── pytest.ini             # Pytest configuration
└── README.md              # README
```

------------------------------------------------------------------------

# ⚙️ Requirements

- Python **3.14+**
- Node.js **22+** or Deno **2.3+** (used for YouTube's JavaScript challenges;
  installations from NVM, Homebrew, and the process `PATH` are detected)
- `ffmpeg` (for merging video/audio streams)
- `ffprobe` (normally included with ffmpeg)
- `mp3gain` (required for MP3 downloads)
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
- `yt-dlp-ejs` and yt-dlp's default dependencies (challenge solver scripts)
- `curl-cffi`
- `Flask` and `Waitress` for the web interface

------------------------------------------------------------------------

# ▶️ Usage

## Web interface

Start the local web server:

```bash
uv run web_app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The page works on desktop
and mobile browsers. It validates the URL, offers video or audio mode, displays
the available video resolutions, prepares the final file on the server, and
then starts a normal browser download.

Each browser receives an anonymous, signed user ID. Its finished files remain
on the server under:

```text
downloads/users/<user-id>/
```

The ID stays in an HTTP-only session cookie and cannot be replaced with another
folder name. The signing key is generated once in `downloads/.web-secret`, so
the same browser keeps its user ID after a server restart.

Finished media is also indexed by a filesystem cache under
`downloads/.web-cache/`. The key includes the YouTube video ID, media mode and
selected video format. Repeating the same request skips the media download and
does not run FFmpeg/MP3Gain again. Format inspection can still make a small
YouTube metadata request. The cache and user file are hard links to the same
data on disk, so caching does not duplicate the media bytes. Different video
resolutions and audio mode use separate cache entries.

Web downloads are retained for seven days. Their combined physical storage is
limited to 50 decimal GB; hard-linked paths are counted once, and the oldest
media is removed first when the limit is exceeded. Cleanup runs when the server
starts and around download jobs. Active files are protected during cleanup.
Files downloaded through the CLI directly into `downloads/` are outside this
policy.

At most two files are processed at once, with a bounded queue of eight jobs.
Each video format is checked against the formats returned for that exact
inspected link. Large files are streamed by the browser download endpoint and
are not buffered in JavaScript memory. While yt-dlp downloads a media stream,
the page shows its live percentage and transferred byte count. FFmpeg merging,
MP3 conversion, MP3Gain, cache lookup, and finalization are shown as named stages
because those tools do not expose a reliable completion percentage.

To publish the page temporarily through ngrok, leave the server running and use
a second terminal:

```bash
ngrok http 8000
```

Open or share the HTTPS forwarding URL printed by ngrok. The server itself stays
bound to `127.0.0.1`; ngrok forwards traffic to it. You can select another port:

```bash
WEB_PORT=9000 uv run web_app.py
ngrok http 9000
```

The ngrok URL is public: anyone who has it can consume your bandwidth, disk
space and YouTube request quota. Share it only with people you trust and stop
ngrok when finished. For an extra password layer, use ngrok's access-control
features.

## CLI

Run the downloader:

```bash
uv run app.py
```

Then:

1. Paste the YouTube video URL
2. Choose `v` (or Enter) for video, or `a` for MP3
3. For video, select the desired resolution
4. Wait for downloading and postprocessing to complete

Downloaded files will appear in:

```
downloads/
```

### MP3 audio

Audio mode selects `bestaudio`, downloads no video, and converts the original
audio to MP3 using FFmpeg/LAME at VBR quality 0. YouTube does not provide MP3;
conversion is lossy and cannot improve the original source quality.

The application then runs the equivalent of:

```bash
mp3gain -r -d 10.5 -f "/path/to/the/newly-downloaded-song.mp3"
```

This runs as a child process without opening a terminal window. The app waits
until MP3Gain finishes before reporting success. Only the new file is processed,
never other songs in the folder. If MP3Gain fails, the MP3 is retained and the
error reports its location. The requested `-d 10.5` and `-f` settings are used
exactly. MP3Gain's clipping confirmation receives `y` through stdin so processing
finishes unattended at the requested level. Loud material can clip at this target;
`-f` controls MPEG layer detection and does not suppress that confirmation.

The filename is normalized to `Artist - Track.mp3` using YouTube's artist/track
metadata and common title layouts. Promotional suffixes such as `(Official Video)`,
`[HD]`, and `[HD UPGRADE]` are removed. Meaningful version descriptions, such as
`(Live)` and `(Remix)`, remain. For example,
`Gorillaz - Feel Good Inc. (Official Video).mp3` becomes
`Gorillaz - Feel Good Inc..mp3`. Existing songs are not overwritten; a numeric
suffix is added when the cleaned filename is already taken.

Titles published as `Track (Official Music Video) [HD UPGRADE] – Artist` are
reordered, so `Breaking the Habit … – Linkin Park` becomes
`Linkin Park - Breaking the Habit.mp3`.

Nested promotional suffixes such as `(Lyric Video from The Witcher (Music from
the Netflix Original Series))` are also removed.

For uploads on compilation or studio channels that omit structured artist data,
an exact tag matching one side of the title is used to identify the artist. Thus
`Heaven and Hell - Jeremy Blake` with the tag `Jeremy Blake` becomes
`Jeremy Blake - Heaven and Hell.mp3`; unrelated genre tags are ignored.

If YouTube supplies no artist at all, the app makes one conservative lookup in
the iTunes music catalog. It accepts a result only when the cleaned track name,
duration, and available artist tags agree. Album artists remain first and extra
track artists use `ft.`, for example:

```text
Sonya Belousova & Giona Ostinelli ft. Joey Batey - Toss a Coin to Your Witcher.mp3
```

If the catalog is unavailable or the result is ambiguous, downloading still
succeeds and the cleaned YouTube title is used without guessing an artist.

### IDE startup / JavaScript warning

The warning about "No supported JavaScript runtime" can also mean missing
**EJS solver scripts**, even if Node is installed. Install project dependencies
into the interpreter used by the IDE:

```bash
uv sync
```

Use this project's `.venv/bin/python3.14` in the IDE. The app searches PATH,
Homebrew and NVM locations, checks runtime compatibility and supplies its
absolute path to yt-dlp. See the [official EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

------------------------------------------------------------------------

# 📦 Dependencies

## yt-dlp

- Core engine used to extract and download media from YouTube
- Provides format extraction, DASH stream downloading, stream merging, metadata processing
- Project: https://github.com/yt-dlp/yt-dlp

## curl-cffi

- Used by `yt-dlp` for improved networking and TLS impersonation
- Provides networking/TLS impersonation support; it does not remove rate limits

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

   The largest audio size is used for an approximate display only. Actual audio
   selection is delegated to yt-dlp's `bestaudio` quality ordering.

3. **Build available resolution list**

   Video formats are filtered by:

   ```python
   vcodec != none
   height is present
   ```

   Only unique heights are kept. Best audio is automatically paired.

4. **Estimate final file size**

   The display estimate combines the selected video and best-audio byte counts.
   For YouTube HLS streams, the app also reads an encoded content length from
   the media URL when yt-dlp leaves `filesize` empty. Only when neither value is
   available does it fall back to stream bitrate × duration, which can still be
   less accurate for variable-bitrate media.

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
- HLS/DASH fragments use up to 4 workers by default; the terminal shows their
  combined progress in one line. The video and audio tracks download sequentially.
- Retries use increasing delays. Missing fragments fail the download instead of
  silently leaving holes in the video; partial video downloads can be resumed.
- A local HTTP test checks actual overlapping requests and exact fragment order.

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
CONCURRENT_FRAGMENT_DOWNLOADS = 4
```

The built-in setting downloads segmented streams concurrently. The application
accepts integer values from 1 to 16; 4 is the default. More connections may
increase rate limiting and are not guaranteed to improve throughput.

For parallel range requests on regular HTTP streams, install `aria2c` and enable:

```python
USE_ARIA2C = True
```

The same concurrency value controls the number of aria2 connections. Keep it at
4 first; increasing it should be tested on your network and IP address. This
mode applies to regular HTTP streams; HLS/DASH fragments keep the native pool.
See [yt-dlp download options](https://github.com/yt-dlp/yt-dlp#download-options).

### Tests

Run deterministic unit, CLI and local HTTP tests with coverage enforcement:

```bash
uv run pytest
```

Run the real YouTube download smoke-test explicitly:

```bash
RUN_YOUTUBE_INTEGRATION=1 uv run pytest
```

------------------------------------------------------------------------

# ⚠️ Notes

- Displayed file size is **approximate**, especially for HLS streams
- Subtitles are no longer downloaded
- YouTube may occasionally rate-limit requests

------------------------------------------------------------------------

# 📜 License

MIT License

------------------------------------------------------------------------

# 🙌 Acknowledgements

- https://github.com/yt-dlp/yt-dlp
- https://github.com/astral-sh/uv

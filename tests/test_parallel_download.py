"""Exercise yt-dlp's actual fragment workers against a controlled HTTP server."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
import time

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.downloader.hls import HlsFD

from src.downloader import _download_options


@contextmanager
def fragment_server(*, fail_fragment=False):
    lock = Lock()
    state = {"active": 0, "peak": 0, "requests": 0}
    chunks = [f"fragment-{i}".encode() * 100 for i in range(8)]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == "/playlist.m3u8":
                manifest = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n"
                manifest += "".join(f"#EXTINF:1.0,\n/fragment-{i}.ts\n" for i in range(8))
                body = (manifest + "#EXT-X-ENDLIST\n").encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            with lock:
                state["requests"] += 1
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                # Simulated network latency makes overlapping requests observable.
                time.sleep(0.04)
                index = int(self.path.removeprefix("/fragment-").removesuffix(".ts"))
                if fail_fragment and index == 3:
                    self.send_error(429)
                    return
                body = chunks[index]
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                with lock:
                    state["active"] -= 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/playlist.m3u8", state, b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("workers", [1, 4])
def test_native_hls_uses_requested_workers_and_preserves_fragment_order(tmp_path, workers):
    options = _download_options("test", str(tmp_path), workers, None, False)
    options.update(quiet=True, noprogress=True, proxy="", cachedir=False)
    with fragment_server() as (url, state, expected), YoutubeDL(options) as ydl:
        result = HlsFD(ydl, options).download(
            str(tmp_path / "video.ts"),
            {"url": url, "protocol": "m3u8_native", "ext": "ts", "http_headers": {}},
        )
    assert result[0] is True
    assert state["requests"] == 8
    assert state["peak"] == workers
    assert (tmp_path / "video.ts").read_bytes() == expected


def test_rate_limited_fragment_fails_instead_of_producing_incomplete_video(tmp_path, monkeypatch):
    from yt_dlp.utils import DownloadError
    from yt_dlp.networking.exceptions import HTTPError

    options = _download_options("test", str(tmp_path), 4, None, False)
    options.update(quiet=True, noprogress=True, proxy="", cachedir=False, retries=0, fragment_retries=0)
    with fragment_server(fail_fragment=True) as (url, _state, _expected), YoutubeDL(options) as ydl:
        failures = []
        urlopen = ydl.urlopen

        def open_and_track_failure(request):
            try:
                return urlopen(request)
            except HTTPError as error:
                failures.append(error)
                raise

        monkeypatch.setattr(ydl, "urlopen", open_and_track_failure)
        try:
            # A failed worker may close the output while another appends,
            # surfacing as ValueError. Neither may publish an incomplete video.
            with pytest.raises((DownloadError, ValueError)):
                HlsFD(ydl, options).download(
                    str(tmp_path / "video.ts"),
                    {"url": url, "protocol": "m3u8_native", "ext": "ts", "http_headers": {}},
                )
        finally:
            # The low-level HlsFD API leaves failed response bodies unread.
            # This harness owns the injected HTTP failures and closes them.
            for error in failures:
                error.close()
    assert not (tmp_path / "video.ts").exists()

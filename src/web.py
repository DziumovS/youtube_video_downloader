from __future__ import annotations

import hashlib
import math
import os
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit, urlunsplit

from flask import Flask, Response, jsonify, render_template, request, send_file, session

from .audio import download_audio
from .downloader import DEFAULT_CONCURRENT_DOWNLOADS, format_size, get_formats
from .models import VideoFormat
from .video import download_video


_FORMAT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_USER_ID = re.compile(r"^[a-f0-9]{32}$")
_YOUTUBE_PATHS = {"embed", "live", "shorts"}
_PUBLIC_DOWNLOAD_ERROR = (
    "Could not prepare the file. Check the link and try again."
)


class DownloadQueueFull(RuntimeError):
    pass


def validate_youtube_url(value: Any) -> str:
    """Return a normalized YouTube video URL or raise a user-facing error."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Paste a YouTube link.")
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid YouTube link.") from error
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
        or hostname
        not in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be",
        }
    ):
        raise ValueError("Only YouTube and YouTube Music links are supported.")

    path_parts = [part for part in parsed.path.split("/") if part]
    is_short = hostname in {"youtu.be", "www.youtu.be"} and bool(path_parts)
    is_watch = parsed.path.rstrip("/") == "/watch" and bool(
        parse_qs(parsed.query).get("v", [""])[0].strip()
    )
    is_named_path = (
        len(path_parts) >= 2
        and path_parts[0].lower() in _YOUTUBE_PATHS
        and bool(path_parts[1].strip())
    )
    if not (is_short or is_watch or is_named_path):
        raise ValueError("The link must point to a specific YouTube video.")
    return urlunsplit(parsed)


@dataclass(frozen=True)
class Inspection:
    url: str
    video_id: str
    user_id: str
    formats: tuple[VideoFormat, ...]


@dataclass
class DownloadJob:
    status: str
    directory: Path
    user_id: str = ""
    path: Path | None = None
    error: str | None = None
    stage: str | None = None
    percent: int | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None


class DownloadService:
    """Thread-safe in-memory coordinator for one local web server process."""

    def __init__(
        self,
        download_dir: str | Path,
        *,
        executor: Executor | None = None,
        formats_func: Callable[[str, str | None], list[VideoFormat]] = get_formats,
        video_func: Callable[..., Path] = download_video,
        audio_func: Callable[..., Path] = download_audio,
        proxy: str | None = None,
        concurrent_fragments: int = DEFAULT_CONCURRENT_DOWNLOADS,
        use_aria2c: bool = False,
        max_pending_jobs: int = 8,
        retention_seconds: float = 7 * 24 * 60 * 60,
        max_storage_bytes: int = 50_000_000_000,
        now_func: Callable[[], float] = time.time,
    ) -> None:
        self.download_dir = Path(download_dir).expanduser().resolve()
        self.users_dir = self.download_dir / "users"
        self.cache_dir = self.download_dir / ".web-cache"
        self.executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="youtube-download"
        )
        self.formats_func = formats_func
        self.video_func = video_func
        self.audio_func = audio_func
        self.proxy = proxy
        self.concurrent_fragments = concurrent_fragments
        self.use_aria2c = use_aria2c
        self.retention_seconds = retention_seconds
        self.max_storage_bytes = max_storage_bytes
        self.now_func = now_func
        self.slots = threading.BoundedSemaphore(max_pending_jobs)
        self.inspections: dict[str, Inspection] = {}
        self.jobs: dict[str, DownloadJob] = {}
        self.cache_locks: dict[str, threading.Lock] = {}
        self.lock = threading.Lock()
        self.cleanup_lock = threading.Lock()

    def inspect(self, raw_url: Any, user_id: str) -> str:
        url = validate_youtube_url(raw_url)
        formats = tuple(self.formats_func(url, self.proxy))
        token = uuid.uuid4().hex
        with self.lock:
            self.inspections[token] = Inspection(
                url=url,
                video_id=_youtube_video_id(url),
                user_id=user_id,
                formats=formats,
            )
        return token

    def formats(self, token: str, user_id: str) -> list[dict[str, Any]] | None:
        with self.lock:
            inspection = self.inspections.get(token)
        if inspection is None or inspection.user_id != user_id:
            return None
        return [
            {
                "id": item["id"],
                "height": item["height"],
                "size": item["size"],
                "size_label": format_size(item["size"]),
            }
            for item in inspection.formats
        ]

    def start(
        self, token: str, user_id: str, mode: str, format_id: Any = None
    ) -> str:
        self.cleanup()
        with self.lock:
            inspection = self.inspections.get(token)
        if inspection is None or inspection.user_id != user_id:
            raise LookupError("This link has expired. Paste it again.")
        if mode not in {"video", "audio"}:
            raise ValueError("Unknown download mode.")
        if mode == "video":
            if not isinstance(format_id, str) or not _FORMAT_ID.fullmatch(format_id):
                raise ValueError("Select a video format.")
            allowed = {item["id"] for item in inspection.formats}
            if format_id not in allowed:
                raise ValueError("The selected format is not available for this link.")

        job_id = uuid.uuid4().hex
        user_dir = self.users_dir / user_id
        cache_key = _cache_key(inspection.video_id, mode, format_id)
        if not self.slots.acquire(blocking=False):
            raise DownloadQueueFull("The server is busy. Try again in a moment.")
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # pragma: no cover - defensive filesystem failure
            self.slots.release()
            raise
        with self.lock:
            self.jobs[job_id] = DownloadJob(
                status="queued", directory=user_dir, user_id=user_id
            )
        try:
            self.executor.submit(
                self._execute,
                job_id,
                inspection.url,
                mode,
                format_id,
                cache_key,
            )
        except Exception:
            with self.lock:
                self.jobs.pop(job_id, None)
            self.slots.release()
            raise
        return job_id

    def _execute(
        self,
        job_id: str,
        url: str,
        mode: str,
        format_id: str | None,
        cache_key: str,
    ) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.stage = "checking_cache"
        expected_suffix = ".mkv" if mode == "video" else ".mp3"
        try:
            with self._lock_for_cache(cache_key):
                cached = self._cached_file(cache_key, expected_suffix)
                if cached:
                    with self.lock:
                        job.stage = "using_cache"
                    resolved = self._link_for_user(cached, job.directory)
                else:
                    kwargs = {
                        "url": url,
                        "download_dir": str(job.directory),
                        "concurrent_fragment_downloads": self.concurrent_fragments,
                        "proxy": self.proxy,
                        "use_aria2c": self.use_aria2c,
                        "progress_callback": self._progress_hook(job_id, mode),
                    }
                    if mode == "video":
                        path = self.video_func(format_id=format_id, **kwargs)
                    else:
                        path = self.audio_func(**kwargs)
                    resolved = Path(path).resolve()
                    if (
                        not resolved.is_relative_to(job.directory.resolve())
                        or resolved.suffix.lower() != expected_suffix
                        or not resolved.is_file()
                        or resolved.stat().st_size == 0
                    ):
                        raise RuntimeError("download function returned an invalid file")
                    self._store_cache(cache_key, resolved)
                with self.lock:
                    job.path = resolved
                self.cleanup(protected_paths=(resolved,))
        except Exception:
            with self.lock:
                job.status = "error"
                job.error = _PUBLIC_DOWNLOAD_ERROR
                job.stage = None
        else:
            with self.lock:
                job.status = "ready"
                job.path = resolved
                job.stage = "ready"
                job.percent = 100
        finally:
            self.slots.release()

    def _progress_hook(
        self, job_id: str, mode: str
    ) -> Callable[[dict[str, Any]], None]:
        def update(event: dict[str, Any]) -> None:
            custom_stage = event.get("stage")
            postprocessor = event.get("postprocessor")
            status = event.get("status")
            if isinstance(custom_stage, str):
                self._set_progress(job_id, stage=custom_stage)
                return
            if isinstance(postprocessor, str):
                name = postprocessor.casefold()
                stage = (
                    "converting_audio"
                    if "extractaudio" in name
                    else "merging_video"
                    if mode == "video" and ("merger" in name or "remuxer" in name)
                    else "finalizing"
                )
                self._set_progress(job_id, stage=stage)
                return
            if status not in {"downloading", "finished"}:
                return

            downloaded = _progress_number(event.get("downloaded_bytes"))
            total = _progress_number(event.get("total_bytes")) or _progress_number(
                event.get("total_bytes_estimate")
            )
            percent = None
            if downloaded is not None and total:
                percent = round(min(100, max(0, downloaded * 100 / total)))
            else:
                fragment = _progress_number(event.get("fragment_index"))
                fragments = _progress_number(event.get("fragment_count"))
                if fragment is not None and fragments:
                    percent = round(min(100, max(0, fragment * 100 / fragments)))

            info = event.get("info_dict")
            is_audio = isinstance(info, dict) and info.get("vcodec") == "none"
            stage = "downloading_audio" if is_audio or mode == "audio" else "downloading_video"
            self._set_progress(
                job_id,
                stage=stage,
                percent=percent,
                downloaded_bytes=int(downloaded) if downloaded is not None else None,
                total_bytes=int(total) if total is not None else None,
            )

        return update

    def _set_progress(
        self,
        job_id: str,
        *,
        stage: str,
        percent: int | None = None,
        downloaded_bytes: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return
            job.stage = stage
            job.percent = percent
            job.downloaded_bytes = downloaded_bytes
            job.total_bytes = total_bytes

    def cleanup(self, protected_paths: tuple[Path, ...] = ()) -> tuple[int, int]:
        """Remove expired web media and trim unique storage to its configured cap."""
        with self.cleanup_lock:
            protected = {
                _inode(path)
                for path in protected_paths
                if path.is_file()
            }
            with self.lock:
                active_paths = [
                    job.path
                    for job in self.jobs.values()
                    if job.status in {"queued", "running"} and job.path is not None
                ]
            protected.update(_inode(path) for path in active_paths if path.is_file())

            entries: dict[tuple[int, int], dict[str, Any]] = {}
            for path in self._managed_media_files():
                try:
                    stat = path.stat()
                except FileNotFoundError:  # pragma: no cover - concurrent deletion
                    continue
                key = (stat.st_dev, stat.st_ino)
                entry = entries.setdefault(
                    key,
                    {"paths": [], "size": stat.st_size, "mtime": stat.st_mtime},
                )
                entry["paths"].append(path)

            total = sum(entry["size"] for entry in entries.values())
            cutoff = self.now_func() - self.retention_seconds
            removed_count = 0
            removed_bytes = 0
            for key, entry in sorted(
                entries.items(), key=lambda item: item[1]["mtime"]
            ):
                expired = entry["mtime"] <= cutoff
                over_limit = total > self.max_storage_bytes
                if key in protected or not (expired or over_limit):
                    continue
                for path in entry["paths"]:
                    path.unlink(missing_ok=True)
                total -= entry["size"]
                removed_count += 1
                removed_bytes += entry["size"]

            self._remove_empty_managed_directories()
            return removed_count, removed_bytes

    def _managed_media_files(self):
        roots = (self.users_dir, self.cache_dir, self.download_dir / ".web-jobs")
        for root in roots:
            if not root.is_dir():
                continue
            for directory in root.iterdir():
                if not directory.is_dir():
                    continue
                for path in directory.iterdir():
                    if path.is_file() and path.suffix.lower() in {".mkv", ".mp3"}:
                        yield path

    def _remove_empty_managed_directories(self) -> None:
        roots = (self.users_dir, self.cache_dir, self.download_dir / ".web-jobs")
        for root in roots:
            if not root.is_dir():
                continue
            for directory in root.iterdir():
                if directory.is_dir():
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

    def _lock_for_cache(self, cache_key: str) -> threading.Lock:
        with self.lock:
            return self.cache_locks.setdefault(cache_key, threading.Lock())

    def _cached_file(self, cache_key: str, suffix: str) -> Path | None:
        directory = self.cache_dir / cache_key
        if not directory.is_dir():
            return None
        files = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == suffix and path.stat().st_size > 0
        ]
        return files[0] if len(files) == 1 else None

    def _store_cache(self, cache_key: str, source: Path) -> Path:
        directory = self.cache_dir / cache_key
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / source.name
        try:
            destination.hardlink_to(source)
        except FileExistsError:
            pass
        return destination

    @staticmethod
    def _link_for_user(source: Path, directory: Path) -> Path:
        index = 1
        while True:
            suffix = "" if index == 1 else f" ({index})"
            destination = directory / f"{source.stem}{suffix}{source.suffix}"
            try:
                destination.hardlink_to(source)
                os.utime(destination, None)
                return destination
            except FileExistsError:
                if destination.samefile(source):
                    os.utime(destination, None)
                    return destination
                index += 1

    def job(self, job_id: str, user_id: str) -> DownloadJob | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return replace(job) if job and job.user_id == user_id else None


def _youtube_video_id(url: str) -> str:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]
    if (parsed.hostname or "").lower().rstrip(".") in {"youtu.be", "www.youtu.be"}:
        return parts[0]
    if parsed.path.rstrip("/") == "/watch":
        return parse_qs(parsed.query)["v"][0]
    return parts[1]


def _cache_key(video_id: str, mode: str, format_id: Any) -> str:
    value = f"v1\0{video_id}\0{mode}\0{format_id or ''}"
    return hashlib.sha256(value.encode()).hexdigest()


def _progress_number(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return float(value)
    return None


def _inode(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def _persistent_secret(download_dir: str | Path) -> bytes:
    directory = Path(download_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".web-secret"
    if path.is_file():
        value = path.read_bytes()
        if value:
            return value
    value = secrets.token_bytes(32)
    path.write_bytes(value)
    path.chmod(0o600)
    return value


def _json_object() -> dict[str, Any] | None:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    project_root = Path(__file__).resolve().parent.parent
    app.config.from_mapping(
        DOWNLOAD_DIR=str(project_root / "downloads"),
        MAX_CONTENT_LENGTH=4096,
        PROXY=None,
        CONCURRENT_FRAGMENT_DOWNLOADS=DEFAULT_CONCURRENT_DOWNLOADS,
        USE_ARIA2C=False,
        EXECUTOR=None,
        MAX_PENDING_JOBS=8,
        RETENTION_DAYS=7,
        MAX_STORAGE_GB=50,
        CLEANUP_ON_START=True,
    )
    if config:
        app.config.update(config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _persistent_secret(app.config["DOWNLOAD_DIR"])
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    service = DownloadService(
        app.config["DOWNLOAD_DIR"],
        executor=app.config["EXECUTOR"],
        proxy=app.config["PROXY"],
        concurrent_fragments=app.config["CONCURRENT_FRAGMENT_DOWNLOADS"],
        use_aria2c=app.config["USE_ARIA2C"],
        max_pending_jobs=app.config["MAX_PENDING_JOBS"],
        retention_seconds=app.config["RETENTION_DAYS"] * 24 * 60 * 60,
        max_storage_bytes=int(app.config["MAX_STORAGE_GB"] * 1_000_000_000),
    )
    app.extensions["download_service"] = service
    if app.config["CLEANUP_ON_START"]:
        service.cleanup()

    def current_user_id() -> str:
        user_id = session.get("user_id")
        if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):
            user_id = uuid.uuid4().hex
            session["user_id"] = user_id
        return user_id

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response

    @app.errorhandler(413)
    def payload_too_large(_error: Exception):
        return jsonify(error="The request is too large."), 413

    @app.get("/")
    def index():
        current_user_id()
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/inspect")
    def inspect_url():
        payload = _json_object()
        if payload is None:
            return jsonify(error="A JSON request is required."), 400
        try:
            token = service.inspect(payload.get("url"), current_user_id())
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except Exception:
            app.logger.exception("YouTube inspection failed")
            return jsonify(error="Could not verify the YouTube link."), 502
        return jsonify(inspection_id=token)

    @app.get("/api/inspections/<token>/formats")
    def inspection_formats(token: str):
        formats = service.formats(token, current_user_id())
        if formats is None:
            return jsonify(error="This link has expired. Paste it again."), 404
        return jsonify(formats=formats)

    @app.post("/api/jobs")
    def create_job():
        payload = _json_object()
        if payload is None:
            return jsonify(error="A JSON request is required."), 400
        try:
            job_id = service.start(
                payload.get("inspection_id", ""),
                current_user_id(),
                payload.get("mode", ""),
                payload.get("format_id"),
            )
        except LookupError as error:
            return jsonify(error=str(error)), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except DownloadQueueFull as error:
            return jsonify(error=str(error)), 429
        except Exception:
            app.logger.exception("Could not enqueue download")
            return jsonify(error="Could not start the download."), 503
        return jsonify(job_id=job_id), 202

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id: str):
        job = service.job(job_id, current_user_id())
        if job is None:
            return jsonify(error="Download job not found."), 404
        result: dict[str, Any] = {"status": job.status}
        if job.stage:
            result["stage"] = job.stage
        if job.percent is not None:
            result["percent"] = job.percent
        if job.downloaded_bytes is not None:
            result["downloaded_bytes"] = job.downloaded_bytes
        if job.total_bytes is not None:
            result["total_bytes"] = job.total_bytes
        if job.error:
            result["error"] = job.error
        if job.status == "ready" and job.path:
            result.update(
                filename=job.path.name,
                file_url=f"/api/jobs/{job_id}/file",
            )
        return jsonify(result)

    @app.get("/api/jobs/<job_id>/file")
    def job_file(job_id: str):
        job = service.job(job_id, current_user_id())
        if job is None:
            return jsonify(error="Download job not found."), 404
        if job.status != "ready" or job.path is None:
            return jsonify(error="The file is not ready yet."), 409
        if not job.path.is_file():
            return jsonify(error="The file has expired and was removed."), 410
        os.utime(job.path, None)
        mimetype = (
            "audio/mpeg"
            if job.path.suffix.lower() == ".mp3"
            else "video/x-matroska"
        )
        return send_file(
            job.path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=job.path.name,
            conditional=True,
        )

    return app

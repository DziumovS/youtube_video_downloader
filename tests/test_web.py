import os
import re
from pathlib import Path
from unittest.mock import ANY, Mock

import pytest

import src.web as web_module
from src.web import (
    DownloadJob,
    _cache_key,
    _persistent_secret,
    _progress_number,
    _youtube_video_id,
    create_app,
    validate_youtube_url,
)


class InlineExecutor:
    def __init__(self, failure=None):
        self.failure = failure

    def submit(self, function, *args):
        if self.failure:
            raise self.failure
        function(*args)
        return object()


class HoldingExecutor:
    def submit(self, function, *args):
        self.pending = (function, args)
        return object()


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc&list=xyz",
        "https://www.youtube.com/watch?v=abc",
        "https://m.youtube.com/shorts/abc",
        "https://music.youtube.com/watch?v=abc&start_radio=1",
        "http://youtu.be/abc",
        "https://www.youtu.be/abc",
        "youtube.com/live/abc",
        "https://youtube.com/embed/abc",
    ],
)
def test_validate_youtube_url_accepts_video_links(url):
    assert validate_youtube_url(url).startswith(("http://", "https://"))


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (None, "Paste"),
        ("   ", "Paste"),
        ("https://youtube.com.evil.test/watch?v=abc", "Only YouTube"),
        ("https://youtube.com@evil.test/watch?v=abc", "Only YouTube"),
        ("ftp://youtube.com/watch?v=abc", "Only YouTube"),
        ("https://youtube.com:8443/watch?v=abc", "Only YouTube"),
        ("https://youtube.com/watch", "specific YouTube video"),
        ("https://youtu.be/", "specific YouTube video"),
        ("https://youtube.com/playlist?list=abc", "specific YouTube video"),
        ("https://youtube.com:bad/watch?v=abc", "Invalid YouTube"),
    ],
)
def test_validate_youtube_url_rejects_non_video_or_spoofed_links(url, message):
    with pytest.raises(ValueError, match=message):
        validate_youtube_url(url)


@pytest.fixture
def web_parts(tmp_path):
    formats = Mock(return_value=[{"id": "18", "height": 360, "size": 1024}])

    def make_file(**kwargs):
        suffix = ".mkv" if "format_id" in kwargs else ".mp3"
        name = "Video with spaces.mkv" if suffix == ".mkv" else "Artist - Song.mp3"
        path = Path(kwargs["download_dir"]) / name
        path.write_bytes(b"media data")
        return path

    video = Mock(side_effect=make_file)
    audio = Mock(side_effect=make_file)
    app = create_app(
        {
            "TESTING": True,
            "DOWNLOAD_DIR": str(tmp_path),
            "EXECUTOR": InlineExecutor(),
            "PROXY": "http://proxy",
            "CONCURRENT_FRAGMENT_DOWNLOADS": 3,
            "USE_ARIA2C": True,
        }
    )
    service = app.extensions["download_service"]
    service.formats_func = formats
    service.video_func = video
    service.audio_func = audio
    return app, app.test_client(), service, formats, video, audio


def inspect(client, url="https://music.youtube.com/watch?v=abc"):
    response = client.post("/api/inspect", json={"url": url})
    assert response.status_code == 200
    return response.json["inspection_id"]


def user_id(client):
    with client.session_transaction() as browser_session:
        return browser_session["user_id"]


def test_index_is_responsive_accessible_and_has_security_headers(web_parts):
    _app, client, *_ = web_parts
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
    assert 'placeholder="paste a YouTube link here"' in html
    assert 'id="light-toggle"' in html
    assert 'class="light-cone"' in html
    assert 'class="fixture-svg"' in html
    assert 'id="video-mode"' in html and 'id="audio-mode"' in html
    assert 'id="download-video"' in html and "disabled" in html
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "camera=()" in response.headers["Permissions-Policy"]


def test_application_and_readme_contain_no_cyrillic_text():
    project_root = Path(__file__).resolve().parent.parent
    paths = [
        project_root / "README.md",
        project_root / "app.py",
        project_root / "web_app.py",
        *(project_root / "src").rglob("*.py"),
        *(project_root / "src").rglob("*.html"),
        *(project_root / "src").rglob("*.js"),
        *(project_root / "src").rglob("*.css"),
    ]
    cyrillic = re.compile(r"[\u0400-\u04ff]")
    offenders = [
        str(path.relative_to(project_root))
        for path in paths
        if cyrillic.search(path.read_text())
    ]
    assert offenders == []


def test_frontend_scatters_particles_and_clears_download_notice():
    project_root = Path(__file__).resolve().parent.parent
    script = (project_root / "src/static/app.js").read_text()
    template = (project_root / "src/templates/index.html").read_text()
    styles = (project_root / "src/static/styles.css").read_text()
    assert "scatter(index, 17)" in script
    assert "scatter(index, 71)" in script
    assert "resetApp(true)" not in script
    assert "downloadNotice.hidden = false" not in script
    assert '<div id="download-notice"' in template
    assert "<span>Your download has started." in template
    assert ".notice { display: block;" in styles
    assert "jobProgressMessage(data)" in script
    assert "data.percent" in script
    assert "data.downloaded_bytes" in script
    assert "setTimeout(resolve, 500)" in script


def test_app_factory_has_production_defaults(tmp_path):
    download_dir = tmp_path / "downloads"
    app = create_app({"DOWNLOAD_DIR": str(download_dir)})
    assert app.config["DOWNLOAD_DIR"] == str(download_dir)
    assert app.extensions["download_service"].concurrent_fragments == 4
    assert app.config["RETENTION_DAYS"] == 7
    assert app.config["MAX_STORAGE_GB"] == 50


def test_app_factory_without_config_uses_project_download_directory(monkeypatch):
    monkeypatch.setattr(web_module, "_persistent_secret", lambda _path: b"x" * 32)
    monkeypatch.setattr(web_module.DownloadService, "cleanup", lambda _self: (0, 0))
    app = create_app()
    assert app.config["DOWNLOAD_DIR"].endswith("/downloads")


def test_anonymous_user_id_is_signed_in_session_and_persistent(web_parts):
    app, client, *_ = web_parts
    first = client.get("/")
    assigned = user_id(client)
    assert len(assigned) == 32
    assert first.headers["Set-Cookie"].startswith("session=")
    assert "HttpOnly" in first.headers["Set-Cookie"]
    assert "SameSite=Lax" in first.headers["Set-Cookie"]
    client.get("/")
    assert user_id(client) == assigned
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = "tampered"
    client.get("/")
    assert user_id(client) != "tampered"
    assert app.config["SECRET_KEY"] == (Path(app.config["DOWNLOAD_DIR"]) / ".web-secret").read_bytes()


def test_health_endpoint(web_parts):
    assert web_parts[1].get("/health").json == {"status": "ok"}


def test_inspect_and_list_cached_formats(web_parts):
    _app, client, _service, formats, *_ = web_parts
    token = inspect(client)
    formats.assert_called_once_with("https://music.youtube.com/watch?v=abc", "http://proxy")
    response = client.get(f"/api/inspections/{token}/formats")
    assert response.json == {
        "formats": [{"id": "18", "height": 360, "size": 1024, "size_label": "~0 MB"}]
    }
    formats.assert_called_once()


def test_inspect_rejects_non_json_and_invalid_url_without_extraction(web_parts):
    _app, client, _service, formats, *_ = web_parts
    assert client.post("/api/inspect", data="text").status_code == 400
    response = client.post("/api/inspect", json={"url": "https://evil.test/video"})
    assert response.status_code == 400
    assert "YouTube" in response.json["error"]
    formats.assert_not_called()


def test_inspect_hides_extractor_failure(web_parts):
    app, client, service, *_ = web_parts
    service.formats_func = Mock(side_effect=RuntimeError("secret /local/path"))
    app.logger.disabled = True
    response = client.post("/api/inspect", json={"url": "https://youtu.be/abc"})
    assert response.status_code == 502
    assert response.json == {"error": "Could not verify the YouTube link."}
    assert "/local/path" not in response.get_data(as_text=True)


def test_unknown_inspection_has_no_formats(web_parts):
    response = web_parts[1].get("/api/inspections/unknown/formats")
    assert response.status_code == 404


def test_video_job_downloads_selected_allowed_format_and_serves_file(web_parts):
    _app, client, service, _formats, video, audio = web_parts
    token = inspect(client)
    created = client.post(
        "/api/jobs",
        json={"inspection_id": token, "mode": "video", "format_id": "18"},
    )
    assert created.status_code == 202
    job_id = created.json["job_id"]
    status = client.get(f"/api/jobs/{job_id}")
    assert status.json["status"] == "ready"
    assert status.json["filename"] == "Video with spaces.mkv"
    assert status.json["file_url"] == f"/api/jobs/{job_id}/file"
    response = client.get(status.json["file_url"])
    assert response.status_code == 200
    assert response.data == b"media data"
    assert response.mimetype == "video/x-matroska"
    assert "attachment" in response.headers["Content-Disposition"]
    assert service.jobs[job_id].directory == service.users_dir / user_id(client)
    video.assert_called_once_with(
        url="https://music.youtube.com/watch?v=abc",
        format_id="18",
        download_dir=str(service.jobs[job_id].directory),
        concurrent_fragment_downloads=3,
        proxy="http://proxy",
        use_aria2c=True,
        progress_callback=ANY,
    )
    audio.assert_not_called()
    response.close()


def test_audio_job_serves_normalized_mp3(web_parts):
    _app, client, service, _formats, video, audio = web_parts
    token = inspect(client)
    created = client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    )
    job_id = created.json["job_id"]
    response = client.get(f"/api/jobs/{job_id}/file")
    assert response.data == b"media data"
    assert response.mimetype == "audio/mpeg"
    assert 'filename="Artist - Song.mp3"' in response.headers["Content-Disposition"]
    audio.assert_called_once_with(
        url="https://music.youtube.com/watch?v=abc",
        download_dir=str(service.jobs[job_id].directory),
        concurrent_fragment_downloads=3,
        proxy="http://proxy",
        use_aria2c=True,
        progress_callback=ANY,
    )
    video.assert_not_called()
    response.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"inspection_id": "missing", "mode": "audio"},
        {"inspection_id": "TOKEN", "mode": "other"},
        {"inspection_id": "TOKEN", "mode": "video"},
        {"inspection_id": "TOKEN", "mode": "video", "format_id": "../../etc"},
        {"inspection_id": "TOKEN", "mode": "video", "format_id": "999"},
    ],
)
def test_job_rejects_unknown_inspection_mode_and_format(web_parts, payload):
    _app, client, service, *_ = web_parts
    token = inspect(client)
    if payload["inspection_id"] == "TOKEN":
        payload["inspection_id"] = token
    response = client.post("/api/jobs", json=payload)
    assert response.status_code in {400, 404}
    assert service.jobs == {}


def test_job_rejects_non_json(web_parts):
    assert web_parts[1].post("/api/jobs", data="bad").status_code == 400


def test_job_failure_is_public_and_does_not_expose_path(web_parts):
    _app, client, service, *_ = web_parts
    service.audio_func = Mock(side_effect=RuntimeError("failure at /secret/path"))
    token = inspect(client)
    job_id = client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    ).json["job_id"]
    status = client.get(f"/api/jobs/{job_id}")
    assert status.json["status"] == "error"
    assert "/secret/path" not in status.get_data(as_text=True)
    response = client.get(f"/api/jobs/{job_id}/file")
    assert response.status_code == 409


@pytest.mark.parametrize("kind", ["outside", "extension", "empty"])
def test_job_rejects_invalid_downloader_result(web_parts, tmp_path, kind):
    _app, client, service, *_ = web_parts

    def invalid(**kwargs):
        if kind == "outside":
            path = tmp_path / "outside.mp3"
        elif kind == "extension":
            path = Path(kwargs["download_dir"]) / "wrong.wav"
        else:
            path = Path(kwargs["download_dir"]) / "empty.mp3"
        path.write_bytes(b"" if kind == "empty" else b"data")
        return path

    service.audio_func = invalid
    token = inspect(client)
    job_id = client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    ).json["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json["status"] == "error"


def test_queued_and_running_job_statuses_and_missing_job(web_parts):
    _app, client, service, *_ = web_parts
    client.get("/")
    assigned = user_id(client)
    job_dir = service.users_dir / assigned
    service.jobs["queued"] = DownloadJob("queued", job_dir, assigned)
    service.jobs["running"] = DownloadJob("running", job_dir, assigned)
    assert client.get("/api/jobs/queued").json == {"status": "queued"}
    assert client.get("/api/jobs/running").json == {"status": "running"}
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/jobs/missing/file").status_code == 404
    assert client.get("/api/jobs/queued/file").status_code == 409


def test_expired_ready_file_returns_gone(web_parts):
    _app, client, service, *_ = web_parts
    client.get("/")
    assigned = user_id(client)
    missing = service.users_dir / assigned / "expired.mp3"
    service.jobs["expired"] = DownloadJob(
        "ready", missing.parent, assigned, path=missing
    )
    response = client.get("/api/jobs/expired/file")
    assert response.status_code == 410
    assert response.json == {"error": "The file has expired and was removed."}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0.0),
        (1.25, 1.25),
        (None, None),
        (True, None),
        (float("nan"), None),
        (float("inf"), None),
        (-1, None),
        ("10", None),
    ],
)
def test_progress_number_accepts_only_finite_nonnegative_numbers(value, expected):
    assert _progress_number(value) == expected


def test_download_progress_hook_tracks_bytes_fragments_and_processing_stages(web_parts):
    _app, client, service, *_ = web_parts
    client.get("/")
    assigned = user_id(client)
    directory = service.users_dir / assigned
    service.jobs["progress"] = DownloadJob("running", directory, assigned)
    video_progress = service._progress_hook("progress", "video")

    video_progress({"status": "waiting"})
    assert service.jobs["progress"].stage is None
    video_progress({"status": "processing", "stage": "checking_metadata"})
    assert service.jobs["progress"].stage == "checking_metadata"
    video_progress({"status": "started", "postprocessor": "FFmpegExtractAudio"})
    assert service.jobs["progress"].stage == "converting_audio"
    video_progress({"status": "started", "postprocessor": "FFmpegMerger"})
    assert service.jobs["progress"].stage == "merging_video"
    video_progress({"status": "started", "postprocessor": "FFmpegVideoRemuxer"})
    assert service.jobs["progress"].stage == "merging_video"
    video_progress({"status": "started", "postprocessor": "MoveFiles"})
    assert service.jobs["progress"].stage == "finalizing"

    video_progress(
        {
            "status": "downloading",
            "downloaded_bytes": 256,
            "total_bytes": 1024,
            "info_dict": {"vcodec": "avc1"},
        }
    )
    response = client.get("/api/jobs/progress")
    assert response.json == {
        "status": "running",
        "stage": "downloading_video",
        "percent": 25,
        "downloaded_bytes": 256,
        "total_bytes": 1024,
    }

    video_progress(
        {
            "status": "downloading",
            "downloaded_bytes": 1200,
            "total_bytes": 0,
            "total_bytes_estimate": 1000,
            "info_dict": {"vcodec": "none"},
        }
    )
    job = service.jobs["progress"]
    assert (job.stage, job.percent, job.total_bytes) == (
        "downloading_audio",
        100,
        1000,
    )

    video_progress(
        {
            "status": "downloading",
            "fragment_index": 3,
            "fragment_count": 8,
            "info_dict": {},
        }
    )
    job = service.jobs["progress"]
    assert (job.stage, job.percent, job.downloaded_bytes, job.total_bytes) == (
        "downloading_video",
        38,
        None,
        None,
    )

    video_progress({"status": "finished", "info_dict": {}})
    assert service.jobs["progress"].percent is None
    audio_progress = service._progress_hook("progress", "audio")
    audio_progress(
        {
            "status": "downloading",
            "downloaded_bytes": 10,
            "total_bytes": 100,
        }
    )
    assert service.jobs["progress"].stage == "downloading_audio"
    audio_progress({"status": "started", "postprocessor": "FFmpegMerger"})
    assert service.jobs["progress"].stage == "finalizing"
    service._set_progress("missing", stage="ignored")


def test_executor_failure_returns_service_unavailable_and_cleans_job(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DOWNLOAD_DIR": str(tmp_path),
            "EXECUTOR": InlineExecutor(RuntimeError("queue stopped")),
        }
    )
    app.logger.disabled = True
    service = app.extensions["download_service"]
    service.formats_func = Mock(return_value=[])
    client = app.test_client()
    token = inspect(client)
    response = client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    )
    assert response.status_code == 503
    assert service.jobs == {}
    assert (service.users_dir / user_id(client)).is_dir()


def test_bounded_queue_rejects_excess_jobs_and_api_returns_429(tmp_path):
    executor = HoldingExecutor()
    app = create_app(
        {
            "TESTING": True,
            "DOWNLOAD_DIR": str(tmp_path),
            "EXECUTOR": executor,
            "MAX_PENDING_JOBS": 1,
        }
    )
    service = app.extensions["download_service"]
    service.formats_func = Mock(return_value=[])
    client = app.test_client()
    token = inspect(client)
    assert client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    ).status_code == 202
    response = client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    )
    assert response.status_code == 429
    assert "busy" in response.json["error"]


def test_repeated_audio_download_uses_filesystem_cache(web_parts):
    _app, client, service, _formats, _video, audio = web_parts
    token = inspect(client)
    first_id = client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    ).json["job_id"]
    second_id = client.post(
        "/api/jobs", json={"inspection_id": token, "mode": "audio"}
    ).json["job_id"]

    first = service.jobs[first_id].path
    second = service.jobs[second_id].path
    assert first == second
    assert audio.call_count == 1
    cached = list(service.cache_dir.glob("*/*.mp3"))
    assert len(cached) == 1
    assert first.stat().st_ino == cached[0].stat().st_ino


def test_cache_is_shared_but_user_files_and_jobs_are_isolated(web_parts):
    app, first_client, service, _formats, _video, audio = web_parts
    first_token = inspect(first_client)
    first_job = first_client.post(
        "/api/jobs", json={"inspection_id": first_token, "mode": "audio"}
    ).json["job_id"]

    second_client = app.test_client()
    second_token = inspect(second_client)
    assert second_client.get(f"/api/inspections/{first_token}/formats").status_code == 404
    assert second_client.post(
        "/api/jobs", json={"inspection_id": first_token, "mode": "audio"}
    ).status_code == 404
    assert second_client.get(f"/api/jobs/{first_job}").status_code == 404
    assert second_client.get(f"/api/jobs/{first_job}/file").status_code == 404

    second_job = second_client.post(
        "/api/jobs", json={"inspection_id": second_token, "mode": "audio"}
    ).json["job_id"]
    first_path = service.jobs[first_job].path
    second_path = service.jobs[second_job].path
    assert audio.call_count == 1
    assert first_path.parent.name == user_id(first_client)
    assert second_path.parent.name == user_id(second_client)
    assert first_path.parent != second_path.parent
    assert first_path.stat().st_ino == second_path.stat().st_ino


def test_filesystem_cache_survives_application_restart(tmp_path):
    def make_audio(**kwargs):
        path = Path(kwargs["download_dir"]) / "Artist - Cached Song.mp3"
        path.write_bytes(b"cached audio")
        return path

    common = {
        "TESTING": True,
        "DOWNLOAD_DIR": str(tmp_path),
        "EXECUTOR": InlineExecutor(),
    }
    first_app = create_app(common)
    first_service = first_app.extensions["download_service"]
    first_service.formats_func = Mock(return_value=[])
    first_service.audio_func = Mock(side_effect=make_audio)
    first_client = first_app.test_client()
    first_token = inspect(first_client)
    first_client.post(
        "/api/jobs", json={"inspection_id": first_token, "mode": "audio"}
    )

    second_app = create_app(common)
    second_service = second_app.extensions["download_service"]
    second_service.formats_func = Mock(return_value=[])
    second_service.audio_func = Mock(side_effect=AssertionError("must use cache"))
    second_client = second_app.test_client()
    second_token = inspect(second_client)
    job_id = second_client.post(
        "/api/jobs", json={"inspection_id": second_token, "mode": "audio"}
    ).json["job_id"]
    assert second_client.get(f"/api/jobs/{job_id}").json["status"] == "ready"
    second_service.audio_func.assert_not_called()


def test_cleanup_removes_expired_hardlinks_once_and_keeps_recent_media(tmp_path):
    now = 1_000_000.0
    service = web_module.DownloadService(
        tmp_path,
        executor=InlineExecutor(),
        retention_seconds=7 * 24 * 60 * 60,
        max_storage_bytes=1_000,
        now_func=lambda: now,
    )
    user_dir = service.users_dir / "user"
    cache_entry = service.cache_dir / "cache-key"
    legacy_dir = tmp_path / ".web-jobs" / "legacy"
    user_dir.mkdir(parents=True)
    cache_entry.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    (service.users_dir / "not-a-directory").write_text("ignored")

    expired = user_dir / "expired.mkv"
    expired.write_bytes(b"x" * 10)
    cached = cache_entry / expired.name
    cached.hardlink_to(expired)
    os.utime(expired, (now - 8 * 24 * 60 * 60,) * 2)
    recent = user_dir / "recent.mp3"
    recent.write_bytes(b"new")
    os.utime(recent, (now - 60,) * 2)
    (user_dir / "notes.txt").write_text("keep")
    (legacy_dir / "recent.mkv").write_bytes(b"legacy")

    assert service.cleanup() == (1, 10)
    assert not expired.exists()
    assert not cached.exists()
    assert recent.exists()
    assert not cache_entry.exists()
    assert user_dir.exists()


def test_cleanup_trims_oldest_unique_media_but_protects_active_file(tmp_path):
    now = 2_000_000.0
    service = web_module.DownloadService(
        tmp_path,
        executor=InlineExecutor(),
        retention_seconds=10_000_000,
        max_storage_bytes=5,
        now_func=lambda: now,
    )
    old_dir = service.users_dir / "old-user"
    new_dir = service.users_dir / "new-user"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old = old_dir / "old.mkv"
    new = new_dir / "new.mp3"
    old.write_bytes(b"123456")
    new.write_bytes(b"1234")
    os.utime(old, (now - 100,) * 2)
    os.utime(new, (now - 50,) * 2)

    assert service.cleanup(protected_paths=(old,)) == (1, 4)
    assert old.exists() and not new.exists()
    service.jobs["active"] = DownloadJob(
        "running", old_dir, "old-user", path=old
    )
    assert service.cleanup() == (0, 0)
    service.jobs["active"].status = "ready"
    assert service.cleanup() == (1, 6)
    assert not old.exists()


def test_create_app_runs_or_skips_startup_cleanup_as_configured(tmp_path):
    expired_dir = tmp_path / "cleanup" / "users" / "user"
    expired_dir.mkdir(parents=True)
    expired = expired_dir / "expired.mp3"
    expired.write_bytes(b"old")
    os.utime(expired, (0, 0))
    create_app(
        {
            "TESTING": True,
            "DOWNLOAD_DIR": str(tmp_path / "cleanup"),
            "EXECUTOR": InlineExecutor(),
        }
    )
    assert not expired.exists()

    kept_dir = tmp_path / "no-cleanup" / "users" / "user"
    kept_dir.mkdir(parents=True)
    kept = kept_dir / "kept.mp3"
    kept.write_bytes(b"old")
    os.utime(kept, (0, 0))
    create_app(
        {
            "TESTING": True,
            "DOWNLOAD_DIR": str(tmp_path / "no-cleanup"),
            "EXECUTOR": InlineExecutor(),
            "CLEANUP_ON_START": False,
        }
    )
    assert kept.exists()


def test_video_formats_get_separate_cache_entries(web_parts):
    _app, client, service, _formats, video, _audio = web_parts
    token = inspect(client)
    current = service.inspections[token]
    service.inspections[token] = web_module.Inspection(
        url=current.url,
        video_id=current.video_id,
        user_id=current.user_id,
        formats=(
            {"id": "18", "height": 360, "size": 1024},
            {"id": "22", "height": 720, "size": 2048},
        ),
    )
    for format_id in ("18", "22", "18"):
        client.post(
            "/api/jobs",
            json={"inspection_id": token, "mode": "video", "format_id": format_id},
        )
    assert video.call_count == 2
    assert len(list(service.cache_dir.glob("*/*.mkv"))) == 2


def test_cache_helpers_reject_ambiguous_or_invalid_entries(web_parts, tmp_path):
    service = web_parts[2]
    assert service._cached_file("missing", ".mp3") is None
    directory = service.cache_dir / "ambiguous"
    directory.mkdir(parents=True)
    (directory / "wrong.wav").write_bytes(b"data")
    (directory / "empty.mp3").write_bytes(b"")
    assert service._cached_file("ambiguous", ".mp3") is None
    (directory / "one.mp3").write_bytes(b"one")
    assert service._cached_file("ambiguous", ".mp3").name == "one.mp3"
    (directory / "two.mp3").write_bytes(b"two")
    assert service._cached_file("ambiguous", ".mp3") is None

    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    stored = service._store_cache("stored", source)
    assert service._store_cache("stored", source) == stored


def test_link_for_user_preserves_different_same_named_file(tmp_path):
    source_dir = tmp_path / "cache"
    user_dir = tmp_path / "user"
    source_dir.mkdir()
    user_dir.mkdir()
    source = source_dir / "Song.mp3"
    source.write_bytes(b"cached")
    (user_dir / "Song.mp3").write_bytes(b"different")
    linked = web_module.DownloadService._link_for_user(source, user_dir)
    assert linked.name == "Song (2).mp3"
    assert web_module.DownloadService._link_for_user(source, user_dir) == linked


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtu.be/short-id", "short-id"),
        ("https://youtube.com/watch?v=watch-id&list=ignored", "watch-id"),
        ("https://youtube.com/shorts/path-id", "path-id"),
    ],
)
def test_youtube_video_id_normalizes_supported_url_shapes(url, expected):
    assert _youtube_video_id(url) == expected


def test_cache_key_separates_modes_and_formats():
    base = _cache_key("video", "video", "18")
    assert len(base) == 64
    assert base == _cache_key("video", "video", "18")
    assert base != _cache_key("video", "video", "22")
    assert base != _cache_key("video", "audio", None)


def test_persistent_secret_is_reused_and_repairs_empty_file(tmp_path):
    first = _persistent_secret(tmp_path)
    assert len(first) == 32
    assert _persistent_secret(tmp_path) == first
    secret_file = tmp_path / ".web-secret"
    secret_file.write_bytes(b"")
    replacement = _persistent_secret(tmp_path)
    assert len(replacement) == 32
    assert replacement != b""


def test_explicit_secret_key_is_preserved(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DOWNLOAD_DIR": str(tmp_path),
            "SECRET_KEY": "configured-secret",
            "EXECUTOR": InlineExecutor(),
        }
    )
    assert app.config["SECRET_KEY"] == "configured-secret"
    assert not (tmp_path / ".web-secret").exists()


def test_payload_size_limit_returns_json(web_parts):
    response = web_parts[1].post(
        "/api/inspect",
        data='{"url":"' + "x" * 5000 + '"}',
        content_type="application/json",
    )
    assert response.status_code == 413
    assert response.json == {"error": "The request is too large."}

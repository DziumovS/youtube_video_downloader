import pytest
from src.downloader import download, get_formats

@pytest.mark.skip(reason="Skipping real download in CI")
def test_download_144p(tmp_path):
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    formats = get_formats(url, proxy=None)
    if not formats:
        pytest.skip("No formats found for test video")
    selected = formats[0]
    download(url, selected["id"], str(tmp_path), concurrent_fragment_downloads=1, proxy=None)
    files = list(tmp_path.iterdir())
    assert files, "No files downloaded"

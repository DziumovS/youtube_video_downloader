import pytest
from src.downloader import get_formats

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
])
def test_get_formats_returns_list(url):
    formats = get_formats(url, proxy=None)
    assert isinstance(formats, list)
    if formats:
        f = formats[0]
        assert "id" in f and "height" in f and "size" in f

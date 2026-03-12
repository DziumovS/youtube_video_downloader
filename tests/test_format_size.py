import pytest
from src.downloader import format_size

def test_format_size_none():
    assert format_size(None) == "unknown"

def test_format_size_zero():
    assert format_size(0) == "unknown"

def test_format_size_small():
    size_bytes = 1024 * 1024  # 1 MB
    result = format_size(size_bytes)
    assert result.startswith("~1")

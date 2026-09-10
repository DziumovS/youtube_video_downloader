import pytest
from src.downloader import format_size

def test_format_size_none():
    assert format_size(None) == "unknown"

def test_format_size_zero():
    assert format_size(0) == "unknown"

def test_format_size_negative():
    assert format_size(-100) == "unknown"

def test_format_size_small():
    size_bytes = 1024 * 1024  # 1 MB
    assert format_size(size_bytes) == "~1 MB"


def test_format_size_uses_decimal_megabytes_without_artificial_overhead():
    assert format_size(946_670_904) == "~947 MB"

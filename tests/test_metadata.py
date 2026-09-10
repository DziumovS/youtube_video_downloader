import io
import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

from src import metadata


TARGET = {
    "artistName": "Sonya Belousova, Giona Ostinelli & Joey Batey",
    "collectionArtistName": "Sonya Belousova & Giona Ostinelli",
    "trackName": "Toss a Coin to Your Witcher",
    "trackTimeMillis": 190_307,
}


def response(payload):
    stream = io.BytesIO(json.dumps(payload).encode())
    stream.__enter__ = lambda self: self
    stream.__exit__ = lambda *_args: stream.close()
    return stream


def test_catalog_formats_album_artists_and_featured_artist():
    cover = {
        "artistName": "Tomi P",
        "trackName": "Toss a Coin to Your Witcher",
        "trackTimeMillis": 189_500,
    }
    result = metadata._best_match(
        [cover, TARGET],
        "Toss A Coin To Your Witcher",
        190,
        ["sonya belousova", "giona ostinelli", "joey batey"],
    )
    assert result == (
        "Sonya Belousova & Giona Ostinelli ft. Joey Batey",
        "Toss a Coin to Your Witcher",
    )


@pytest.mark.parametrize(
    "results",
    [
        None,
        [None],
        [{"trackName": "Different", "artistName": "Artist", "trackTimeMillis": 1}],
        [{"trackName": "Song", "artistName": "", "trackTimeMillis": 1}],
        [{"trackName": "Song", "artistName": "Artist"}],
        [{"trackName": "Song", "artistName": "Artist", "trackTimeMillis": 20_000}],
    ],
)
def test_catalog_rejects_incomplete_or_ambiguous_results(results):
    assert metadata._best_match(results, "Song", 1, None) is None


def test_catalog_accepts_exact_duration_without_tags_and_plain_credit():
    result = metadata._best_match(
        [{"trackName": "Song!", "artistName": "Artist", "trackTimeMillis": 1_500}],
        "song",
        1,
        "not-a-list",
    )
    assert result == ("Artist", "Song!")


def test_artist_parser_rejects_non_text_values():
    assert metadata._artists(None) == []


def test_catalog_keeps_full_credit_when_album_credit_has_no_feature():
    item = {
        "trackName": "Song",
        "artistName": "Artist & Collaborator",
        "collectionArtistName": "Artist & Collaborator",
        "trackTimeMillis": 1_000,
    }
    assert metadata._best_match([item], "Song", 1, []) == (
        "Artist & Collaborator", "Song"
    )


def test_lookup_sends_encoded_query_and_reads_result():
    with patch("src.metadata.urlopen", return_value=response({"results": [TARGET]})) as opened:
        result = metadata.lookup_track_credit(
            "Toss A Coin To Your Witcher", 190, ["Joey Batey"]
        )
    assert result == (
        "Sonya Belousova & Giona Ostinelli ft. Joey Batey",
        "Toss a Coin to Your Witcher",
    )
    request = opened.call_args.args[0]
    assert "Toss+A+Coin+To+Your+Witcher" in request.full_url
    assert opened.call_args.kwargs == {"timeout": 5}


@pytest.mark.parametrize(
    "failure",
    [URLError("offline"), OSError("network"), ValueError("json"), UnicodeError("text")],
)
def test_lookup_network_or_decode_failure_is_a_safe_fallback(failure):
    with patch("src.metadata.urlopen", side_effect=failure):
        assert metadata.lookup_track_credit("Song", 100, []) is None


def test_lookup_rejects_non_object_payload():
    with patch("src.metadata.urlopen", return_value=response([])):
        assert metadata.lookup_track_credit("Song", None, None) is None

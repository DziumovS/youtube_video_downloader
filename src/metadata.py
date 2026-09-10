"""Conservative fallback for music credits missing from YouTube metadata."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
_ARTIST_SEPARATOR = re.compile(r"\s*(?:,|&|\band\b)\s*", re.IGNORECASE)
_NON_WORDS = re.compile(r"[^\w]+", re.UNICODE)


def _normalized(value: Any) -> str:
    return _NON_WORDS.sub(" ", value.casefold()).strip() if isinstance(value, str) else ""


def _artists(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in _ARTIST_SEPARATOR.split(value) if part.strip()]


def _credit_name(result: dict[str, Any]) -> str:
    all_credit = result.get("artistName")
    if not isinstance(all_credit, str) or not all_credit.strip():
        return ""
    all_credit = all_credit.strip()
    album_credit = result.get("collectionArtistName")
    if not isinstance(album_credit, str) or not album_credit.strip():
        return all_credit

    album_credit = album_credit.strip()
    album_artists = {_normalized(name) for name in _artists(album_credit)}
    featured = [
        name for name in _artists(all_credit) if _normalized(name) not in album_artists
    ]
    if album_artists and featured:
        return f"{album_credit} ft. {' & '.join(featured)}"
    return all_credit


def _tag_names(tags: Any) -> set[str]:
    if not isinstance(tags, list):
        return set()
    return {_normalized(tag) for tag in tags if _normalized(tag)}


def _best_match(
    results: Any,
    title: str,
    duration: Any,
    tags: Any,
) -> tuple[str, str] | None:
    if not isinstance(results, list):
        return None
    wanted_title = _normalized(title)
    wanted_duration = float(duration) * 1000 if isinstance(duration, (int, float)) else None
    normalized_tags = _tag_names(tags)
    matches: list[tuple[int, float, str, str]] = []

    for result in results:
        if not isinstance(result, dict) or _normalized(result.get("trackName")) != wanted_title:
            continue
        credit = _credit_name(result)
        track = result.get("trackName")
        milliseconds = result.get("trackTimeMillis")
        if not credit or not isinstance(track, str) or not isinstance(milliseconds, (int, float)):
            continue
        difference = abs(milliseconds - wanted_duration) if wanted_duration is not None else float("inf")
        artist_tags = sum(
            _normalized(artist) in normalized_tags for artist in _artists(result.get("artistName"))
        )
        # Exact duration alone is useful; otherwise at least one credited artist
        # must agree with a YouTube tag. Reject covers with merely the same title.
        if difference > 1_000 and (difference > 5_000 or artist_tags == 0):
            continue
        matches.append((artist_tags, -difference, credit, track.strip()))

    if not matches:
        return None
    _, _, credit, track = max(matches)
    return credit, track


def lookup_track_credit(
    title: str,
    duration: Any,
    tags: Iterable[Any] | None,
) -> tuple[str, str] | None:
    """Find official artist/track credit; return None on ambiguity or network failure."""
    query = urlencode({"term": title, "entity": "song", "limit": 25})
    request = Request(
        f"{_ITUNES_SEARCH_URL}?{query}",
        headers={"User-Agent": "youtube-video-downloader/0.1"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _best_match(payload.get("results"), title, duration, list(tags) if tags is not None else None)

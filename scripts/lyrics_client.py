#!/usr/bin/env python3
"""Lyrics client — fetch synced/plain lyrics, stdlib only.

Sources, in order: LRCLIB (free, no auth, well curated) then Kuwo, which
covers CJK tracks LRCLIB misses and returns timestamps.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from melodymine_common import (
    is_accompaniment,
    is_derivative,
    strip_version_tag,
    text_sim,
)

UA = "MelodyMine/1.0 (music-downloader; +https://github.com/thintsing/MelodyMine)"


def search(query, limit=5, timeout=10):
    """Search LRCLIB for lyrics.

    Returns list of dicts: {title, artist, album, duration, synced_lyrics, plain_lyrics}
    or empty list on failure.
    """
    if not query:
        return []

    params = urllib.parse.urlencode({"q": query})
    url = f"https://lrclib.net/api/search?{params}"

    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    results = []
    for item in data if isinstance(data, list) else []:
        if item.get("instrumental"):
            continue
        synced = item.get("syncedLyrics") or ""
        plain = item.get("plainLyrics") or ""
        if not synced and not plain:
            continue
        results.append({
            "title": item.get("trackName", ""),
            "artist": item.get("artistName", ""),
            "album": item.get("albumName", ""),
            "duration": item.get("duration", 0),
            "synced_lyrics": synced,
            "plain_lyrics": plain,
        })
        if len(results) >= limit:
            break
    return results


def get_lyrics(artist, title, album=None, timeout=10):
    """Fetch lyrics for a specific song, trying every configured source.

    LRCLIB goes first — it is well curated and needs no matching heuristics.
    Kuwo fills the gap LRCLIB has on CJK tracks, and it returns timestamps, so
    a Kuwo hit is preferred over an LRCLIB plain-text-only hit.

    Returns dict with synced_lyrics and plain_lyrics, or None on failure.
    """
    if not title:
        return None

    lrclib = _get_lyrics_lrclib(artist, title, album, timeout)
    if lrclib and lrclib.get("synced_lyrics"):
        return lrclib

    kuwo = _get_lyrics_kuwo(artist, title, timeout)
    if kuwo:
        return {"synced_lyrics": kuwo, "plain_lyrics": (lrclib or {}).get("plain_lyrics", "")}
    return lrclib


def _get_lyrics_lrclib(artist, title, album, timeout):
    """LRCLIB lookup: direct artist/title hit first, then a search."""
    if artist:
        params = urllib.parse.urlencode({
            "artist_name": artist,
            "track_name": title,
            "album_name": album or "",
        })
        url = f"https://lrclib.net/api/get?{params}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                synced = data.get("syncedLyrics") or ""
                plain = data.get("plainLyrics") or ""
                if synced or plain:
                    return {"synced_lyrics": synced, "plain_lyrics": plain}
        except Exception:
            pass

    query = f"{artist} {title}".strip() if artist else title
    results = search(query, limit=3, timeout=timeout)
    if results:
        return {
            "synced_lyrics": results[0].get("synced_lyrics", ""),
            "plain_lyrics": results[0].get("plain_lyrics", ""),
        }
    return None


def _rank_kuwo_matches(results, artist, title):
    """Kuwo results that could be this song, best first.

    Version tags are stripped before comparing so a live recording of the
    right song still matches — Kuwo indexes most CJK catalogue as live or
    remaster editions. Backing tracks and clipped fragments are demoted:
    their lyric text is missing or partial.
    """
    want_title = strip_version_tag(title)
    scored = []
    for item in results:
        raw_title = item.get("title") or ""
        if text_sim(want_title, strip_version_tag(raw_title)) < 0.7:
            continue
        if artist and text_sim(artist, item.get("artist")) < 0.5:
            continue
        penalty = 0.0
        if is_accompaniment(raw_title):
            penalty += 0.4
        if is_derivative(raw_title):
            penalty += 0.2
        scored.append((penalty, item))
    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored]


def _get_lyrics_kuwo(artist, title, timeout):
    """Kuwo lookup: search for the song, then pull lyrics by its music id."""
    import kuwo_client

    query = f"{artist} {title}".strip() if artist else title
    results = kuwo_client.search(query, limit=10, timeout=timeout)
    if not results:
        return None

    # A demoted candidate may be the only one Kuwo actually has lyrics for.
    for match in _rank_kuwo_matches(results, artist, title)[:3]:
        lrc = kuwo_client.get_lyrics(match["music_id"], timeout=timeout)
        if lrc:
            return lrc
    return None


def save_lrc(filepath, synced_lyrics, plain_lyrics=None):
    """Save lyrics as .lrc file alongside the audio file.

    Prefers synced lyrics (with timestamps) if available.
    Returns the .lrc file path on success, None on failure.
    """
    if not filepath:
        return None

    lyrics = synced_lyrics or plain_lyrics
    if not lyrics:
        return None

    base = os.path.splitext(filepath)[0]
    lrc_path = base + ".lrc"

    try:
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(lyrics)
        return lrc_path
    except Exception:
        return None


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not q:
        print("Usage: python lyrics_client.py <query>")
        sys.exit(1)
    results = search(q, limit=3)
    for r in results:
        print(f"{r['artist']} - {r['title']}")
        if r.get("synced_lyrics"):
            print("  [synced lyrics available]")
        if r.get("plain_lyrics"):
            lines = r["plain_lyrics"].split("\n")[:3]
            print(f"  Preview: {' / '.join(lines)[:30]}...")
        print()

#!/usr/bin/env python3
"""YouTube Music search via ytmusicapi — no cookies/auth needed for search.

Usage:
    python ytmusic_client.py "许飞 父亲写的散文诗"
    python ytmusic_client.py "The Weeknd Blinding Lights" 5
"""

import json
import sys


def search(query, limit=5):
    """Search YouTube Music catalog by song title/artist.

    Tries ``filter="songs"`` first (precise), falls back to
    ``filter="videos"`` (broader recall).  Returns a list of dicts with
    ``videoId``, ``title``, ``artist``, ``duration``, ``album``, and
    ``browseId``, or an empty list on failure.
    """
    try:
        from ytmusicapi import YTMusic
    except ImportError:
        return []

    ytm = YTMusic()

    # Tier 1: songs filter (cleaner results, often empty for Chinese/Asian)
    try:
        results = ytm.search(query, filter="songs", limit=limit)
    except Exception:
        results = []

    # Tier 2: videos filter (broader recall)
    if not results:
        try:
            results = ytm.search(query, filter="videos", limit=limit)
        except Exception:
            return []

    out = []
    for r in results:
        rid = r.get("videoId", "")
        if not rid:
            continue
        # ytmusicapi 1.12+ returns artists as a list of dicts with name/key
        artists_raw = r.get("artists", [])
        if isinstance(artists_raw, list):
            artist = ", ".join(
                a.get("name", "") for a in artists_raw if isinstance(a, dict)
            )
        else:
            artist = str(artists_raw) if artists_raw else ""
        album_raw = r.get("album", {})
        album = album_raw.get("name", "") if isinstance(album_raw, dict) else ""

        out.append({
            "videoId": rid,
            "title": r.get("title", ""),
            "artist": artist,
            "duration": r.get("duration", None),
            "album": album,
            "url": f"https://music.youtube.com/watch?v={rid}",
        })
    return out


if __name__ == "__main__":
    q = " ".join(sys.argv[1:-1]) if len(sys.argv) > 2 else (sys.argv[1] if len(sys.argv) > 1 else "")
    n = int(sys.argv[-1]) if len(sys.argv) > 2 and sys.argv[-1].isdigit() else 5
    if not q:
        print("Usage: python ytmusic_client.py <query> [limit]")
        sys.exit(1)
    results = search(q, limit=n)
    print(json.dumps(results, ensure_ascii=False, indent=2))
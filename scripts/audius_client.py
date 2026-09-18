#!/usr/bin/env python3
"""Audius API client — search + stream URL, stdlib only.

Audius is a decentralized music streaming platform with a free, open API.
No authentication required — just an app_name identifier.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
APP_NAME = "MelodyMine"

_API_BASE = "https://api.audius.co"
_SEARCH_URL = f"{_API_BASE}/v1/tracks/search"
_STREAM_URL = f"{_API_BASE}/v1/tracks"


def _get_json(url, params, timeout=10):
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    req = urllib.request.Request(full)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    req.add_header("Referer", "https://audius.co/")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def search(query, limit=10, timeout=10):
    """Search Audius for tracks.

    Returns list of dicts: {title, artist, track_id, duration, artwork_url}
    or empty list on failure.
    """
    if not query:
        return []

    params = {
        "query": query,
        "limit": limit,
        "offset": 0,
        "app_name": APP_NAME,
    }

    body = _get_json(_SEARCH_URL, params, timeout)
    if not body:
        return []

    tracks = body.get("data") or []
    results = []
    for track in tracks:
        track_id = track.get("id", "")
        if not track_id:
            continue

        user = track.get("user") or {}
        artist = user.get("name", "")

        artwork = track.get("artwork") or {}
        art_url = artwork.get("1000x1000") or artwork.get("480x480") or artwork.get("150x150") or ""

        results.append({
            "title": track.get("title", ""),
            "artist": artist,
            "track_id": track_id,
            "duration": int(track.get("duration", 0)),
            "artwork_url": art_url,
        })
    return results


def get_stream_url(track_id, timeout=10):
    """Get the stream URL for an Audius track.

    The returned URL redirects (302) to the actual audio stream.
    Returns the URL string, or None on failure.
    """
    if not track_id:
        return None

    params = {"app_name": APP_NAME}
    qs = urllib.parse.urlencode(params)
    return f"{_STREAM_URL}/{track_id}/stream?{qs}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "search" and len(sys.argv) >= 3:
        q = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        results = search(q, limit=n)
        for r in results:
            mins = r["duration"] // 60
            secs = r["duration"] % 60
            print(f"{r['artist']} - {r['title']}  [{mins}:{secs:02d}]")
    elif cmd == "url" and len(sys.argv) >= 3:
        tid = sys.argv[2]
        url = get_stream_url(tid)
        print(url or "(no URL)")
    else:
        print("Usage: python audius_client.py search <query> [limit]")
        print("       python audius_client.py url <trackId>")
        sys.exit(1)

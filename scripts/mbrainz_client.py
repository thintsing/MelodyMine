#!/usr/bin/env python3
"""MusicBrainz API client — recording lookup with cover art, stdlib only."""

import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

UA = "MelodyMine/1.0 (music-downloader; +https://github.com/thintsing/MelodyMine)"


def lookup(query, limit=5, timeout=15):
    """Search MusicBrainz for song metadata (artist, album, cover art).

    Rate-limited: sleeps 0.5s before each request per MusicBrainz policy.

    Returns list of dicts: {title, artist, album, duration, pic_url}
    or empty list on failure.
    """
    time.sleep(0.5)
    mb_query = urllib.parse.quote(query)
    url = f"https://musicbrainz.org/ws/2/recording/?query={mb_query}&limit={limit}&fmt=json"

    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    results = []
    for rec in data.get("recordings", []):
        title = rec.get("title", "")
        ac = rec.get("artist-credit", [])
        artist = ac[0]["name"] if ac else ""
        releases = rec.get("releases", [])
        album = releases[0]["title"] if releases else ""
        release_mbid = releases[0]["id"] if releases else ""
        duration_ms = rec.get("length", 0)
        pic_url = _resolve_cover(release_mbid, timeout=timeout) if release_mbid else ""
        if title and artist:
            results.append({
                "title": title, "artist": artist, "album": album,
                "duration": duration_ms, "pic_url": pic_url,
            })
    return results


def _resolve_cover(release_mbid, timeout=10):
    """Fetch cover art URL for a release MBID from Cover Art Archive."""
    for size in ["front-500", "front"]:
        time.sleep(0.3)
        try:
            ca_req = urllib.request.Request(
                f"https://coverartarchive.org/release/{release_mbid}/{size}"
            )
            ca_req.add_header("User-Agent", UA)
            with urllib.request.urlopen(ca_req, timeout=timeout) as ca_resp:
                if ca_resp.status == 200:
                    return ca_resp.url
        except Exception:
            continue
    return ""


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    if not q:
        print("Usage: python mbrainz_client.py <query> [limit]")
        sys.exit(1)
    results = lookup(q, limit=n)
    print(json.dumps(results, ensure_ascii=False))

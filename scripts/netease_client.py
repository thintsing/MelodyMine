#!/usr/bin/env python3
"""NetEase Cloud Music API client — search + song detail, stdlib only."""

import json
import sys
import urllib.request
import urllib.error
import urllib.parse

from melodymine_common import BILI_UA as UA


def search(query, limit=3, timeout=10):
    """Search NetEase for songs by query string.

    Returns list of dicts: {title, artist, album, duration, pic_url}
    or empty list on failure.
    """
    data = urllib.parse.urlencode({"s": query, "type": 1, "limit": limit, "offset": 0}).encode()
    req = urllib.request.Request(
        "https://music.163.com/api/search/get",
        data=data,
    )
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://music.163.com")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    if body.get("code") != 200:
        return []

    results = []
    for song in body.get("result", {}).get("songs", []):
        artists = ", ".join(a["name"] for a in song.get("artists", []))
        album = song.get("album", {})
        results.append({
            "title": song.get("name", ""),
            "artist": artists,
            "album": album.get("name", ""),
            "duration": song.get("duration", 0),
            "pic_url": album.get("picUrl", ""),
        })
    return results


def detail(song_id, timeout=10):
    """Get song detail by NetEase song ID.

    Returns dict: {title, artist, album} or None on failure.
    """
    data = urllib.parse.urlencode({"ids": f"[{song_id}]", "limit": 1, "offset": 0}).encode()
    req = urllib.request.Request(
        "https://music.163.com/api/song/detail/",
        data=data,
    )
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://music.163.com")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if body.get("code") != 200 or not body.get("songs"):
        return None

    song = body["songs"][0]
    artists = ", ".join(a["name"] for a in song.get("artists", []))
    return {
        "title": song.get("name", ""),
        "artist": artists,
        "album": song.get("album", {}).get("name", ""),
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "search" and len(sys.argv) >= 3:
        q = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        print(json.dumps(search(q, limit=n), ensure_ascii=False))
    elif cmd == "detail" and len(sys.argv) >= 3:
        sid = sys.argv[2]
        print(json.dumps(detail(sid), ensure_ascii=False))
    else:
        print("Usage: python netease_client.py search <query> [limit]")
        print("       python netease_client.py detail <song_id>")
        sys.exit(1)

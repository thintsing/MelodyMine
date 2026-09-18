#!/usr/bin/env python3
"""Kugou Music (酷狗音乐) API client — search + download URL, stdlib only.

Uses third-party fallback endpoints for download URL resolution to avoid
the complex signing required by the official Kugou gateway API.
Also includes a tracker CDN fallback using only MD5 (stdlib hashlib).
"""

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

_SEARCH_URL = "https://songsearch.kugou.com/song_search_v2"

_FALLBACK_APIS = [
    {
        "name": "haitang",
        "url": "https://musicapi.haitangw.net/kgqq/kg.php",
        "params": lambda h, level: {"type": "json", "id": h, "level": level},
        "parse": lambda body: (body.get("data") or {}).get("url"),
    },
    {
        "name": "cocodownloader",
        "url": "https://cocodownloader.markqq.com/api/url",
        "params": lambda h, level: {"id": h, "provider": "kugou"},
        "parse": lambda body: body.get("url"),
    },
]

_TRACKER_URL = "https://trackercdn.kugou.com/i/v2/"
_TRACKER_KEY_SALT = "kgcloudv2"

_QUALITY_LEVELS = ["hires", "lossless", "exhigh"]


def _get_json(url, params, timeout=10, headers=None):
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    req = urllib.request.Request(full)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def search(query, limit=10, timeout=10):
    """Search Kugou for songs.

    Returns list of dicts: {title, artist, album, hash, duration, pic_url}
    or empty list on failure.
    """
    if not query:
        return []

    params = {
        "format": "json",
        "keyword": query,
        "platform": "WebFilter",
        "page": 1,
        "pagesize": limit,
    }

    body = _get_json(_SEARCH_URL, params, timeout)
    if not body:
        return []

    data = body.get("data") or {}
    songs = data.get("lists") or []
    results = []
    for song in songs:
        song_hash = song.get("hash") or song.get("FileHash") or ""
        if not song_hash:
            continue

        title = (song.get("songname") or song.get("SongName")
                 or song.get("OriSongName") or song.get("filename") or "")

        singers = song.get("Singers") or []
        if singers:
            artist = ", ".join(s.get("name", "") for s in singers)
        else:
            artist = song.get("singername") or song.get("SingerName") or ""

        album_info = song.get("albuminfo") or {}
        album = song.get("album_name") or song.get("AlbumName") or ""
        if not album and isinstance(album_info, dict):
            album = album_info.get("name", "")

        duration = song.get("duration") or song.get("Duration") or 0
        timelen = song.get("timelen", 0)
        if not duration and timelen:
            duration = timelen // 1000

        pic = song.get("cover_url") or ""

        results.append({
            "title": title,
            "artist": artist,
            "album": album,
            "hash": song_hash,
            "duration": int(duration),
            "pic_url": pic,
        })
    return results


def _tracker_url(song_hash, timeout=10):
    """Fallback: use Kugou's tracker CDN with MD5 key (no signature needed)."""
    key = hashlib.md5((song_hash + _TRACKER_KEY_SALT).encode()).hexdigest()
    params = {
        "hash": song_hash.lower(),
        "key": key,
        "behavior": "download",
        "pid": 1,
        "cmd": 21,
        "appid": 1001,
        "cdnBackup": 1,
    }
    body = _get_json(_TRACKER_URL, params, timeout)
    if body:
        url = body.get("url")
        if url:
            return url
        urls = body.get("urls") or []
        if urls:
            return urls[0] if isinstance(urls[0], str) else (urls[0].get("url") if isinstance(urls[0], dict) else None)
    return None


def get_download_url(song_hash, quality="lossless", timeout=10):
    """Resolve a downloadable audio URL for a Kugou song.

    Tries third-party fallback APIs first, then the tracker CDN.
    *quality*: one of 'hires', 'lossless', 'exhigh'.
    Returns the URL string, or None on failure.
    """
    if not song_hash:
        return None

    levels = [quality] if quality in _QUALITY_LEVELS else _QUALITY_LEVELS

    for api in _FALLBACK_APIS:
        for level in levels:
            params = api["params"](song_hash, level)
            body = _get_json(api["url"], params, timeout)
            if body:
                url = api["parse"](body)
                if url:
                    return url

    url = _tracker_url(song_hash, timeout)
    if url:
        return url

    return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "search" and len(sys.argv) >= 3:
        q = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        results = search(q, limit=n)
        for r in results:
            print(f"{r['artist']} - {r['title']}  [hash={r['hash'][:12]}...]")
    elif cmd == "url" and len(sys.argv) >= 3:
        h = sys.argv[2]
        q = sys.argv[3] if len(sys.argv) > 3 else "lossless"
        url = get_download_url(h, quality=q)
        print(url or "(no URL)")
    else:
        print("Usage: python kugou_client.py search <query> [limit]")
        print("       python kugou_client.py url <hash> [quality]")
        sys.exit(1)

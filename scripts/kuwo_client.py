#!/usr/bin/env python3
"""Kuwo Music (酷我音乐) API client — search + download URL, stdlib only.

Uses third-party fallback endpoints for download URL resolution to avoid
the DES encryption required by the official mobi.kuwo.cn API.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

_SEARCH_URL = "http://www.kuwo.cn/search/searchMusicBykeyWord"

# Public web-player endpoint: returns time-stamped lines for a music id.
_LYRIC_URL = "https://kuwo.cn/openapi/v1/www/lyric/getlyric"

_FALLBACK_APIS = [
    {
        "name": "haitang",
        "url": "https://musicapi.haitangw.net/music/kw.php",
        "params": lambda sid, level: {"id": sid, "level": level, "type": "json"},
        "parse": lambda body: (body.get("data") or {}).get("url"),
    },
    {
        "name": "nxinxz",
        "url": "http://music.nxinxz.com/kw.php",
        "params": lambda sid, level: {"id": sid, "level": level, "type": "json"},
        "parse": lambda body: (body.get("data") or {}).get("url"),
    },
]

_QUALITY_LEVELS = ["lossless", "exhigh", "standard"]


def _get_json(url, params, timeout=10):
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    req = urllib.request.Request(full)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def search(query, limit=10, timeout=10):
    """Search Kuwo for songs.

    Returns list of dicts: {title, artist, album, music_id, duration, pic_url}
    or empty list on failure.
    """
    if not query:
        return []

    params = {
        "vipver": "1",
        "client": "kt",
        "ft": "music",
        "cluster": "0",
        "strategy": "2012",
        "encoding": "utf8",
        "mobi": "1",
        "issubtitle": "1",
        "show_copyright_off": "1",
        "pn": "0",
        "rn": str(limit),
        "all": query,
    }

    body = _get_json(_SEARCH_URL, params, timeout)
    if not body:
        return []

    songs = body.get("abslist") or []
    results = []
    for song in songs:
        rid = song.get("MUSICRID") or song.get("musicrid") or ""
        if isinstance(rid, str) and rid.startswith("MUSIC_"):
            rid = rid[6:]
        if not rid:
            continue

        title = song.get("SONGNAME") or song.get("name") or song.get("songName") or ""
        artist = song.get("ARTIST") or song.get("artist") or ""
        album = song.get("ALBUM") or song.get("album") or ""
        duration = song.get("DURATION") or song.get("duration") or "0"
        pic = song.get("hts_MVPIC") or song.get("albumpic") or song.get("pic") or ""

        try:
            duration = int(duration)
        except (ValueError, TypeError):
            duration = 0

        results.append({
            "title": title,
            "artist": artist,
            "album": album,
            "music_id": str(rid),
            "duration": duration,
            "pic_url": pic,
        })
    return results


def get_download_url(music_id, quality="lossless", timeout=10):
    """Resolve a downloadable audio URL for a Kuwo song.

    Tries multiple third-party fallback APIs in order.
    *quality*: one of 'lossless' (FLAC), 'exhigh' (high-bitrate MP3), 'standard' (MP3).
    Returns the URL string, or None on failure.
    """
    if not music_id:
        return None

    levels = [quality] if quality in _QUALITY_LEVELS else _QUALITY_LEVELS

    for api in _FALLBACK_APIS:
        for level in levels:
            params = api["params"](music_id, level)
            body = _get_json(api["url"], params, timeout)
            if body:
                url = api["parse"](body)
                if url:
                    return url
    return None


def get_lyrics(music_id, timeout=10):
    """Fetch time-stamped lyrics for a Kuwo song id as LRC text.

    Kuwo's catalogue covers CJK tracks that community sources miss, and this
    endpoint returns timestamps rather than plain text. Returns ``None`` when
    the song has no lyrics (the API answers 200 with an empty ``data``).
    """
    if not music_id:
        return None

    body = _get_json(_LYRIC_URL, {"musicId": music_id}, timeout)
    if not body or body.get("code") != 200:
        return None

    lines = (body.get("data") or {}).get("lrclist") or []
    out = []
    for line in lines:
        text = (line.get("lineLyric") or "").strip()
        if not text:
            continue
        try:
            secs = float(line.get("time") or 0)
        except (TypeError, ValueError):
            secs = 0.0
        # Round before splitting so 59.999 doesn't render as "[00:60.00]".
        mins, sec = divmod(round(max(secs, 0.0), 2), 60)
        out.append(f"[{int(mins):02d}:{sec:05.2f}]{text}")
    return "\n".join(out) if out else None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "search" and len(sys.argv) >= 3:
        q = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        results = search(q, limit=n)
        for r in results:
            print(f"{r['artist']} - {r['title']}  [{r['music_id']}]")
    elif cmd == "url" and len(sys.argv) >= 3:
        mid = sys.argv[2]
        q = sys.argv[3] if len(sys.argv) > 3 else "lossless"
        url = get_download_url(mid, quality=q)
        print(url or "(no URL)")
    elif cmd == "lyrics" and len(sys.argv) >= 3:
        print(get_lyrics(sys.argv[2]) or "(no lyrics)")
    else:
        print("Usage: python kuwo_client.py search <query> [limit]")
        print("       python kuwo_client.py url <musicId> [quality]")
        print("       python kuwo_client.py lyrics <musicId>")
        sys.exit(1)

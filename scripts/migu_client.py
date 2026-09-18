#!/usr/bin/env python3
"""Migu Music (咪咕音乐) API client — search + download URL, stdlib only.

References the public Migu mobile-app API surface.  No OAuth required;
identification is via static app headers (ua / version / channel).
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "MelodyMine/1.0 (music-downloader; +https://github.com/thintsing/MelodyMine)"

_APP_HEADERS = {
    "ua": "Android_migu",
    "version": "6.8.8",
    "channel": "014021I",
    "Origin": "https://h5.nf.migu.cn",
    "Referer": "https://h5.nf.migu.cn/",
}

_SEARCH_URL = "https://c.musicapp.migu.cn/v1.0/content/search_all.do"
_LISTEN_URL = "https://c.musicapp.migu.cn/strategy/listen-url/h5/v2.4"
_FALLBACK_URL = "https://app.pd.nf.migu.cn/MIGUM3.0/v1.0/content/sub/listenSong.do"

_MAGIC = b"\xab\xcd\x01"
_XOR_KEY = b"Jk8qzuePiJ1qE3mDYhLQ3T73DtDoAhLP"

_TONE_FLAGS = ("LQ", "PQ", "HQ", "SQ", "ZQ", "ZQ24", "ZQ32")


def _decrypt(body):
    """Decrypt Migu's XOR-shift encrypted JSON response.

    Format: 3 magic bytes (\\xab\\xcd\\x01) + 1 seed byte + encrypted payload.
    Each decrypted byte = (encrypted_byte + seed - key[i % 32]) & 0xFF.
    Returns the raw bytes on success, or None if the payload is not encrypted.
    """
    if len(body) < 4 or body[:3] != _MAGIC:
        return None
    seed = body[3]
    enc = body[4:]
    return bytes((b + seed - _XOR_KEY[i % 32]) & 0xFF for i, b in enumerate(enc))


def _request(url, params, timeout, expect_binary=False):
    """Issue a GET request with Migu app headers.

    When *expect_binary* is True the raw response bytes are returned (needed
    for the encrypted-listen endpoint where Content-Type is unreliable).
    """
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    req = urllib.request.Request(full)
    req.add_header("User-Agent", UA)
    for k, v in _APP_HEADERS.items():
        req.add_header(k, v)
    if expect_binary:
        req.add_header("signature", "1")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception:
        return None

    if expect_binary:
        decrypted = _decrypt(raw)
        if decrypted is not None:
            raw = decrypted
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def search(query, limit=5, timeout=10):
    """Search Migu for songs.

    Returns list of dicts: {title, artist, album, content_id, copyright_id,
    duration, pic_url, has_flac}
    or empty list on failure.
    """
    if not query:
        return []

    search_switch = {
        "songResultData": {"needRecord": 1, "pageNumber": 1, "pageSize": limit},
    }
    params = {
        "text": query,
        "pageNo": 1,
        "pageSize": limit,
        "isCopyright": 1,
        "sort": 1,
        "searchSwitch": json.dumps(search_switch),
    }

    body = _request(_SEARCH_URL, params, timeout)
    if not body:
        return []

    songs = (body.get("songResultData") or {}).get("result") or []
    results = []
    for song in songs:
        content_id = song.get("contentId", "")
        copyright_id = song.get("copyrightId", "")
        if not content_id or not copyright_id:
            continue

        singers = song.get("singers") or []
        artist = ", ".join(s.get("name", "") for s in singers)

        album_info = song.get("album") or {}
        album = album_info.get("albumName", "") if isinstance(album_info, dict) else ""
        pic = album_info.get("picUrl", "") if isinstance(album_info, dict) else ""

        has_flac = False
        for rf in (song.get("rateFormats") or []):
            if rf.get("resourceType") in ("E", "F", "ZQ", "ZQ24", "ZQ32"):
                has_flac = True
                break

        results.append({
            "title": song.get("name", ""),
            "artist": artist,
            "album": album,
            "content_id": content_id,
            "copyright_id": copyright_id,
            "duration": song.get("length", 0),
            "pic_url": pic,
            "has_flac": has_flac,
        })
    return results


def get_download_url(content_id, copyright_id, tone_flag="HQ", timeout=10):
    """Resolve a playable audio URL for a Migu song.

    Tries the primary listen-url endpoint first; falls back to the direct
    content-sub URL.  Returns the URL string, or None on failure.

    *tone_flag* selects quality: LQ (mp3 128k), PQ, HQ (mp3), SQ (flac),
    ZQ (flac), ZQ24 (24-bit flac), ZQ32 (32-bit flac).
    """
    if not content_id or not copyright_id:
        return None
    if tone_flag not in _TONE_FLAGS:
        tone_flag = "HQ"

    params = {
        "contentId": content_id,
        "copyrightId": copyright_id,
        "resourceType": 2,
        "netType": "01",
        "toneFlag": tone_flag,
        "scene": "",
        "lowerQualityContentId": "",
    }

    body = _request(_LISTEN_URL, params, timeout, expect_binary=True)
    if body:
        url = (body.get("data") or {}).get("url")
        if url:
            return url

    params_fb = {
        "channel": "mx",
        "copyrightId": copyright_id,
        "contentId": content_id,
        "toneFlag": tone_flag,
        "resourceType": 2,
    }
    qs = urllib.parse.urlencode(params_fb)
    return f"{_FALLBACK_URL}?{qs}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "search" and len(sys.argv) >= 3:
        q = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        results = search(q, limit=n)
        for r in results:
            flac_tag = " [FLAC]" if r.get("has_flac") else ""
            print(f"{r['artist']} - {r['title']}{flac_tag}")
            print(f"  contentId={r['content_id']}  copyrightId={r['copyright_id']}")
    elif cmd == "url" and len(sys.argv) >= 4:
        cid, crid = sys.argv[2], sys.argv[3]
        flag = sys.argv[4] if len(sys.argv) > 4 else "HQ"
        url = get_download_url(cid, crid, tone_flag=flag)
        print(url or "(no URL)")
    else:
        print("Usage: python migu_client.py search <query> [limit]")
        print("       python migu_client.py url <contentId> <copyrightId> [toneFlag]")
        sys.exit(1)

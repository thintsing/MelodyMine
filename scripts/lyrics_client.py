#!/usr/bin/env python3
"""Lyrics client — fetch synced/plain lyrics from LRCLIB (free, no auth), stdlib only."""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

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
    """Fetch lyrics for a specific song.

    Tries direct lookup first, falls back to search.
    Returns dict with synced_lyrics and plain_lyrics, or None on failure.
    """
    if not title:
        return None

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

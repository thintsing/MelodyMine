#!/usr/bin/env python3
"""Bilibili API client — WBI-signed search, no external deps (stdlib only)."""

import hashlib
import json
import re
import sys
import time
import urllib.request
import urllib.error

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
TABS = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13]


def _mixed_key(orig):
    return "".join(orig[i] for i in TABS)[:32]


def _wbi_sign(params, ik, sk):
    mk = _mixed_key(ik + sk)
    params["wts"] = int(time.time())
    q = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(params.items())
    )
    params["w_rid"] = hashlib.md5((q + mk).encode()).hexdigest()
    return params


def _get_wbi_keys(timeout=10):
    """Fetch WBI img_key and sub_key from Bilibili nav API."""
    url = "https://api.bilibili.com/x/web-interface/nav"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://search.bilibili.com")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    ik = data["data"]["wbi_img"]["img_url"].rsplit("/", 1)[1].split(".")[0]
    sk = data["data"]["wbi_img"]["sub_url"].rsplit("/", 1)[1].split(".")[0]
    return ik, sk


def search(query, limit=5, timeout=10):
    """Search Bilibili via WBI-signed API.

    Returns list of dicts: {bvid, aid, title, duration, play, uploader}
    or empty list on failure.
    """
    try:
        ik, sk = _get_wbi_keys(timeout=timeout)
    except Exception as e:
        print(f"  [!] Bilibili wbi_key: {e}")
        return []

    params = _wbi_sign(
        {"keyword": query, "search_type": "video", "page": 1, "page_size": str(limit)},
        ik, sk,
    )
    url = "https://api.bilibili.com/x/web-interface/search/type?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://search.bilibili.com")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [!] Bilibili HTTP {e.code}: {e.reason}")
        return []
    except Exception as e:
        print(f"  [!] Bilibili search: {e}")
        return []

    if data.get("code") != 0:
        print(f"  [!] Bilibili API: {data.get('message', 'unknown')}")
        return []

    results = []
    for item in data.get("data", {}).get("result", [])[:limit]:
        title = re.sub(r"<[^>]+>", "", item.get("title", ""))
        results.append({
            "bvid": item.get("bvid", ""),
            "aid": item.get("aid", 0),
            "title": title,
            "duration": item.get("duration", ""),
            "play": item.get("play", 0),
            "uploader": item.get("author", ""),
        })
    return results


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else ""
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if not q:
        print("Usage: python bili_client.py <query> [limit]")
        sys.exit(1)
    results = search(q, limit=n)
    print(json.dumps(results, ensure_ascii=False))

#!/usr/bin/env python3
"""Bilibili API client — WBI-signed search with retry + fallback, stdlib only."""

import hashlib
import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

from melodymine_common import BILI_UA as UA

TABS = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13]

# Cache WBI keys for 5 minutes to avoid repeated nav API calls
_WBI_CACHE = {"ik": None, "sk": None, "ts": 0}
_WBI_TTL = 300


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
    """Fetch WBI img_key and sub_key from Bilibili nav API (cached)."""
    now = time.time()
    if _WBI_CACHE["ik"] and (now - _WBI_CACHE["ts"]) < _WBI_TTL:
        return _WBI_CACHE["ik"], _WBI_CACHE["sk"]

    url = "https://api.bilibili.com/x/web-interface/nav"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://search.bilibili.com")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    ik = data["data"]["wbi_img"]["img_url"].rsplit("/", 1)[1].split(".")[0]
    sk = data["data"]["wbi_img"]["sub_url"].rsplit("/", 1)[1].split(".")[0]
    _WBI_CACHE["ik"], _WBI_CACHE["sk"], _WBI_CACHE["ts"] = ik, sk, now
    return ik, sk


def _parse_results(data, limit):
    """Extract search results from Bilibili search API response."""
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


def _search_wbi(query, limit, timeout, retries=3):
    """WBI-signed search with retry and backoff.

    Returns (results_list, error_msg) — error_msg is None on success.
    """
    for attempt in range(1, retries + 1):
        try:
            ik, sk = _get_wbi_keys(timeout=timeout)
        except Exception as e:
            if attempt < retries:
                time.sleep(1 * attempt)
                continue
            return [], f"wbi_key: {e}"

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
            if e.code == 412 and attempt < retries:
                time.sleep(1 * attempt)
                continue
            return [], f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            if attempt < retries:
                time.sleep(1 * attempt)
                continue
            return [], str(e)

        if data.get("code") != 0:
            msg = data.get("message", "unknown")
            if attempt < retries and data.get("code") in (-412, -509):
                time.sleep(1 * attempt)
                continue
            return [], f"API {data.get('code')}: {msg}"

        return _parse_results(data, limit), None

    return [], "retry exhausted"


def _search_plain(query, limit, timeout=10):
    """Fallback search via Bilibili's older typehead API (no WBI needed).

    Less reliable but avoids 412 rate-limiting entirely.
    Returns results list or empty list on failure.
    """
    params = urllib.parse.urlencode({
        "term": query, "main_ver": "v3", "highlight": "0",
        "search_type": "video", "page": 1, "page_size": limit,
    })
    url = f"https://s.search.bilibili.com/c/search?{params}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://search.bilibili.com")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    # s.search returns {numResults, page, pagesize, results: [...]}
    raw = data.get("results", []) if isinstance(data, dict) else []
    results = []
    for item in raw[:limit]:
        # s.search doesn't include bvid directly — use aid as fallback
        aid = item.get("aid", 0)
        bvid = item.get("bvid", "")
        results.append({
            "bvid": bvid or f"aid{aid}",
            "aid": aid,
            "title": re.sub(r"<[^>]+>", "", item.get("title", "")),
            "duration": item.get("duration", ""),
            "play": item.get("play", 0),
            "uploader": item.get("author", ""),
        })
    return results


def search(query, limit=5, timeout=10):
    """Search Bilibili for videos matching query.

    Tier 1: WBI-signed API with retry (3 tries, 1s/2s backoff)
    Tier 2: Plain search API (no WBI, avoids 412 rate-limiting)

    Returns list of dicts: {bvid, aid, title, duration, play, uploader}
    or empty list on failure.
    """
    # Tier 1: WBI search with retry
    results, error = _search_wbi(query, limit, timeout)
    if results:
        return results

    if error:
        print(f"  [!] WBI search failed ({error}), trying fallback...", file=sys.stderr)

    # Tier 2: plain search fallback
    results = _search_plain(query, limit, timeout)
    if results:
        return results

    print(f"  [!] Bilibili search failed (both WBI and plain)", file=sys.stderr)
    return []


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else ""
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if not q:
        print("Usage: python bili_client.py <query> [limit]")
        sys.exit(1)
    results = search(q, limit=n)
    print(json.dumps(results, ensure_ascii=False))
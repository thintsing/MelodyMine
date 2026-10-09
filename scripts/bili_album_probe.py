#!/usr/bin/env python3
"""Probe a Bilibili audiobook upload: title, owner, part list, durations, season.

usage: python scripts/bili_album_probe.py <BVid> [out.txt]

The real book title / author / translator usually live in the video `desc`, not
in `title`, so the dump keeps both verbatim for the human deciding the tags.
"""

import json
import sys
import time
import urllib.request

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bilibili.com/",
}


def get(url, tries=6):
    """GET a JSON endpoint, backing off on the intermittent TLS resets."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 + 3 * attempt)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    bvid = sys.argv[1]
    out = open(sys.argv[2] if len(sys.argv) > 2 else "probe.txt", "w", encoding="utf-8")
    v = get("https://api.bilibili.com/x/web-interface/view?bvid=" + bvid)["data"]
    parts = v["pages"]
    total = sum(p["duration"] for p in parts)
    pubdate = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v["pubdate"]))
    owner = v["owner"]
    season = (v.get("ugc_season") or {}).get("title")
    out.write(
        f"bvid: {bvid}\ntitle: {v['title']}\n"
        f"owner: {owner['name']} (mid {owner['mid']})\n"
        f"parts: {len(parts)} total={total}s = {total / 3600:.2f} h\n"
        f"pubdate: {pubdate}\ndesc: {v['desc'][:400]}\npic={v['pic']}\n\n"
    )
    for p in parts:
        out.write(f"P{p['page']:<5} {p['duration']:>6}s  {p['part']}\n")
    out.write(f"\nugc_season={season}\n")
    out.close()
    print(f"parts={len(parts)} h={total / 3600:.2f} owner={owner['name']}")
    print("title=", v["title"])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Find a book cover on Douban and download the large variant.

usage:
    python scripts/douban_cover.py --out C:\\tmp\\cover "人类简史：从动物到上帝" [...]

`subject_suggest` only returns an id (its `pic`/`img` fields are usually null),
so each candidate's subject page is fetched to read the `mainpic` <img> and the
`info` block. The infobox (作者/译者/出版社/出版年/ISBN) is what tells the
editions apart — print it and pick before downloading. The `/s/` name in the
thumbnail url becomes `/l/` for the full-size image.

img9.doubanio.com answers a ~1 KB JS interstitial, so the hosts are tried in
order and the byte size plus the JPEG SOF dimensions are reported as the check.
"""

import argparse
import json
import os
import re
import struct
import sys
import urllib.parse
import urllib.request

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "Chrome/124 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
    # Without the referer the image hosts answer the JS interstitial instead.
    "Referer": "https://book.douban.com/",
}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=45).read()


def jpeg_dims(b):
    """(width, height) from the first SOFn marker, or None if not a JPEG."""
    if b[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(b) - 9:
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return (w, h)
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    return None


def info_of(sid):
    """(mainpic url, infobox text) for a subject id."""
    html = get(f"https://book.douban.com/subject/{sid}/").decode("utf-8", "replace")
    pic = re.search(r'id="mainpic"\s*>\s*<a[^>]*>\s*<img src="([^"]+)"', html)
    start = html.find('id="info"')
    seg = html[start:start + 1500] if start >= 0 else ""
    info = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg)).strip()
    return (pic.group(1) if pic else ""), info[:220]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".", help="directory the images are written to")
    ap.add_argument("queries", nargs="+")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    for q in args.queries:
        print(f"=== {q}")
        sug = json.loads(get(
            "https://book.douban.com/j/subject_suggest?q=" + urllib.parse.quote(q)
        ).decode("utf-8"))
        for it in sug[:6]:
            sid = it.get("id")
            try:
                pic, info = info_of(sid)
            except Exception as exc:
                print(f"  {sid}  {it.get('title')} | {it.get('author_name')}"
                      f"  (page err {exc})")
                continue
            print(f"  {sid}  {it.get('title')} | {it.get('author_name')}")
            print(f"        {info}")
            m = re.search(r"/public/(s\d+)\.jpg", pic)
            if not m:
                continue
            base = m.group(1)
            for host in ("img3", "img2", "img9"):
                url = f"https://{host}.doubanio.com/view/subject/l/public/{base}.jpg"
                try:
                    b = get(url)
                except Exception as exc:
                    print(f"        {host}/l/{base} ERR {type(exc).__name__}")
                    continue
                fn = os.path.join(args.out, f"db_{base}_{host}_l.jpg")
                with open(fn, "wb") as fh:
                    fh.write(b)
                print(f"        {host}/l/{base} -> {len(b)} B {jpeg_dims(b)} -> {fn}")
                if len(b) > 5000:
                    break


if __name__ == "__main__":
    main()

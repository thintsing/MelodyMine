#!/usr/bin/env python3
"""Download every part of a multi-P Bilibili audiobook as tagged .m4a files.

usage:
    python scripts/bili_album_dl.py --bvid BV1nFcLzaEGb --out C:\\tmp\\b9 \\
        --album "人类简史：从动物到上帝" --artist "尤瓦尔·赫拉利" \\
        --strip-regex "^完整版："

Login-free playurl route (yt-dlp gets 412 on these uploads); the DASH audio is
remuxed, not re-encoded, so a 128 kbps upload stays a 128 kbps upload. Files are
named NNNN-<part title>.m4a, which is how this Audiobookshelf library is laid
out, and book.json records the API metadata plus the naming options so
bili_album_verify.py can re-derive the expected names independently.

Note on Windows: a Chinese artist/album argument does not survive cmd's argv
encoding. Drive this from a small UTF-8 .py that sets sys.argv and execs it.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

from melodymine_common import BILI_UA as UA
from melodymine_common import find_ffmpeg

FFMPEG = find_ffmpeg() or find_ffmpeg(sys.executable)
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def http_json(url, referer):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", referer)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def view(bvid):
    d = http_json(
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
        "https://www.bilibili.com/",
    )
    if d.get("code") != 0:
        raise RuntimeError(f"view: {d.get('message')}")
    return d["data"]


def audio_url(bvid, cid):
    url = (f"https://api.bilibili.com/x/player/playurl?bvid={bvid}"
           f"&cid={cid}&fnval=16&fourk=1")
    d = http_json(url, f"https://www.bilibili.com/video/{bvid}")
    if d.get("code") != 0:
        raise RuntimeError(f"playurl: {d.get('message')}")
    audio = ((d.get("data") or {}).get("dash") or {}).get("audio") or []
    if not audio:
        raise RuntimeError("no audio stream")
    best = max(audio, key=lambda a: a.get("bandwidth", 0))
    return best["baseUrl"]


def safe(name):
    name = ILLEGAL.sub(" ", name).strip().strip(".")
    return re.sub(r"\s+", " ", name)[:120]


def clean_part(name):
    """Drop the uploaders' broadcast date prefix: 20220621 / 2022-07-20."""
    name = re.sub(r"^\s*20\d{2}\s*-?\s*\d{2}\s*-?\s*\d{2}[\s\-_、.]*", "", name)
    return name.strip()


def part_title(part, options):
    """Apply the recorded naming options to an API part title."""
    if options.get("clean"):
        part = clean_part(part)
    if options.get("strip_seq"):
        part = re.sub(r"^\s*\d{3}(?=\D)", "", part)
    if options.get("strip_regex"):
        part = re.sub(options["strip_regex"], "", part)
    return safe(part)


def download(url, referer, dest):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", referer)
    got = 0
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
    return got


def ffprobe_duration(path):
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr.decode("utf-8", "replace"))
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def remux(src, dest, meta):
    # -map_metadata -1 before the -metadata adds: ffmpeg otherwise inherits the
    # source container's global tags, and Bilibili's include a junk `desc`
    # synopsis ("Packed by Bilibili XCoder") that Audiobookshelf caches as the
    # book description and will not drop afterwards.
    def build(codec):
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
               "-map_metadata", "-1", "-vn"]
        for k, v in meta.items():
            cmd += ["-metadata", f"{k}={v}"]
        cmd += codec + [dest]
        return cmd

    for codec, how in ((["-c:a", "copy"], "copy"), (["-c:a", "aac", "-b:a", "128k"], "reencode")):
        p = subprocess.run(build(codec), capture_output=True)
        if p.returncode == 0 and os.path.getsize(dest) > 1000:
            return how
        if how == "copy":
            continue
        raise RuntimeError("ffmpeg: " + p.stderr.decode("utf-8", "replace")[-300:])


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvid", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default="", help="comma list, e.g. 1,23 (default: all)")
    ap.add_argument("--clean", action="store_true",
                    help="strip broadcast-date prefixes from part titles")
    ap.add_argument("--strip-seq", action="store_true",
                    help="strip leading 3-digit chapter numbers from part titles")
    ap.add_argument("--strip-regex", default="",
                    help="regex removed from part titles (stored in book.json)")
    ap.add_argument("--album", default="", help="album tag override (default: video title)")
    ap.add_argument("--artist", default="", help="artist tag override (default: uploader)")
    ap.add_argument("--comment", default="",
                    help="comment tag; leave empty so Audiobookshelf caches no junk description")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--manifest", default="")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    info = view(args.bvid)
    book = args.album or safe(info["title"])
    artist = args.artist or safe((info.get("owner") or {}).get("name", ""))
    pages = info.get("pages") or []
    options = {"clean": args.clean, "strip_seq": args.strip_seq,
               "strip_regex": args.strip_regex}
    print(f"BOOK={book} parts={len(pages)} artist={artist} "
          f"total={int(info.get('duration') or 0)}s")
    with open(os.path.join(args.out, "book.json"), "w", encoding="utf-8") as fh:
        json.dump({"bvid": args.bvid, "book": book, "artist": artist, "options": options,
                   "pages": pages}, fh, ensure_ascii=False)

    wanted = ([int(x) for x in args.pages.split(",")] if args.pages
              else [p["page"] for p in pages])
    man = open(args.manifest or os.path.join(args.out, "manifest.tsv"), "a",
               encoding="utf-8", errors="surrogateescape")

    for page in wanted:
        p = next((x for x in pages if x["page"] == page), None)
        if not p:
            print(f"skip unknown page {page}")
            continue
        part = part_title(p["part"], options)
        fname = f"{page:04d}-{part}.m4a"
        dest = os.path.join(args.out, fname)
        api_dur = int(p.get("duration") or 0)
        if os.path.exists(dest) and abs((ffprobe_duration(dest) or 0) - api_dur) <= 4:
            print(f"have {fname}")
            continue
        try:
            url = None
            for attempt in range(1, 4):
                try:
                    url = audio_url(args.bvid, p["cid"])
                    break
                except Exception as exc:
                    print(f"  resolve {page} failed ({exc}), retry")
                    time.sleep(2 * attempt)
            if not url:
                raise RuntimeError("resolve exhausted")
            raw = dest + ".m4s"
            nbytes = download(url, f"https://www.bilibili.com/video/{args.bvid}", raw)
            meta = {"title": part, "album": book, "artist": artist,
                    "track": str(page), "genre": "Audiobook"}
            if args.comment:
                meta["comment"] = args.comment
            how = remux(raw, dest, meta)
            os.remove(raw)
            local = ffprobe_duration(dest) or 0
            ok = abs(local - api_dur) <= 4
            status = "OK" if ok else f"DUR_MISMATCH {local:.1f}"
            man.write(f"{page}\t{fname}\t{nbytes}\t{os.path.getsize(dest)}\t{api_dur}"
                      f"\t{how}\t{status}\n")
            man.flush()
            print(f"{'[ok]' if ok else '[DUR]'} {fname} {nbytes}->"
                  f"{os.path.getsize(dest)} bytes {how} {local:.0f}s/{api_dur}s")
            if not ok:
                print("   duration mismatch, keeping file for review")
        except Exception as exc:
            man.write(f"{page}\t{fname}\t0\t0\t{api_dur}\tFAILED\t{exc}\n")
            man.flush()
            print(f"[FAIL] page {page} {fname}: {exc}")
        time.sleep(args.delay)
    man.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Independently verify a downloaded Bilibili audiobook folder.

usage: python scripts/bili_album_verify.py <outdir>

Recomputes the expected file name and tags from the API metadata stored in
book.json (not from what the downloader wrote), checks every file on disk
against it, and emits md5.txt + verify.txt for the server transfer.
"""

import argparse
import hashlib
import json
import os
import re
import sys

from mutagen.mp4 import MP4

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_part(name):
    name = re.sub(r"^\s*20\d{2}\s*-?\s*\d{2}\s*-?\s*\d{2}[\s\-_、.]*", "", name)
    return name.strip()


def safe(name):
    name = ILLEGAL.sub(" ", name).strip().strip(".")
    return re.sub(r"\s+", " ", name)[:120]


# The naming rules are duplicated from bili_album_dl.py on purpose: importing
# the downloader would make "independent check" mean nothing, and tests/
# test_bili_album.py pins the two implementations together.
def part_title(part, options):
    if options.get("clean"):
        part = clean_part(part)
    if options.get("strip_seq"):
        part = re.sub(r"^\s*\d{3}(?=\D)", "", part)
    if options.get("strip_regex"):
        part = re.sub(options["strip_regex"], "", part)
    return safe(part)


def tag_get(tags, key):
    return (tags.get(key) or [None])[0] if key in tags else None


def tag_dec(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    args = ap.parse_args()
    out = args.outdir

    book_meta = json.load(open(os.path.join(out, "book.json"), encoding="utf-8"))
    album = book_meta["book"]
    artist = book_meta["artist"]
    pages = book_meta["pages"]
    options = book_meta["options"]

    bad = []
    total_bytes = 0
    total_dur = 0
    md5s = open(os.path.join(out, "md5.txt"), "w", encoding="utf-8", newline="\n")
    seen_tracks = set()
    for p in pages:
        part = part_title(p["part"], options)
        fname = f"{p['page']:04d}-{part}.m4a"
        path = os.path.join(out, fname)
        if not os.path.exists(path):
            bad.append(f"MISSING {fname}")
            continue
        size = os.path.getsize(path)
        total_bytes += size
        try:
            a = MP4(path)
        except Exception as exc:
            bad.append(f"UNREADABLE {fname} {exc!r}")
            continue
        tags = a.tags or {}
        for key, want in (("\xa9alb", album), ("\xa9ART", artist),
                          ("\xa9nam", part), ("\xa9gen", "Audiobook")):
            got = tag_dec(tag_get(tags, key))
            if got != want:
                bad.append(f"TAG {fname} {key}={got!r} want={want!r}")
        trkn = tag_get(tags, "trkn")
        if not trkn or trkn[0] != p["page"]:
            bad.append(f"TAG {fname} trkn={trkn!r} want={p['page']}")
        else:
            seen_tracks.add(p["page"])
        # A comment or an inherited `desc` atom becomes the book synopsis in
        # Audiobookshelf, and that cache cannot be revoked from the file side.
        for key, label in (("\xa9cmt", "COMMENT"), ("desc", "DESC")):
            if key in tags:
                bad.append(f"{label} {fname}={tag_dec(tags[key][0])!r}")
        dur = a.info.length
        total_dur += dur
        if abs(dur - p["duration"]) > 4:
            bad.append(f"DUR {fname} {dur:.0f}s vs api {p['duration']}s")
        if size < 500000:
            bad.append(f"TINY {fname} {size}")
        h = hashlib.md5()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        md5s.write(f"{h.hexdigest()}  {fname}\n")
    md5s.close()

    gaps = sorted(set(range(1, len(pages) + 1)) - seen_tracks)
    rep = open(os.path.join(out, "verify.txt"), "w", encoding="utf-8")
    rep.write(f"album={album} artist={artist}\n")
    rep.write(f"pages={len(pages)} ok={len(seen_tracks)} track_gaps={gaps}\n")
    rep.write(f"bytes={total_bytes} ({total_bytes / 1e9:.2f} GB) "
              f"audio={total_dur / 3600.0:.2f} h\n")
    rep.write(f"problems={len(bad)}\n")
    for line in bad[:60]:
        rep.write("  " + line + "\n")
    rep.close()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"pages={len(pages)} ok={len(seen_tracks)} gaps={gaps} problems={len(bad)} "
          f"bytes={total_bytes / 1e9:.2f}GB hours={total_dur / 3600.0:.2f}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Cover art downloader — download image from URL to temp file, stdlib only."""

import os
import sys
import tempfile
import urllib.request
import urllib.error


def download(url, timeout=10):
    """Download a cover image from URL to a temporary file.

    Returns the local file path, or None on failure.
    """
    if not url:
        return None
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        data = resp.read()
        ct = resp.headers.get("content-type", "")
        ext = ".png" if "png" in ct else ".jpg"
        tmp = os.path.join(tempfile.gettempdir(), f"cover_{os.getpid()}{ext}")
        with open(tmp, "wb") as f:
            f.write(data)
        return tmp
    except Exception:
        return None


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    path = download(url)
    if path:
        print(path)
    else:
        print("")
        sys.exit(1)

#!/usr/bin/env python3
"""MelodyMine Spotify helper - Advanced spotDL operations.

Orchestrates the Spotify -> YouTube -> ffmpeg pipeline with:
  - Auto Python/spotdl path detection (shared with music_helper via melodymine_common)
  - SOCKS5 proxy support via --yt-dlp-args (bypasses spotDL's HTTP-only proxy check)
  - Spotify search to resolve Chinese song names to URLs
  - Real-time streaming output
  - Post-download verification (file size check)
  - Intelligent error diagnosis with retry suggestions

Proxy handling:
  spotDL only accepts HTTP/HTTPS proxies in --proxy flag.
  For SOCKS5 proxies, we pass the proxy via --yt-dlp-args which goes directly
  to yt-dlp (which supports SOCKS5). For Spotify API calls, we set the
  ALL_PROXY environment variable which Python's requests library respects
  via PySocks.

Usage:
    python spotify_helper.py check                                    # Check dependencies
    python spotify_helper.py search "周杰伦 稻香"                      # Search Spotify for URL
    python spotify_helper.py download "URL_or_query" [--proxy ...]    # Download music
    python spotify_helper.py download "URL" --format mp3              # Pass --proxy if needed
    python spotify_helper.py sync "URL" --save-file x.spotdl          # Sync playlist
    python spotify_helper.py save "query"                              # Save metadata only
    python spotify_helper.py url "query"                               # Get YouTube URL
    python spotify_helper.py meta "/path/song.mp3" [--query "Artist Song"]  # Update metadata
"""

import argparse
import json
import os
import subprocess
import sys

from melodymine_common import (
    DEFAULT_OUTPUT,
    build_spotdl_proxy_args,
    check_module,
    derive_query_from_filename,
    detect_python_with,
    find_ffmpeg,
    find_python,
    is_socks_proxy,
    make_subprocess_env,
    pip_install,
    proxy_to_env,
    run_streaming,
)

# Metadata enhancement is shared with the main helper.
from music_helper import enhance_metadata


# --- Configuration ---

# User must provide a proxy via --proxy; no implicit default.
DEFAULT_PROXY = None

# Packages installed when bootstrapping spotDL.
# spotdl is hard-capped to major 4 — MelodyMine imports spotdl's internal
# SpotifyClient API (see spotify_search), which breaks across major versions.
# Keep this in sync with requirements.txt and DEP_COMPAT in melodymine_common.py.
SPOTDL_PACKAGES = ["spotdl>=4.2.0,<5.0.0", "PySocks"]


def _get_python():
    """Get a working python with spotdl, auto-install if missing."""
    py, _ = find_python("spotdl", SPOTDL_PACKAGES)
    if not py:
        print("ERROR: spotdl installation failed.")
        print("       Try manually: pip install spotdl PySocks")
        sys.exit(1)
    return py


# --- Spotify Search ---
def spotify_search(query, proxy=None):
    """Search Spotify for a song and return matching track URLs.

    Returns a list of dicts: [{name, artist, album, url, duration}, ...]
    """
    python_exe = _get_python()

    # Build environment with proxy
    env = make_subprocess_env()
    if proxy:
        env.update(proxy_to_env(proxy))

    search_script = r"""
import sys, json
try:
    from spotdl.utils.spotify import SpotifyClient
    SpotifyClient.init()
    client = SpotifyClient.getInstance()
    query = sys.argv[1]
    results = client.search(query, type='track')
    tracks = results.get('tracks', {}).get('items', [])
    output = []
    for t in tracks[:5]:
        output.append({
            'name': t['name'],
            'artist': ', '.join([a['name'] for a in t['artists']]),
            'album': t['album']['name'],
            'url': t['external_urls']['spotify'],
            'duration': t['duration_ms'] // 1000,
            'id': t['id']
        })
    print(json.dumps(output, ensure_ascii=False))
except Exception as e:
    print(json.dumps({'error': str(e)}, ensure_ascii=False))
    sys.exit(1)
"""

    print(f"[SEARCH] Searching Spotify for: {query}")
    result = subprocess.run(
        [python_exe, "-c", search_script, query],
        capture_output=True, text=True, timeout=30,
        env=env, encoding="utf-8", errors="replace",
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        print(f"[SEARCH] Direct API search failed: {stderr[:200] or 'unknown error'}")
        return []

    try:
        data = json.loads(result.stdout.strip())
        if isinstance(data, dict) and "error" in data:
            print(f"[SEARCH] Error: {data['error']}")
            return []
        return data
    except json.JSONDecodeError:
        print(f"[SEARCH] Invalid JSON response from Spotify API")
        return []


# --- Download execution ---
def run_spotdl(operation, queries, extra_args):
    """Build and run `python -m spotdl <operation> [queries] [options]`."""
    python_exe = _get_python()

    # Auto-set output directory
    output_dir = extra_args.get("output") or DEFAULT_OUTPUT
    os.makedirs(output_dir, exist_ok=True)

    # Auto-set proxy only when a default is configured (avoids printing "None").
    proxy = extra_args.get("proxy")
    if not proxy and operation in ("download", "sync", "url", "save") and DEFAULT_PROXY:
        proxy = DEFAULT_PROXY
        print(f"[PROXY] Auto-applying default proxy: {proxy}")

    cmd = [python_exe, "-m", "spotdl", operation]
    for q in queries:
        cmd.append(q)
    cmd.extend(["--output", output_dir])

    # Single-value flags
    flag_map = {
        "format": "--format",
        "bitrate": "--bitrate",
        "threads": "--threads",
        "cookie_file": "--cookie-file",
        "overwrite": "--overwrite",
        "archive": "--archive",
        "save_file": "--save-file",
        "m3u": "--m3u",
        "ffmpeg": "--ffmpeg",
        "client_id": "--client-id",
        "client_secret": "--client-secret",
    }
    for key, flag in flag_map.items():
        val = extra_args.get(key)
        if val is not None:
            cmd.extend([flag, str(val)])

    # PROXY HANDLING — shared with music_helper via build_spotdl_proxy_args.
    # spotDL only accepts HTTP/HTTPS in --proxy flag; SOCKS5 must go via --yt-dlp-args.
    if proxy:
        cmd.extend(build_spotdl_proxy_args(proxy))
        if is_socks_proxy(proxy):
            print(f"[PROXY] SOCKS5 proxy applied via --yt-dlp-args: {proxy}")
        else:
            print(f"[PROXY] HTTP proxy applied via --proxy: {proxy}")

    # Multi-value flags
    if extra_args.get("audio"):
        cmd.extend(["--audio"] + extra_args["audio"])
    if extra_args.get("lyrics"):
        cmd.extend(["--lyrics"] + extra_args["lyrics"])

    # Boolean flags
    bool_flags = {
        "generate_lrc": "--generate-lrc",
        "skip_explicit": "--skip-explicit",
        "print_errors": "--print-errors",
        "user_auth": "--user-auth",
        "use_official_api": "--use-official-api",
        "preload": "--preload",
        "sponsor_block": "--sponsor-block",
    }
    for key, flag in bool_flags.items():
        if extra_args.get(key):
            cmd.append(flag)

    # Set environment variables for proxy (for Spotify API calls)
    env = make_subprocess_env()
    if proxy:
        env.update(proxy_to_env(proxy))

    print(f"\n[RUN] {' '.join(cmd)}")
    if proxy:
        print(f"[ENV] Proxy env vars set: {proxy_to_env(proxy)}")
    print("=" * 60)

    exit_code = run_streaming(cmd, env=env)
    print("=" * 60)

    if exit_code != 0:
        diagnose_error(exit_code, output_dir)
        sys.exit(1)

    # Post-download verification
    verify_downloads(output_dir)


def diagnose_error(exit_code, output_dir):
    """Print common error patterns and suggest fixes."""
    print(f"\n[ERROR] spotdl exited with code {exit_code}")
    print("\nDiagnosis and retry suggestions:")
    print("  1. SOCKS5 proxy not working -> check proxy is running, try different port")
    print("  2. Chinese song not found -> use helper 'search' command to get Spotify URL first")
    print("  3. Spotify API KeyError -> add --use-official-api flag")
    print("  4. FFmpeg missing -> run: spotdl --download-ffmpeg")
    print("  5. Rate limited -> reduce threads: --threads 2")
    print("  6. File permission -> change --output to writable directory")


def verify_downloads(output_dir):
    """Check output directory for downloaded files."""
    print(f"\n[VERIFY] Checking: {output_dir}")

    audio_exts = (".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav")
    found_files = []
    bad_files = []

    if os.path.isdir(output_dir):
        for f in sorted(os.listdir(output_dir)):
            if f.endswith(audio_exts):
                filepath = os.path.join(output_dir, f)
                size_kb = os.path.getsize(filepath) / 1024
                if size_kb > 100:
                    found_files.append((filepath, size_kb))
                else:
                    bad_files.append((filepath, size_kb))

    if found_files:
        print(f"[OK] {len(found_files)} file(s) downloaded:")
        for path, size in found_files:
            size_str = f"{size:.0f} KB" if size < 1024 else f"{size/1024:.1f} MB"
            print(f"  {path}  ({size_str})")
    else:
        print("[WARN] No audio files found in output directory")

    if bad_files:
        print(f"[WARN] {len(bad_files)} file(s) suspicious (<100KB):")
        for path, size in bad_files:
            print(f"  {path}  ({size:.0f} KB) - possibly incomplete")


# --- Check command ---
def check_install():
    """Check if spotdl, ffmpeg, and PySocks are available (read-only, no install)."""
    python_exe, spotdl_ver = detect_python_with("spotdl")
    info = {
        "spotdl_installed": python_exe is not None,
        "ffmpeg": False,
        "pysocks": False,
        "default_proxy": DEFAULT_PROXY,
    }

    if python_exe:
        info["python_path"] = python_exe
        if spotdl_ver:
            info["spotdl_version"] = spotdl_ver

        # Check PySocks
        if check_module(python_exe, "socks"):
            info["pysocks"] = True

        # Use shared ffmpeg detection (system PATH + imageio-ffmpeg fallback)
        ff = find_ffmpeg(python_exe)
        if ff:
            info["ffmpeg"] = True
            try:
                result = subprocess.run(
                    [ff, "-version"], capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode == 0:
                    info["ffmpeg_version"] = result.stdout.strip().split("\n")[0]
            except Exception:
                pass

    print(json.dumps(info, indent=2, ensure_ascii=False))

    ready = info["spotdl_installed"] and info["ffmpeg"]
    if ready:
        print("\nAll dependencies ready.")
        if not info["pysocks"]:
            print("WARNING: PySocks not installed - SOCKS5 proxy for Spotify API may fail.")
            print("Install: pip install PySocks")
        print("SOCKS5 proxy is applied via --yt-dlp-args to yt-dlp.")
        print("Spotify API calls use ALL_PROXY environment variable.")
    else:
        print("\nMissing dependencies. Auto-install will run on first download.")


# --- Main ---
def main():
    parser = argparse.ArgumentParser(
        description="MelodyMine Spotify helper - download Spotify music via YouTube + ffmpeg",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("operation",
        choices=["check", "search", "download", "sync", "save", "meta", "url"],
        help="Operation: check deps, search Spotify, download, sync, save, meta, url")

    parser.add_argument("queries", nargs="*",
        help="Search queries or Spotify URLs")

    parser.add_argument("--proxy",
        help=f"Proxy URL, supports socks5:// and http:// (default: {DEFAULT_PROXY})")
    parser.add_argument("--format",
        choices=["mp3", "flac", "m4a", "ogg", "opus", "wav"],
        help="Output format (default: mp3)")
    parser.add_argument("--bitrate",
        help="Output bitrate (e.g. 320k, disable)")
    parser.add_argument("--output",
        help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--threads", type=int,
        help="Parallel download threads")
    parser.add_argument("--cookie-file",
        help="YouTube Music cookies file path")
    parser.add_argument("--overwrite",
        choices=["skip", "metadata", "force"],
        help="How to handle existing files")
    parser.add_argument("--archive",
        help="Archive file to track downloads")
    parser.add_argument("--save-file",
        help=".spotdl save file path")
    parser.add_argument("--m3u",
        help="Generate M3U playlist")
    parser.add_argument("--audio", nargs="+",
        help="Audio providers fallback chain (e.g. youtube-music youtube)")
    parser.add_argument("--lyrics", nargs="+",
        help="Lyrics providers (e.g. genius musixmatch synced)")
    parser.add_argument("--generate-lrc", action="store_true")
    parser.add_argument("--skip-explicit", action="store_true")
    parser.add_argument("--print-errors", action="store_true")
    parser.add_argument("--user-auth", action="store_true")
    parser.add_argument("--use-official-api", action="store_true",
        help="Force official Spotify API (fixes SpotipyFree bugs)")
    parser.add_argument("--preload", action="store_true")
    parser.add_argument("--sponsor-block", action="store_true")
    parser.add_argument("--ffmpeg",
        help="Path to ffmpeg executable")
    parser.add_argument("--query",
        help="Search query for metadata lookup (used with 'meta'; defaults to filename)")

    args = parser.parse_args()

    if args.operation == "check":
        check_install()
        return

    if args.operation == "search":
        if not args.queries:
            print("Error: search requires a query")
            sys.exit(1)
        proxy = args.proxy or DEFAULT_PROXY
        results = spotify_search(args.queries[0], proxy=proxy)
        if results:
            print("\n[RESULTS]")
            for i, r in enumerate(results, 1):
                print(f"  {i}. {r['artist']} - {r['name']}  ({r['album']})")
                print(f"     URL: {r['url']}")
                print(f"     Duration: {r['duration']}s")
            print(f"\nBest match URL: {results[0]['url']}")
        else:
            print("[SEARCH] No results found")
        return

    if args.operation == "meta":
        if not args.queries:
            print("Error: meta requires a file path")
            sys.exit(1)
        filepath = args.queries[0]
        if not os.path.isfile(filepath):
            print(f"ERROR: File not found: {filepath}")
            sys.exit(1)

        query = args.query
        if not query:
            query = derive_query_from_filename(filepath)

        output_dir = os.path.dirname(filepath) or "."
        python = _get_python()
        print("=" * 60)
        print("  MelodyMine Spotify helper — Update metadata")
        print("=" * 60)
        print(f"  File  : {filepath}")
        print(f"  Query : {query}")
        print()
        enhance_metadata(query, "", output_dir, embed_thumbnail=True, filepath=filepath)
        print("\n[OK] Metadata update complete!")
        return

    if not args.queries:
        print("Error: No queries provided for operation", args.operation)
        sys.exit(1)

    # Build extra_args dict
    extra = {}
    simple_keys = [
        "format", "bitrate", "output", "threads", "cookie_file",
        "overwrite", "archive", "save_file", "m3u", "ffmpeg",
    ]
    for k in simple_keys:
        v = getattr(args, k, None)
        if v is not None:
            extra[k] = v

    if args.proxy:
        extra["proxy"] = args.proxy

    if args.audio:
        extra["audio"] = args.audio
    if args.lyrics:
        extra["lyrics"] = args.lyrics

    for k in ["generate_lrc", "skip_explicit", "print_errors",
              "user_auth", "use_official_api", "preload", "sponsor_block"]:
        v = getattr(args, k, None)
        if v:
            extra[k] = v

    run_spotdl(args.operation, args.queries, extra)


if __name__ == "__main__":
    main()

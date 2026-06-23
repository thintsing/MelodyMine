#!/usr/bin/env python3
"""MelodyMine Spotify helper - Advanced spotDL operations.

Orchestrates the Spotify -> YouTube -> ffmpeg pipeline with:
  - Auto Python/spotdl path detection
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
    python spotify_helper.py download "URL" --format mp3              # Auto-applies default proxy
    python spotify_helper.py sync "URL" --save-file x.spotdl          # Sync playlist
    python spotify_helper.py save "query"                              # Save metadata only
    python spotify_helper.py url "query"                               # Get YouTube URL
    python spotify_helper.py meta "/path/song.mp3"                     # Update metadata
"""

import argparse
import json
import os
import shutil
import subprocess
import sys


# --- Configuration ---
HOME = os.path.expanduser("~")
IS_WIN = sys.platform == "win32"
DEFAULT_PROXY = None  # User must provide via --proxy


def _get_default_output():
    """Pick a sensible default output directory that exists on this platform."""
    for candidate in [
        os.path.join(HOME, "Music", "MelodyMine"),
        os.path.join(HOME, "Downloads", "music"),
        os.path.join(HOME, "music"),
        os.path.join(HOME, "MelodyMine-downloads"),
    ]:
        if os.path.isdir(os.path.dirname(candidate)):
            return candidate
    return os.path.join(HOME, "Music", "MelodyMine")


DEFAULT_OUTPUT = _get_default_output()

# Dedicated venv for spotDL (created on demand when system Python is externally managed)
_SPOTDL_VENV_DIR = os.path.join(HOME, ".cache", "melodymine-spotdl-venv")


def _is_socks_proxy(proxy_url):
    """Check if proxy URL is a SOCKS proxy."""
    return proxy_url and proxy_url.startswith(("socks5://", "socks5h://", "socks4://"))


def _proxy_to_env(proxy_url):
    """Convert proxy URL to environment variable format for Python requests."""
    if _is_socks_proxy(proxy_url):
        return {"ALL_PROXY": proxy_url}
    else:
        return {"HTTP_PROXY": proxy_url, "HTTPS_PROXY": proxy_url}


def _collect_python_candidates():
    """Build an exhaustive list of Python interpreters to try."""
    candidates = []

    # 1. Dedicated venv (if it exists)
    if IS_WIN:
        candidates.append(os.path.join(_SPOTDL_VENV_DIR, "Scripts", "python.exe"))
    else:
        candidates.append(os.path.join(_SPOTDL_VENV_DIR, "bin", "python"))

    # 2. Current interpreter
    candidates.append(sys.executable)

    # 3. python3 / python / py on PATH
    for name in ["python3", "python", "py"]:
        path = shutil.which(name)
        if path:
            candidates.append(path)

    # 4. WorkBuddy venv (any version)
    wb_venv = os.path.join(HOME, ".workbuddy", "binaries", "python", "envs", "default")
    if IS_WIN:
        candidates.append(os.path.join(wb_venv, "Scripts", "python.exe"))
    else:
        candidates.append(os.path.join(wb_venv, "bin", "python"))

    # 5. Common platform paths
    if not IS_WIN:
        for path in ["/usr/bin/python3", "/usr/local/bin/python3",
                      "/opt/homebrew/bin/python3"]:
            candidates.append(path)
        # pyenv
        pyenv_root = os.environ.get("PYENV_ROOT", os.path.join(HOME, ".pyenv"))
        candidates.append(os.path.join(pyenv_root, "shims", "python3"))
        # conda
        for conda_base in [os.path.join(HOME, "miniconda3"),
                           os.path.join(HOME, "anaconda3"),
                           "/opt/conda"]:
            candidates.append(os.path.join(conda_base, "bin", "python3"))
        # pip --user
        candidates.append(os.path.join(HOME, ".local", "bin", "python3"))

    if IS_WIN:
        local_app = os.environ.get("LOCALAPPDATA", "")
        for ver in ["3.13", "3.12", "3.11", "3.10"]:
            v = ver.replace(".", "")
            candidates.append(f"{local_app}\\Programs\\Python\\Python{v}\\python.exe")

    # Deduplicate
    seen = set()
    unique = []
    for c in candidates:
        rp = os.path.realpath(c) if c else ""
        if c and rp not in seen:
            seen.add(rp)
            unique.append(c)
    return unique


def _pip_install(python, packages, timeout=180):
    """Install pip packages. Handles PEP 668 (externally-managed-environment)."""
    if not packages:
        return True
    base_cmd = [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    try:
        result = subprocess.run(
            base_cmd + packages,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return True
        if "externally-managed-environment" not in (result.stderr or "").lower():
            return False
    except Exception:
        return False
    # PEP 668: try --user
    try:
        result = subprocess.run(
            base_cmd + ["--user"] + packages,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0
    except Exception:
        return False


def _find_python_with_spotdl():
    """Find a Python that can import spotdl."""
    for py in _collect_python_candidates():
        if not py or not os.path.isfile(py):
            continue
        try:
            result = subprocess.run(
                [py, "-c", "import spotdl; print(spotdl.__version__)"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                return py
        except Exception:
            continue
    return None


def _ensure_spotdl_installed():
    """Install spotdl + PySocks into a Python environment.
    Handles PEP 668 by creating a venv if system Python is externally-managed.
    """
    # Try installing into existing Python candidates first
    for py in _collect_python_candidates():
        if not py or not os.path.isfile(py):
            continue
        # Check pip works
        pip_check = subprocess.run(
            [py, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if pip_check.returncode != 0:
            continue

        print(f"[INSTALL] Installing spotdl + PySocks into {py}...")
        _pip_install(py, ["spotdl", "PySocks"])

        # Verify
        try:
            result = subprocess.run(
                [py, "-c", "import spotdl; print('ok')"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                print(f"[INSTALL] spotdl ready, python: {py}")
                return py
        except Exception:
            continue

    # Fallback: create a dedicated venv
    print("[INSTALL] System Python is externally-managed, creating isolated venv...")
    venv_py = os.path.join(
        _SPOTDL_VENV_DIR,
        "Scripts", "python.exe" if IS_WIN else "bin", "python",
    )
    if not os.path.isfile(venv_py):
        # Find any Python to create the venv
        for py in _collect_python_candidates():
            if not py or not os.path.isfile(py):
                continue
            result = subprocess.run(
                [py, "-m", "venv", _SPOTDL_VENV_DIR],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                break
        else:
            print("ERROR: Could not create venv. Install Python 3.10+ first.")
            sys.exit(1)

    _pip_install(venv_py, ["spotdl", "PySocks"])
    try:
        result = subprocess.run(
            [venv_py, "-c", "import spotdl; print('ok')"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            print(f"[INSTALL] spotdl ready (venv), python: {venv_py}")
            return venv_py
    except Exception:
        pass

    print("ERROR: spotdl installation failed")
    sys.exit(1)


def _get_python():
    """Get a working python with spotdl, auto-install if missing."""
    py = _find_python_with_spotdl()
    if py is None:
        py = _ensure_spotdl_installed()
    return py


# --- Spotify Search ---
def spotify_search(query, proxy=None):
    """Search Spotify for a song and return matching track URLs.

    Returns a list of dicts: [{name, artist, album, url, duration}, ...]
    """
    python_exe = _get_python()

    # Build environment with proxy
    env = os.environ.copy()
    if proxy:
        env.update(_proxy_to_env(proxy))

    search_script = r"""
import sys, json
try:
    from spotdl.utils.spotify import SpotifyClient
    SpotifyClient.init()
    client = SpotifyClient.getInstance()
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
        [python_exe, "-c", search_script],
        capture_output=True, text=True, timeout=30,
        env=env,
    )

    if result.returncode != 0:
        print(f"[SEARCH] Direct API search failed, using fallback...")
        return [{"name": query, "artist": "", "album": "",
                 "url": query, "duration": 0, "id": ""}]

    try:
        data = json.loads(result.stdout.strip())
        if isinstance(data, dict) and "error" in data:
            print(f"[SEARCH] Error: {data['error']}")
            return [{"name": query, "artist": "", "album": "",
                     "url": query, "duration": 0, "id": ""}]
        return data
    except json.JSONDecodeError:
        return [{"name": query, "artist": "", "album": "",
                 "url": query, "duration": 0, "id": ""}]


# --- Download execution ---
def run_spotdl(operation, queries, extra_args):
    """Build and run `python -m spotdl <operation> [queries] [options]`."""
    python_exe = _get_python()

    # Auto-set output directory
    output_dir = extra_args.get("output") or DEFAULT_OUTPUT
    os.makedirs(output_dir, exist_ok=True)

    # Auto-set proxy if not specified
    needs_proxy = operation in ("download", "sync", "url", "save")
    proxy = extra_args.get("proxy")
    if needs_proxy and not proxy:
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

    # PROXY HANDLING - the critical part
    # spotDL only accepts HTTP/HTTPS in --proxy flag.
    # For SOCKS5 proxies, we must use --yt-dlp-args instead.
    if proxy:
        if _is_socks_proxy(proxy):
            # SOCKS5 proxy: pass via yt-dlp-args (bypasses spotDL's HTTP-only check)
            # yt-dlp directly supports socks5:// URLs
            existing_ytdlp = extra_args.get("yt_dlp_args", "")
            proxy_arg = f"--proxy {proxy}"
            if existing_ytdlp:
                yt_dlp_args_val = f"{existing_ytdlp} {proxy_arg}"
            else:
                yt_dlp_args_val = proxy_arg
            cmd.extend(["--yt-dlp-args", yt_dlp_args_val])
            print(f"[PROXY] SOCKS5 proxy applied via --yt-dlp-args: {proxy}")
        else:
            # HTTP/HTTPS proxy: use spotdl's native --proxy flag
            cmd.extend(["--proxy", proxy])
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
    env = os.environ.copy()
    if proxy:
        env.update(_proxy_to_env(proxy))
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"\n[RUN] {' '.join(cmd)}")
    if proxy:
        print(f"[ENV] Proxy env vars set: {_proxy_to_env(proxy)}")
    print("=" * 60)

    # Stream output in real-time with UTF-8 encoding
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        print(line, end="")

    proc.wait()
    exit_code = proc.returncode
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
    """Check if spotdl, ffmpeg, and PySocks are available."""
    python_exe = _find_python_with_spotdl()
    info = {
        "spotdl_installed": python_exe is not None,
        "ffmpeg": False,
        "pysocks": False,
        "default_proxy": DEFAULT_PROXY,
    }

    if python_exe:
        info["python_path"] = python_exe
        try:
            result = subprocess.run(
                [python_exe, "-m", "spotdl", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            info["spotdl_version"] = result.stdout.strip()
        except Exception:
            pass

        # Check PySocks
        try:
            result = subprocess.run(
                [python_exe, "-c", "import socks; print('PySocks OK')"],
                capture_output=True, text=True, timeout=5,
            )
            info["pysocks"] = result.returncode == 0
        except Exception:
            pass

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        info["ffmpeg"] = result.returncode == 0
        if info["ffmpeg"]:
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

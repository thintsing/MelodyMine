#!/usr/bin/env python3
"""
MelodyMine - Multi-platform audio downloader.

Bilibili: wbi API search + yt-dlp download (direct access, no proxy needed)
YouTube:  yt-dlp search + download (proxy optional, needed in China)
spotDL:   Spotify URL pipeline (optional, has known bugs)

Usage:
    python music_helper.py check
    python music_helper.py search "周杰伦 稻香"
    python music_helper.py download "周杰伦 稻香"
    python music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://host:port
    python music_helper.py download "https://open.spotify.com/track/xxx"
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ─── Constants ───────────────────────────────────────────────────────────

HOME = os.path.expanduser("~")
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def _get_default_output():
    """Pick a sensible default output directory that exists on this platform."""
    for candidate in [
        os.path.join(HOME, "Music", "MelodyMine"),     # Windows / macOS (~/Music exists)
        os.path.join(HOME, "Downloads", "music"),      # Linux desktop (~/Downloads)
        os.path.join(HOME, "music"),                   # Lowercase fallback
        os.path.join(HOME, "MelodyMine-downloads"),    # Last resort
    ]:
        parent = os.path.dirname(candidate)
        if os.path.isdir(parent):
            return candidate
    # Nothing exists — just use the first option, we'll mkdir it
    return os.path.join(HOME, "Music", "MelodyMine")


DEFAULT_OUTPUT = _get_default_output()

BILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

PROXY_PLATFORMS = {"youtube", "soundcloud", "niconico", "vimeo"}

SPOTIFY_RE = re.compile(
    r"https?://(?:open\.spotify\.com|spotify\.link)/(?:track|album|playlist|artist)/"
)

# wbi signing mixin table (fixed by Bilibili)
_MIXIN_KEY_ENC_TABS = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
]

# ─── Path / Dependency Detection (auto-bootstrap) ────────────────────────

# pip packages required for full functionality
REQUIRED_PACKAGES = ["yt-dlp", "requests", "pysocks"]
OPTIONAL_PACKAGES = ["imageio-ffmpeg", "spotdl"]

# Cached values (populated by ensure_deps)
_CACHED_PYTHON = None
_CACHED_YTDLP_VER = None
_CACHED_FFMPEG = None
_DEPS_CHECKED = False


def _collect_python_candidates():
    """Build an exhaustive list of Python interpreters to try."""
    candidates = []

    # 1. WorkBuddy venv (any version — don't hardcode)
    wb_base = os.path.join(HOME, ".workbuddy", "binaries", "python")
    if IS_WIN:
        candidates.append(os.path.join(wb_base, "envs", "default", "Scripts", "python.exe"))
        # Also try versioned dirs
        versions_dir = os.path.join(wb_base, "versions")
        if os.path.isdir(versions_dir):
            for v in sorted(os.listdir(versions_dir), reverse=True):
                candidates.append(os.path.join(versions_dir, v, "python.exe"))
    else:
        candidates.append(os.path.join(wb_base, "envs", "default", "bin", "python"))
        versions_dir = os.path.join(wb_base, "versions")
        if os.path.isdir(versions_dir):
            for v in sorted(os.listdir(versions_dir), reverse=True):
                candidates.append(os.path.join(versions_dir, v, "bin", "python"))

    # 2. Current interpreter (whatever ran this script)
    candidates.append(sys.executable)

    # 3. python3 / python / py on PATH
    for name in ["python3", "python", "py"]:
        path = shutil.which(name)
        if path:
            candidates.append(path)

    # 4. Common Windows install locations
    if IS_WIN:
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        for ver in ["3.13", "3.12", "3.11", "3.10"]:
            v = ver.replace(".", "")
            candidates.append(f"{local_app}\\Programs\\Python\\Python{v}\\python.exe")
            candidates.append(f"{prog_files}\\Python{v}\\python.exe")
            candidates.append(f"C:\\Python{v}\\python.exe")

    # 5. macOS / Linux common paths
    if not IS_WIN:
        for path in ["/usr/bin/python3", "/usr/local/bin/python3",
                      "/opt/homebrew/bin/python3", "/usr/bin/python"]:
            candidates.append(path)

        # pyenv shims + version dirs
        pyenv_root = os.environ.get("PYENV_ROOT", os.path.join(HOME, ".pyenv"))
        candidates.append(os.path.join(pyenv_root, "shims", "python3"))
        versions_dir = os.path.join(pyenv_root, "versions")
        if os.path.isdir(versions_dir):
            for v in sorted(os.listdir(versions_dir), reverse=True):
                candidates.append(os.path.join(versions_dir, v, "bin", "python3"))

        # conda / miniconda / anaconda
        for conda_base in [
            os.path.join(HOME, "miniconda3"),
            os.path.join(HOME, "anaconda3"),
            os.path.join(HOME, "miniforge3"),
            "/opt/conda",
        ]:
            candidates.append(os.path.join(conda_base, "bin", "python3"))
            envs_dir = os.path.join(conda_base, "envs")
            if os.path.isdir(envs_dir):
                for env_name in sorted(os.listdir(envs_dir)):
                    candidates.append(os.path.join(envs_dir, env_name, "bin", "python3"))

        # asdf
        asdf_dir = os.path.join(HOME, ".asdf")
        if os.path.isdir(asdf_dir):
            for py_ver_dir in glob.glob(os.path.join(asdf_dir, "installs", "python", "*")):
                candidates.append(os.path.join(py_ver_dir, "bin", "python3"))

        # pip --user installs location
        candidates.append(os.path.join(HOME, ".local", "bin", "python3"))

    # 6. macOS framework Python (python.org installer)
    if IS_MAC:
        fw_base = "/Library/Frameworks/Python.framework/Versions"
        if os.path.isdir(fw_base):
            for v in sorted(os.listdir(fw_base), reverse=True):
                candidates.append(os.path.join(fw_base, v, "bin", "python3"))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for c in candidates:
        rp = os.path.realpath(c) if c else ""
        if c and rp not in seen:
            seen.add(rp)
            unique.append(c)
    return unique


def _check_module(python, module_name, timeout=10):
    """Check if a Python has a module installed. Returns version string or None."""
    # yt_dlp stores version in yt_dlp.version.__version__, not top-level
    version_expr = {
        "yt_dlp": "yt_dlp.version.__version__",
    }.get(module_name, f"getattr({module_name}, '__version__', 'ok')")
    try:
        result = subprocess.run(
            [python, "-c", f"import {module_name}; print({version_expr})"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _pip_install(python, packages, timeout=180):
    """Install pip packages. Handles PEP 668 (externally-managed-environment).

    Strategy: regular install → --user → report failure (caller may create venv).
    Returns True on success.
    """
    if not packages:
        return True

    base_cmd = [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]

    # Attempt 1: regular install
    try:
        result = subprocess.run(
            base_cmd + packages,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return True
        # Check for PEP 668
        stderr_lower = (result.stderr or "").lower()
        if "externally-managed-environment" not in stderr_lower:
            return False
    except Exception:
        return False

    # Attempt 2: --user install (bypasses PEP 668 for user site-packages)
    try:
        result = subprocess.run(
            base_cmd + ["--user"] + packages,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    return False


# Dedicated venv path (created on demand when system Python is externally managed)
_VENV_DIR = os.path.join(HOME, ".cache", "melodymine-venv")


def _create_venv(base_python, timeout=120):
    """Create a dedicated virtual environment and install all deps.
    Returns (venv_python, yt_dlp_version) or (None, None).
    """
    if IS_WIN:
        venv_py = os.path.join(_VENV_DIR, "Scripts", "python.exe")
    else:
        venv_py = os.path.join(_VENV_DIR, "bin", "python")

    # Create venv if it doesn't exist
    if not os.path.isfile(venv_py):
        print(f"  Creating virtual environment at {_VENV_DIR}...")
        try:
            result = subprocess.run(
                [base_python, "-m", "venv", _VENV_DIR],
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                print(f"  [!] venv creation failed: {result.stderr[:200]}")
                return None, None
        except Exception as e:
            print(f"  [!] venv creation error: {e}")
            return None, None

    # Install packages into venv (venvs are never externally-managed)
    print(f"  Installing packages into venv...")
    _pip_install(venv_py, REQUIRED_PACKAGES + ["imageio-ffmpeg"])

    ver = _check_module(venv_py, "yt_dlp")
    if ver:
        return venv_py, ver
    return None, None


def find_python():
    """
    Find a Python interpreter with yt-dlp installed.
    Auto-installs yt-dlp + requests + pysocks if not present.
    Returns (path, yt_dlp_version) or (None, None).
    """
    global _CACHED_PYTHON, _CACHED_YTDLP_VER
    if _CACHED_PYTHON:
        return _CACHED_PYTHON, _CACHED_YTDLP_VER

    candidates = _collect_python_candidates()

    # Phase 1: find a Python that already has yt-dlp
    for py in candidates:
        if not py or not os.path.isfile(py):
            continue
        ver = _check_module(py, "yt_dlp")
        if ver:
            _CACHED_PYTHON = py
            _CACHED_YTDLP_VER = ver
            return py, ver

    # Phase 2: find any working Python and auto-install deps
    for py in candidates:
        if not py or not os.path.isfile(py):
            continue
        # Verify pip works
        pip_check = subprocess.run(
            [py, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if pip_check.returncode != 0:
            continue

        print(f"  Auto-installing: {', '.join(REQUIRED_PACKAGES)}")
        print(f"  Using: {py}")
        _pip_install(py, REQUIRED_PACKAGES)

        ver = _check_module(py, "yt_dlp")
        if ver:
            _CACHED_PYTHON = py
            _CACHED_YTDLP_VER = ver
            return py, ver

    # Phase 3: system Python is externally-managed (PEP 668) → create a venv
    # Find ANY working Python to create the venv with
    for py in candidates:
        if not py or not os.path.isfile(py):
            continue
        ver_check = subprocess.run(
            [py, "--version"], capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if ver_check.returncode == 0:
            print(f"  System Python is externally-managed, creating isolated venv...")
            venv_py, venv_ver = _create_venv(py)
            if venv_py:
                _CACHED_PYTHON = venv_py
                _CACHED_YTDLP_VER = venv_ver
                return venv_py, venv_ver
            break  # don't try more candidates if venv creation failed

    return None, None


def find_ffmpeg(python=None):
    """
    Find ffmpeg executable.
    Strategy: system PATH → imageio-ffmpeg (auto-installed pip package with bundled binary).
    Returns the ffmpeg command/path, or None.
    """
    global _CACHED_FFMPEG
    if _CACHED_FFMPEG:
        return _CACHED_FFMPEG

    # 1. Try system ffmpeg on PATH
    for exe in ["ffmpeg", "ffmpeg.exe"]:
        try:
            result = subprocess.run(
                [exe, "-version"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                _CACHED_FFMPEG = exe
                return exe
        except Exception:
            pass

    # 2. Try imageio-ffmpeg (bundled static ffmpeg binary)
    if python is None:
        python, _ = find_python()
    if python:
        # Auto-install if missing
        if not _check_module(python, "imageio_ffmpeg"):
            print("  Auto-installing: imageio-ffmpeg (bundled ffmpeg binary)")
            _pip_install(python, ["imageio-ffmpeg"])
        try:
            result = subprocess.run(
                [python, "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                if path and os.path.isfile(path):
                    _CACHED_FFMPEG = path
                    return path
        except Exception:
            pass

    return None


def ensure_deps():
    """
    Ensure all dependencies are available. Called at the start of every command.
    Populates cached values for find_python() and find_ffmpeg().
    Returns (python, yt_dlp_ver, ffmpeg_path) or (None, None, None).
    """
    global _DEPS_CHECKED
    if _DEPS_CHECKED:
        py, ver = find_python()
        return py, ver, find_ffmpeg(py)
    _DEPS_CHECKED = True

    py, ver = find_python()
    if not py:
        return None, None, None

    ff = find_ffmpeg(py)
    return py, ver, ff


def has_spotdl(python):
    try:
        result = subprocess.run(
            [python, "-c", "import spotdl; print(spotdl.__version__)"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ─── Language Detection ──────────────────────────────────────────────────

def is_chinese(text):
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def auto_select_platform(query):
    if is_chinese(query):
        return "bilibili"
    return "youtube"


def needs_proxy(platform):
    return platform in PROXY_PLATFORMS


def is_spotify_url(text):
    return bool(SPOTIFY_RE.search(text))


# ─── Bilibili wbi Search (bypasses yt-dlp broken search) ─────────────────

_BILI_SEARCH_SCRIPT = r"""
import hashlib, time, json, re, sys
from urllib.parse import quote
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
TABS = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13]

def mixed_key(orig):
    return "".join(orig[i] for i in TABS)[:32]

def wbi_sign(params, ik, sk):
    mk = mixed_key(ik + sk)
    params["wts"] = int(time.time())
    q = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in sorted(params.items()))
    params["w_rid"] = hashlib.md5((q + mk).encode()).hexdigest()
    return params

query = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://search.bilibili.com"})

try:
    nav = s.get("https://api.bilibili.com/x/web-interface/nav", timeout=10).json()
    ik = nav["data"]["wbi_img"]["img_url"].rsplit("/", 1)[1].split(".")[0]
    sk = nav["data"]["wbi_img"]["sub_url"].rsplit("/", 1)[1].split(".")[0]
except Exception as e:
    print(json.dumps({"error": f"wbi_key: {e}"}))
    sys.exit(1)

try:
    params = wbi_sign({"keyword": query, "search_type": "video", "page": 1, "page_size": str(limit)}, ik, sk)
    resp = s.get("https://api.bilibili.com/x/web-interface/search/type", params=params, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        print(json.dumps({"error": data.get("message", "unknown")}))
        sys.exit(1)
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
    print(json.dumps(results, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)
"""


def bili_search(query, limit=5, python=None):
    """
    Search Bilibili via official API with wbi signing.
    Uses subprocess to ensure requests library is available.
    Retries once after 2s delay if rate-limited.
    Returns list of dicts: {bvid, aid, title, duration, play, uploader}
    """
    if python is None:
        python, _ = find_python()
    if not python:
        print("  [!] No Python with requests found")
        return []

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    for attempt in range(2):  # max 2 attempts
        if attempt > 0:
            print("  [*] Retrying in 2s...")
            time.sleep(2)

        try:
            result = subprocess.run(
                [python, "-c", _BILI_SEARCH_SCRIPT, query, str(limit)],
                capture_output=True, text=True, timeout=30,
                env=env, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            if attempt == 0:
                continue
            print("  [!] Bilibili search timed out")
            return []
        except Exception as e:
            if attempt == 0:
                continue
            print(f"  [!] Bilibili search error: {e}")
            return []

        # Check for errors
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            err_msg = None
            if stdout:
                try:
                    err_data = json.loads(stdout)
                    if isinstance(err_data, dict) and "error" in err_data:
                        err_msg = err_data["error"]
                except json.JSONDecodeError:
                    pass
            if not err_msg and stderr:
                err_msg = stderr[:200]
            if not err_msg:
                err_msg = f"exit code {result.returncode}"

            if attempt == 0:
                print(f"  [!] Bilibili search attempt 1 failed: {err_msg}")
                continue  # retry
            else:
                print(f"  [!] Bilibili API: {err_msg}")
                return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            if attempt == 0:
                print("  [!] Bilibili returned non-JSON (likely rate-limited)")
                continue  # retry
            print("  [!] Bilibili search returned invalid JSON")
            return []

        if isinstance(data, dict) and "error" in data:
            if attempt == 0:
                print(f"  [!] Bilibili API: {data['error']}")
                continue  # retry
            print(f"  [!] Bilibili API: {data['error']}")
            return []

        return data if isinstance(data, list) else []

    return []


# ─── Metadata Enhancement (NetEase Music API + Title Parsing) ────────────

_NETEASE_SEARCH_SCRIPT = r"""
import json, sys, requests

query = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://music.163.com",
})

try:
    resp = s.post(
        "https://music.163.com/api/search/get",
        data={"s": query, "type": 1, "limit": limit, "offset": 0},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 200:
        print(json.dumps({"error": data.get("message", "unknown")}))
        sys.exit(1)
    songs = data.get("result", {}).get("songs", [])
    results = []
    for song in songs:
        artists = ", ".join(a["name"] for a in song.get("artists", []))
        album = song.get("album", {})
        results.append({
            "title": song.get("name", ""),
            "artist": artists,
            "album": album.get("name", ""),
            "duration": song.get("duration", 0),
            "pic_url": album.get("picUrl", ""),
        })
    print(json.dumps(results, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)
"""


def _clean_artist(name):
    """Clean up artist name from API (remove trailing dashes, periods, etc.)."""
    if not name:
        return ""
    # Take first artist if comma-separated
    name = name.split(",")[0].split("，")[0]
    # Strip trailing punctuation
    name = name.rstrip("-－—–.。，,·・")
    return name.strip()


def parse_search_query(query):
    """
    Parse a user search query to extract artist and title.
    "周杰伦 稻香"       -> ("周杰伦", "稻香")
    "The Weeknd Blinding Lights" -> ("The Weeknd", "Blinding Lights")
    "稻香"               -> (None, "稻香")

    For Chinese: first token = artist, rest = title
    For English: first token(s) before a capitalised word = artist
    """
    parts = query.strip().split()
    if len(parts) >= 2:
        # Simple heuristic: first part = artist, rest = title
        artist = parts[0]
        title = " ".join(parts[1:])
        return artist, title
    return None, query.strip()

_COVER_DOWNLOAD_SCRIPT = r"""
import sys, requests, tempfile, os
url = sys.argv[1]
try:
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        ext = ".jpg"
        ct = resp.headers.get("content-type", "")
        if "png" in ct:
            ext = ".png"
        tmp = os.path.join(tempfile.gettempdir(), "cover_" + str(os.getpid()) + ext)
        with open(tmp, "wb") as f:
            f.write(resp.content)
        print(tmp)
    else:
        print("")
except:
    print("")
"""


def metadata_lookup(query, python=None, limit=3):
    """
    Search NetEase Music API for song metadata.
    Returns list of dicts: {title, artist, album, duration, pic_url}
    or empty list on failure.
    """
    if python is None:
        python, _ = find_python()
    if not python:
        return []

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        result = subprocess.run(
            [python, "-c", _NETEASE_SEARCH_SCRIPT, query, str(limit)],
            capture_output=True, text=True, timeout=15,
            env=env, encoding="utf-8", errors="replace",
        )
    except Exception:
        return []

    stdout = result.stdout.strip()
    if not stdout:
        return []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict) and "error" in data:
        return []

    return data if isinstance(data, list) else []


# Noise words to strip from Bilibili titles
_NOISE_PATTERNS = [
    r"完整版", r"无损音质", r"无损", r"高清", r"超清", r"高品质",
    r"官方MV", r"官方", r"\bMV\b", r"\bOfficial\b", r"\bHD\b",
    r"\bLyrics?\b", r"歌词版?", r"歌词", r"现场版?", r"\bLive\b",
    r"纯音乐", r"伴奏", r"翻唱", r"字幕版?", r"音频版?", r"音频",
    r"\(.*?\)", r"（.*?）", r"【.*?】", r"［.*?］",
    r"\d{4}", r"｜.*", r"\|.*",
]


def parse_bili_title(title):
    """
    Extract artist and song name from a Bilibili video title.

    Patterns:
    - "周杰伦《稻香》完整版"     -> artist=周杰伦, title=稻香
    - "周杰伦 - 稻香 MV"         -> artist=周杰伦, title=稻香
    - "【周杰伦】稻香 官方MV"     -> artist=周杰伦, title=稻香

    Returns (artist, song_name) or (None, None).
    """
    artist = None
    song_name = None

    # Pattern 1: artist《title》
    m = re.match(r"^(.+?)《(.+?)》", title)
    if m:
        artist = m.group(1).strip()
        song_name = m.group(2).strip()

    # Pattern 2: 【artist】title or ［artist］title
    if not artist:
        m = re.match(r"^[【［](.+?)[】］]\s*(.+)", title)
        if m:
            artist = m.group(1).strip()
            song_name = m.group(2).strip()

    # Pattern 3: artist - title / artist — title / artist – title
    if not artist:
        m = re.match(r"^(.+?)\s*[-－—–]\s*(.+)", title)
        if m:
            artist = m.group(1).strip()
            song_name = m.group(2).strip()

    # Clean noise
    if song_name:
        for p in _NOISE_PATTERNS:
            song_name = re.sub(p, "", song_name)
        song_name = song_name.strip(" -｜|\t")

    if artist:
        for p in _NOISE_PATTERNS:
            artist = re.sub(p, "", artist)
        artist = artist.strip(" -｜|\t")

    return artist, song_name


def sanitize_filename(name):
    """Sanitize a string for use as a filename (cross-platform safe)."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def find_downloaded_file(output_dir):
    """Find the most recently created/modified audio file in output_dir."""
    audio_exts = {".mp3", ".flac", ".m4a", ".opus", ".wav", ".vorbis", ".ogg", ".webm"}
    output_path = Path(output_dir)
    if not output_path.exists():
        return None
    files = [f for f in output_path.iterdir() if f.suffix.lower() in audio_exts]
    if not files:
        return None
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return str(files[0])


def download_cover(url, python=None):
    """Download a cover image from URL. Returns local path or None."""
    if not url:
        return None
    if python is None:
        python, _ = find_python()
    if not python:
        return None
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [python, "-c", _COVER_DOWNLOAD_SCRIPT, url],
            capture_output=True, text=True, timeout=15,
            env=env, encoding="utf-8", errors="replace",
        )
        path = result.stdout.strip()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


def set_metadata(filepath, title=None, artist=None, album=None, cover_path=None):
    """
    Use ffmpeg to set ID3 metadata on an audio file.
    Preserves existing streams (including embedded cover art).
    Returns True on success.
    """
    ffmpeg_exe = find_ffmpeg()
    if not ffmpeg_exe:
        print("  [!] FFmpeg not found (tried system + imageio-ffmpeg), skipping metadata")
        return False

    # Temp file must keep the same extension so ffmpeg recognises the format
    base, ext = os.path.splitext(filepath)
    tmp_path = base + ".meta_tmp" + ext
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    cmd = [ffmpeg_exe, "-y", "-i", filepath]
    has_cover = cover_path and os.path.isfile(cover_path)
    if has_cover:
        cmd.extend(["-i", cover_path])

    # Map all original streams; add cover as additional stream
    cmd.extend(["-map", "0"])
    if has_cover:
        cmd.extend(["-map", "1"])
    cmd.extend(["-c", "copy"])
    if has_cover:
        cmd.extend(["-disposition:v:0", "attached_pic"])
    cmd.extend(["-id3v2_version", "3"])

    if title:
        cmd.extend(["-metadata", f"title={title}"])
    if artist:
        cmd.extend(["-metadata", f"artist={artist}"])
    if album:
        cmd.extend(["-metadata", f"album={album}"])

    cmd.append(tmp_path)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and os.path.isfile(tmp_path):
            os.remove(filepath)
            os.rename(tmp_path, filepath)
            return True
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        return False
    except Exception:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        return False


def enhance_metadata(python, search_query, bili_title, output_dir):
    """
    Post-download metadata enhancement (3-layer strategy).

    Layer 1: Parse user's search query (e.g. "周杰伦 稻香" -> artist=周杰伦, title=稻香)
    Layer 2: NetEase Music API (best-effort album/cover lookup)
    Layer 3: Parse Bilibili video title (fallback)

    Then: set ID3 tags with ffmpeg + rename file to "Artist - Title.ext"

    Never raises — metadata enhancement is best-effort.
    """
    filepath = find_downloaded_file(output_dir)
    if not filepath:
        print("  [!] Could not find downloaded file for metadata")
        return

    print(f"\n[3/3] Enhancing metadata...")

    # ── Layer 1: Parse search query ──
    artist, title = parse_search_query(search_query)
    if artist and title:
        print(f"  From search query: artist={artist}, title={title}")
    elif bili_title:
        artist, title = parse_bili_title(bili_title)
        if artist and title:
            print(f"  From Bilibili title: artist={artist}, title={title}")

    if not artist or not title:
        print(f"  [!] Could not determine artist/title, keeping original tags")
        return

    # ── Layer 2: NetEase Music API (best-effort album + cover) ──
    album = ""
    pic_url = ""
    print(f"  Looking up album info on NetEase Music: {search_query}")
    results = metadata_lookup(search_query, python=python, limit=10)
    if results:
        # Find best match: prefer exact artist match (single-artist tracks)
        # to avoid picking up covers/remixes with collaborators
        best = None
        best_score = -1
        for r in results:
            r_artist_raw = r.get("artist", "")
            r_artist = _clean_artist(r_artist_raw)
            r_title = r.get("title", "").strip()
            is_collaboration = "," in r_artist_raw or "，" in r_artist_raw

            # Score: exact solo artist match > collaboration > no match
            score = 0
            if r_artist == artist and not is_collaboration:
                score += 20  # exact solo artist match (likely original)
            elif r_artist == artist and is_collaboration:
                score += 5   # artist matches but it's a collab (likely cover)
            elif artist in r_artist_raw:
                score += 3   # partial match
            if r_title == title:
                score += 5   # exact title match
            elif title in r_title or r_title in title:
                score += 2   # partial title match

            if score > best_score:
                best_score = score
                best = r

        if best:
            # Only use album from API if we have a high-confidence match
            # (solo artist match = score >= 20, meaning not a collaboration)
            if best_score >= 20:
                album = best.get("album", "").strip()
                pic_url = best.get("pic_url", "")
                if album:
                    print(f"  Album: {album} (high-confidence match)")
                if pic_url:
                    print(f"  Cover: available")
                else:
                    print(f"  Cover: not available (will keep Bilibili thumbnail)")
            else:
                print(f"  No original version found (all results are covers/remixes)")
                print(f"  Album info skipped — title and artist will still be set")
                pic_url = best.get("pic_url", "")  # still try cover
        else:
            print(f"  No suitable match found in NetEase results")
    else:
        print(f"  NetEase Music: no results (using parsed metadata only)")

    # ── Layer 3: Download album cover ──
    cover_path = None
    if pic_url:
        cover_path = download_cover(pic_url, python)
        if cover_path:
            print(f"  Downloaded album cover")

    # ── Set ID3 tags with ffmpeg ──
    ok = set_metadata(
        filepath,
        title=title,
        artist=artist,
        album=album,
        cover_path=cover_path,
    )
    if ok:
        print(f"  [OK] Metadata embedded: {artist} - {title}" + (f" | {album}" if album else ""))
    else:
        print(f"  [!] Failed to set metadata (ffmpeg error)")

    # ── Rename file ──
    new_base = sanitize_filename(f"{artist} - {title}")
    if new_base:
        ext = os.path.splitext(filepath)[1]
        new_path = os.path.join(os.path.dirname(filepath), new_base + ext)
        if new_path != filepath and not os.path.exists(new_path):
            try:
                os.rename(filepath, new_path)
                print(f"  Renamed: {os.path.basename(new_path)}")
            except Exception:
                pass  # keep original name if rename fails

    # Cleanup cover temp file
    if cover_path and os.path.isfile(cover_path):
        try:
            os.remove(cover_path)
        except Exception:
            pass


# ─── yt-dlp Download ─────────────────────────────────────────────────────

def _ytdlp_download(
    python, url_or_query, output, fmt, bitrate=None,
    embed_thumbnail=True, proxy=None, bili_ua=False, index=1,
):
    """Run yt-dlp to download and convert audio. Returns True on success."""
    cmd = [
        python, "-m", "yt_dlp",
        url_or_query,
        "--playlist-items", str(index),
        "-f", "bestaudio/best",
        "-x",
        "--audio-format", fmt,
        "--embed-metadata",
        "-o", os.path.join(output, "%(title)s.%(ext)s"),
        "--no-warnings",
        "--newline",
    ]

    # Tell yt-dlp where ffmpeg is (critical when using imageio-ffmpeg)
    ffmpeg_exe = find_ffmpeg(python)
    if ffmpeg_exe and ffmpeg_exe not in ("ffmpeg", "ffmpeg.exe"):
        cmd.extend(["--ffmpeg-location", ffmpeg_exe])

    if bitrate:
        cmd.extend(["--audio-quality", str(bitrate)])
    else:
        cmd.extend(["--audio-quality", "0"])

    if embed_thumbnail:
        cmd.append("--embed-thumbnail")

    if bili_ua:
        cmd.extend(["--user-agent", BILI_UA])

    if proxy:
        cmd.extend(["--proxy", proxy])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        print(line, end="")
    proc.wait()
    return proc.returncode == 0


# ─── Commands ────────────────────────────────────────────────────────────

def cmd_setup():
    """One-shot bootstrap: find Python, install all deps, get ffmpeg."""
    print("=" * 60)
    print("  MelodyMine — First-Time Setup")
    print("=" * 60)
    print()

    # Step 1: Find Python
    print("[1/4] Finding Python interpreter...")
    candidates = _collect_python_candidates()
    working_py = None
    for py in candidates:
        if not py or not os.path.isfile(py):
            continue
        ver = subprocess.run(
            [py, "--version"], capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if ver.returncode == 0:
            print(f"  Found: {py} ({ver.stdout.strip()})")
            working_py = py
            break

    if not working_py:
        print("  [FAIL] No Python found on this system.")
        print("         Install Python 3.10+ from https://python.org")
        return False
    print()

    # Step 2: Install pip packages
    print("[2/4] Installing Python packages (yt-dlp, requests, pysocks, imageio-ffmpeg)...")
    ok = _pip_install(working_py, REQUIRED_PACKAGES + ["imageio-ffmpeg"])
    if ok:
        print("  [OK] All packages installed")
    else:
        print("  [WARN] Some packages may have failed to install")
    # Verify
    for pkg, mod in [("yt-dlp", "yt_dlp"), ("requests", "requests"),
                      ("pysocks", "socks"), ("imageio-ffmpeg", "imageio_ffmpeg")]:
        ver = _check_module(working_py, mod)
        if ver:
            print(f"  [OK]   {pkg:20s} {ver}")
        else:
            print(f"  [FAIL] {pkg:20s} not installed")
    print()

    # Step 3: Find ffmpeg
    print("[3/4] Locating ffmpeg...")
    # Force re-detection (clear cache)
    global _CACHED_FFMPEG
    _CACHED_FFMPEG = None
    ff = find_ffmpeg(working_py)
    if ff:
        # Get version
        try:
            r = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=5,
                               encoding="utf-8", errors="replace")
            ver_line = r.stdout.split("\n")[0] if r.returncode == 0 else ff
        except Exception:
            ver_line = ff
        print(f"  [OK] {ver_line}")
    else:
        print("  [FAIL] ffmpeg not found (system PATH + imageio-ffmpeg both failed)")
        return False
    print()

    # Step 4: Summary
    print("[4/4] Setup complete!")
    print()
    print("  You can now download music:")
    print(f'    python music_helper.py download "周杰伦 稻香"')
    print()
    print("  Platform availability:")
    has_yt = _check_module(working_py, "yt_dlp")
    has_req = _check_module(working_py, "requests")
    has_socks = _check_module(working_py, "socks")
    if has_yt and ff:
        print("    [OK] Bilibili  (Chinese songs, no proxy needed)")
    if has_yt and has_socks and ff:
        print("    [OK] YouTube   (English songs, needs --proxy socks5://...)")
    if has_req:
        print("    [OK] NetEase   (metadata lookup for album/cover)")
    sp = has_spotdl(working_py)
    if sp:
        print(f"    [OK] Spotify   (via spotDL v{sp})")
    else:
        print("    [--] Spotify   (optional: pip install spotdl)")
    print()
    return True


def cmd_check():
    print("=== MelodyMine — Dependency Check ===\n")

    # This will auto-install if needed
    py, ytdlp_ver, ff = ensure_deps()

    if py:
        print(f"  [OK]   Python:        {py}")
        print(f"  [OK]   yt-dlp:        v{ytdlp_ver}")
    else:
        print("  [FAIL] No Python with yt-dlp found")
        print("         Run: python music_helper.py setup")
        return False

    if ff:
        print(f"  [OK]   FFmpeg:        {ff}")
    else:
        print("  [FAIL] FFmpeg not found")
        return False

    # requests (for Bilibili wbi search)
    req_ver = _check_module(py, "requests")
    if req_ver:
        print(f"  [OK]   requests:      v{req_ver} (for Bilibili API)")
    else:
        print("  [--]   requests:      not installed (auto-installs on first use)")

    # PySocks (for SOCKS5 proxy)
    socks_ver = _check_module(py, "socks")
    if socks_ver:
        print(f"  [OK]   PySocks:       available (for SOCKS5 proxy)")
    else:
        print("  [--]   PySocks:       not installed (auto-installs on first use)")

    sp_ver = has_spotdl(py)
    if sp_ver:
        print(f"  [OK]   spotDL:        v{sp_ver}  (optional, for Spotify URLs)")
    else:
        print("  [--]   spotDL:        not installed (optional)")

    print("\n  Platforms:")
    print("    - Bilibili  (Chinese songs, no proxy needed)")
    print("    - YouTube   (English songs, proxy optional — needed in China)")
    print("    - Spotify URL  (optional, via spotDL)")
    print("\n=== Ready! ===")
    return True


def cmd_search(query, platform="auto", limit=5, proxy=None):
    """Search for songs and print results."""
    py, _, _ = ensure_deps()
    if not py:
        print("ERROR: No Python with yt-dlp found. Run 'setup' first:")
        print("  python music_helper.py setup")
        sys.exit(1)

    if platform == "auto":
        platform = auto_select_platform(query)

    print(f"Searching on {platform} for: {query}")
    print("=" * 60)

    if platform == "bilibili":
        # Use wbi API search (more reliable than yt-dlp's bilisearch)
        results = bili_search(query, limit=limit)
        if results:
            for i, r in enumerate(results, 1):
                print(f"  {i}. [{r['duration']}] {r['title']}")
                print(f"     Uploader: {r['uploader']} | Plays: {r['play']} | bvid: {r['bvid']}")
                print()
            print(f"Top {len(results)} results. Use --index N to download a specific result.")
        else:
            print("No results or search failed.")
            print("Tip: Try --platform youtube --proxy socks5://host:port")
    else:
        # YouTube search via yt-dlp
        search_query = f"ytsearch:{query}"
        cmd = [
            py, "-m", "yt_dlp",
            search_query,
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(duration_string)s",
            "--playlist-end", str(limit),
            "--no-warnings",
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, encoding="utf-8", errors="replace",
        )
        count = 0
        for line in proc.stdout:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                count += 1
                vid, title = parts[0], parts[1]
                dur = parts[2] if len(parts) > 2 else "?"
                print(f"  {count}. [{dur}] {title}")
                print(f"     https://www.youtube.com/watch?v={vid}")
                print()
        proc.wait()
        if count == 0:
            err = proc.stderr.read() if proc.stderr else ""
            if err:
                print(f"Search error: {err.strip()}")
            print("No results. Add --proxy if YouTube is blocked in your region.")


def cmd_download(
    query, platform="auto", fmt="mp3", output=None,
    proxy=None, bitrate=None, index=1, embed_thumbnail=True,
    no_metadata=False,
):
    """Download a song with automatic platform selection and fallback."""
    py, _, _ = ensure_deps()
    if not py:
        print("ERROR: No Python with yt-dlp found. Run 'setup' first:")
        print("  python music_helper.py setup")
        sys.exit(1)

    # ── Spotify URL → spotDL ──
    if is_spotify_url(query):
        return _download_via_spotdl(py, query, fmt, output, proxy, bitrate)

    if platform == "auto":
        platform = auto_select_platform(query)

    if not output:
        output = DEFAULT_OUTPUT
    os.makedirs(output, exist_ok=True)

    # ── Bilibili: wbi search + yt-dlp download ──
    if platform == "bilibili":
        print("=" * 60)
        print(f"  Platform : Bilibili (direct, no proxy)")
        print(f"  Query    : {query}")
        print(f"  Format   : {fmt}")
        print(f"  Output   : {output}")
        print("=" * 60)
        print()

        # Step 1: wbi search
        print("[1/3] Searching Bilibili...")
        results = bili_search(query, limit=max(index, 5), python=py)
        if not results:
            print("\n  Bilibili search failed (rate-limited or network issue).")
            print("  Falling back to YouTube...")
            return _do_youtube_download(
                py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
                no_metadata=no_metadata,
            )

        # Step 2: Pick result and download
        item = results[min(index - 1, len(results) - 1)]
        bvid = item["bvid"]
        url = f"https://www.bilibili.com/video/{bvid}"
        print(f"  Found: [{item['duration']}] {item['title']}")
        print(f"  bvid: {bvid}")
        print()
        print("[2/3] Downloading via yt-dlp...")

        ok = _ytdlp_download(
            py, url, output, fmt, bitrate, embed_thumbnail,
            bili_ua=True, index=1,
        )
        if ok:
            if not no_metadata:
                enhance_metadata(py, query, item["title"], output)
            print(f"\n[OK] Download complete!")
            print(f"     Files saved to: {output}")
            return

        # Bilibili download failed → try YouTube fallback
        print(f"\n  Bilibili download failed.")
        print("  Falling back to YouTube...")
        return _do_youtube_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata,
        )

    # ── YouTube ──
    else:
        return _do_youtube_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata,
        )


def _do_youtube_download(
    py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
    no_metadata=False,
):
    """Download from YouTube via yt-dlp search + download.
    Proxy is optional — users outside China don't need it.
    """
    search_query = f"ytsearch:{query}"
    print("=" * 60)
    print(f"  Platform : YouTube")
    print(f"  Query    : {query}")
    print(f"  Format   : {fmt}")
    print(f"  Output   : {output}")
    if proxy:
        print(f"  Proxy    : {proxy}")
    else:
        print(f"  Proxy    : none (direct connection)")
    print("=" * 60)
    print()

    ok = _ytdlp_download(
        py, search_query, output, fmt, bitrate, embed_thumbnail,
        proxy=proxy, index=index,
    )
    if ok:
        if not no_metadata:
            enhance_metadata(py, query, "", output)
        print(f"\n[OK] Download complete!")
        print(f"     Files saved to: {output}")
        return

    print(f"\n[FAIL] YouTube download failed.")
    print("\n--- Common YouTube Issues ---")
    if not proxy:
        print("  1. Network unreachable / timeout")
        print("     → If you're in China, YouTube is blocked.")
        print("       Add a proxy: --proxy socks5://HOST:PORT")
        print("       or: --proxy http://HOST:PORT")
    print("  2. 'Sign in to confirm you are not a bot'")
    print("     → YouTube detected automated access. Export cookies from browser:")
    print("       Install 'Get cookies.txt' extension, export YouTube cookies")
    print("       Then pass: --cookies cookies.txt")
    if proxy:
        print("  3. Proxy connection failed")
        print("     → Check proxy is working: curl --proxy socks5://host:port https://youtube.com")
    print("  4. Try different search terms (English names for Chinese songs)")
    sys.exit(1)


def _download_via_spotdl(python, url, fmt, output, proxy, bitrate):
    """Delegate Spotify URL downloads to spotDL."""
    sp_ver = has_spotdl(python)
    if not sp_ver:
        print("  spotDL not installed, auto-installing...")
        _pip_install(python, ["spotdl"])
        sp_ver = has_spotdl(python)
    if not sp_ver:
        print("ERROR: spotDL installation failed.")
        print("       Try manually: pip install spotdl")
        print("       Or search by song name instead of Spotify URL.")
        sys.exit(1)

    if not output:
        output = DEFAULT_OUTPUT
    os.makedirs(output, exist_ok=True)

    cmd = [
        python, "-m", "spotdl", "download", url,
        "--output", output,
        "--format", fmt,
        "--print-errors",
    ]
    if bitrate:
        cmd.extend(["--bitrate", str(bitrate)])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    if proxy:
        if proxy.startswith("socks5"):
            cmd.extend(["--yt-dlp-args", f"--proxy {proxy}"])
            env["ALL_PROXY"] = proxy
        else:
            cmd.extend(["--proxy", proxy])

    print("=" * 60)
    print("  Engine   : spotDL (Spotify URL)")
    print(f"  URL      : {url}")
    print(f"  Format   : {fmt}")
    print(f"  Output   : {output}")
    if proxy:
        print(f"  Proxy    : {proxy}")
    print("=" * 60)
    print()

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        print(line, end="")
    proc.wait()

    if proc.returncode != 0:
        print(f"\n[FAIL] spotDL exited with code {proc.returncode}")
        print("\n--- Common spotDL Issues ---")
        print("  1. KeyError 'uri'   -> SpotipyFree API bug")
        print("  2. YouTube blocked  -> Ensure proxy is working")
        print("  3. Fallback         -> Search by song name instead of Spotify URL")
        sys.exit(1)

    print(f"\n[OK] Download complete!")
    print(f"     Files saved to: {output}")


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MelodyMine - Multi-platform audio downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  setup                                    First-time setup (install all deps)
  check                                    Verify dependencies
  search "周杰伦 稻香"                      Search Bilibili (auto)
  search "The Weeknd" --proxy socks5://...  Search YouTube
  download "周杰伦 稻香"                     Download (Bilibili, no proxy)
  download "The Weeknd" --proxy socks5://HOST:PORT
  download "https://open.spotify.com/track/xxx"   Via spotDL
  download "周杰伦 稻香" --format flac        FLAC format
  download "周杰伦 稻香" --index 2           Download 2nd search result
        """,
    )
    sub = parser.add_subparsers(dest="operation")

    sub.add_parser("setup", help="First-time setup: install all dependencies automatically")
    sub.add_parser("check", help="Verify dependencies (auto-installs if missing)")

    p_search = sub.add_parser("search", help="Search for songs (no download)")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--platform", default="auto", choices=["auto", "bilibili", "youtube"])
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--proxy", default=None)

    p_dl = sub.add_parser("download", help="Download a song")
    p_dl.add_argument("query", help="Song name, artist, Spotify URL, or search query")
    p_dl.add_argument("--platform", default="auto", choices=["auto", "bilibili", "youtube"])
    p_dl.add_argument("--format", default="mp3", choices=["mp3", "flac", "m4a", "opus", "wav", "vorbis"])
    p_dl.add_argument("--output", default=None, help="Output dir (default: ~/Music/MelodyMine)")
    p_dl.add_argument("--proxy", default=None, help="Proxy for YouTube (e.g. socks5://host:port)")
    p_dl.add_argument("--bitrate", default=None, help="Audio bitrate (e.g. 320K)")
    p_dl.add_argument("--index", type=int, default=1, help="Search result index (1-based)")
    p_dl.add_argument("--no-thumbnail", action="store_true")
    p_dl.add_argument("--no-metadata", action="store_true",
                      help="Skip metadata enhancement (NetEase lookup + ID3 tags + rename)")

    args = parser.parse_args()

    if args.operation == "setup":
        ok = cmd_setup()
        sys.exit(0 if ok else 1)
    elif args.operation == "check":
        ok = cmd_check()
        sys.exit(0 if ok else 1)
    elif args.operation == "search":
        cmd_search(args.query, args.platform, args.limit, args.proxy)
    elif args.operation == "download":
        cmd_download(
            args.query,
            platform=args.platform,
            fmt=args.format,
            output=args.output,
            proxy=args.proxy,
            bitrate=args.bitrate,
            index=args.index,
            embed_thumbnail=not args.no_thumbnail,
            no_metadata=args.no_metadata,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

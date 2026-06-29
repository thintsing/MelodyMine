#!/usr/bin/env python3
"""MelodyMine shared infrastructure.

Centralizes cross-cutting concerns used by both ``music_helper.py`` and
``spotify_helper.py``:

- Platform / constant definitions
- Default output directory selection
- Python interpreter discovery (with auto-install + venv fallback)
- pip install (PEP 668 aware)
- ffmpeg detection (system PATH + imageio-ffmpeg bundle)
- Proxy URL helpers (SOCKS5 aware)
- Language / Spotify-URL detection
- Filename sanitization

Importing this module keeps both helpers in sync and avoids divergent
venv paths or duplicated dependency-install logic.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import time

# ─── Platform / Constants ────────────────────────────────────────────────

HOME = os.path.expanduser("~")
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

BILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

PROXY_PLATFORMS = {"youtube", "soundcloud", "niconico", "vimeo"}

SPOTIFY_RE = re.compile(
    r"https?://(?:open\.spotify\.com|spotify\.link)/(?:track|album|playlist|artist)/"
)

# NetEase Cloud Music URL: music.163.com/song?id=xxx or y.music.126.com/n/song?ids=xxx
NETEASE_RE = re.compile(
    r"https?://(?:music\.163\.com|y\.music\.126\.com)/\S*[?&]ids?=(\d+)"
)

# Direct audio source URLs that yt-dlp can download without a search step.
YOUTUBE_RE = re.compile(
    r"https?://(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]{6,}"
)
SOUNDCLOUD_RE = re.compile(
    r"https?://(?:www\.|m\.)?soundcloud\.com/[\w\-]+/[\w\-]+"
)
BANDCAMP_RE = re.compile(
    r"https?://[\w\-]+\.bandcamp\.com/track/[\w\-]+"
)

# Unified venv path shared by both helpers so dependencies are installed once.
VENV_DIR = os.path.join(HOME, ".cache", "melodymine-venv")

# Dependency version compatibility matrix.
# Format: module_name -> (min_version, max_major, tested_version, severity)
#   min_version: lowest version that works (inclusive)
#   max_major:   highest major version allowed (exclusive upper bound)
#   tested_version: a version explicitly verified to work
#   severity: "error" = likely broken, "warn" = untested but probably OK
#
# Rationale:
#   yt-dlp: only set a floor (platform-compat fixes ship constantly); no upper
#           bound because new versions almost always improve extraction.
#   spotdl: hard-cap major version — MelodyMine imports spotdl's internal
#           SpotifyClient API (spotify_helper.py), which breaks across majors.
DEP_COMPAT = {
    "yt_dlp": {"min": "2024.0.0", "max_major": None, "tested": "2026.06.09", "severity": "warn"},
    "spotdl": {"min": "4.2.0", "max_major": 5, "tested": "4.5.0", "severity": "error"},
}


def check_version_compat(module_name, installed_version):
    """Check an installed version against the compatibility matrix.

    Returns (status, message):
      status: "ok" | "warn" | "error"
      message: human-readable explanation, or "" if ok
    """
    spec = DEP_COMPAT.get(module_name)
    if not spec or not installed_version:
        return "ok", ""

    def _parse(v):
        """Parse a version string into a tuple of ints for comparison."""
        parts = re.split(r"[.\-]", v)
        nums = []
        for p in parts:
            try:
                nums.append(int(p))
            except ValueError:
                break
        return tuple(nums) or (0,)

    inst = _parse(installed_version)

    # Floor check
    if spec["min"] and inst < _parse(spec["min"]):
        return spec["severity"], f"v{installed_version} is below minimum v{spec['min']} — upgrade required"

    # Major cap check
    if spec["max_major"] is not None:
        if inst and inst[0] >= spec["max_major"]:
            return spec["severity"], (
                f"v{installed_version} is at or above major v{spec['max_major']} "
                f"— MelodyMine was tested up to v{spec['tested']}, "
                f"downgrade with: pip install {module_name.replace('_', '-')}<\"{spec['max_major']}.0.0\""
            )

    # Untested-but-ok
    if spec["tested"] and inst != _parse(spec["tested"]):
        return "warn", f"v{installed_version} (tested on v{spec['tested']}, should work but unverified)"

    return "ok", ""


def _get_default_output():
    """Pick a sensible default output directory that exists on this platform."""
    for candidate in [
        os.path.join(HOME, "Music", "MelodyMine"),     # Windows / macOS
        os.path.join(HOME, "Downloads", "music"),      # Linux desktop
        os.path.join(HOME, "music"),                   # Lowercase fallback
        os.path.join(HOME, "MelodyMine-downloads"),    # Last resort
    ]:
        parent = os.path.dirname(candidate)
        if os.path.isdir(parent):
            return candidate
    return os.path.join(HOME, "Music", "MelodyMine")


DEFAULT_OUTPUT = _get_default_output()


# ─── Python / Dependency Discovery ───────────────────────────────────────

# Per-required-module cache: module_name -> (python_path, version)
_PYTHON_CACHE = {}
_CACHED_FFMPEG = None


def _collect_python_candidates():
    """Build an exhaustive list of Python interpreters to try."""
    candidates = []

    # 1. Unified MelodyMine venv (if it exists)
    if IS_WIN:
        candidates.append(os.path.join(VENV_DIR, "Scripts", "python.exe"))
    else:
        candidates.append(os.path.join(VENV_DIR, "bin", "python"))

    # 2. WorkBuddy venv (any version — don't hardcode)
    wb_base = os.path.join(HOME, ".workbuddy", "binaries", "python")
    if IS_WIN:
        candidates.append(os.path.join(wb_base, "envs", "default", "Scripts", "python.exe"))
    else:
        candidates.append(os.path.join(wb_base, "envs", "default", "bin", "python"))
    wb_versions = os.path.join(wb_base, "versions")
    if os.path.isdir(wb_versions):
        for v in sorted(os.listdir(wb_versions), reverse=True):
            if IS_WIN:
                candidates.append(os.path.join(wb_versions, v, "python.exe"))
            else:
                candidates.append(os.path.join(wb_versions, v, "bin", "python"))

    # 3. Hermes Agent bundled runtime (uv-managed Python 3.11)
    #    Windows: %LOCALAPPDATA%\hermes ; Unix: ~/.hermes (or $HERMES_HOME)
    hermes_home = os.environ.get("HERMES_HOME") or (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes") if IS_WIN
        else os.path.join(HOME, ".hermes")
    )
    if IS_WIN:
        candidates.append(os.path.join(hermes_home, "bin", "python.exe"))
    else:
        candidates.append(os.path.join(hermes_home, "bin", "python3"))

    # 4. uv-managed CPython (used by Hermes and standalone uv installs)
    #    Win: %APPDATA%\uv\data\python\cpython-3.1*\python.exe
    #    Unix: ~/.local/share/uv/python/cpython-3.1*/bin/python3
    uv_py_root = (
        os.path.join(os.environ.get("APPDATA", ""), "uv", "data", "python")
        if IS_WIN else os.path.join(HOME, ".local", "share", "uv", "python")
    )
    if os.path.isdir(uv_py_root):
        for v in sorted(os.listdir(uv_py_root), reverse=True):
            if not v.startswith("cpython-3.1"):
                continue
            if IS_WIN:
                candidates.append(os.path.join(uv_py_root, v, "python.exe"))
            else:
                candidates.append(os.path.join(uv_py_root, v, "bin", "python3"))

    # 5. Current interpreter (whatever ran this script)
    candidates.append(sys.executable)

    # 6. python3 / python / py on PATH
    for name in ["python3", "python", "py"]:
        path = shutil.which(name)
        if path:
            candidates.append(path)

    # 7. Common Windows install locations
    if IS_WIN:
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        for ver in ["3.13", "3.12", "3.11", "3.10"]:
            v = ver.replace(".", "")
            candidates.append(f"{local_app}\\Programs\\Python\\Python{v}\\python.exe")
            candidates.append(f"{prog_files}\\Python{v}\\python.exe")
            candidates.append(f"C:\\Python{v}\\python.exe")

    # 8. macOS / Linux common paths
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

        # conda / miniconda / anaconda / miniforge
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

    # 9. macOS framework Python (python.org installer)
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


def check_module(python, module_name, timeout=10):
    """Check if a Python has a module installed. Returns version string or None."""
    # yt_dlp stores version in yt_dlp.version.__version__, not top-level
    version_expr = {
        "yt_dlp": "yt_dlp.version.__version__",
    }.get(module_name, f"getattr({module_name}, '__version__', 'ok')")
    try:
        result = subprocess.run(
            [python, "-c", f"import {module_name}; print({version_expr})"],
            capture_output=True, text=True, timeout=timeout,
            env=make_subprocess_env(), encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        debug_log(f"check_module failed for {module_name}: {e}")
        pass
    return None


def pip_install(python, packages, timeout=180):
    """Install pip packages. Handles PEP 668 (externally-managed-environment).

    Strategy: regular install -> --user -> report failure (caller may create venv).
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
            env=make_subprocess_env(), encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return True
        if "externally-managed-environment" not in (result.stderr or "").lower():
            return False
    except Exception as e:
        debug_log(f"pip_install attempt 1 failed: {e}")
        return False

    # Attempt 2: --user install (bypasses PEP 668 for user site-packages)
    try:
        result = subprocess.run(
            base_cmd + ["--user"] + packages,
            capture_output=True, text=True, timeout=timeout,
            env=make_subprocess_env(), encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return True
    except Exception as e:
        debug_log(f"pip_install attempt 2 (--user) failed: {e}")
        pass

    return False


def _create_venv(base_python, install_packages, verify_module="yt_dlp", timeout=120):
    """Create the unified virtual environment and install all deps.

    Returns (venv_python, verify_module_version) or (None, None).
    """
    if IS_WIN:
        venv_py = os.path.join(VENV_DIR, "Scripts", "python.exe")
    else:
        venv_py = os.path.join(VENV_DIR, "bin", "python")

    if not os.path.isfile(venv_py):
        print(f"  Creating virtual environment at {VENV_DIR}...")
        try:
            result = subprocess.run(
                [base_python, "-m", "venv", VENV_DIR],
                capture_output=True, text=True, timeout=timeout,
                env=make_subprocess_env(), encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                print(f"  [!] venv creation failed: {(result.stderr or '')[:200]}")
                return None, None
        except Exception as e:
            print(f"  [!] venv creation error: {e}")
            return None, None

    print(f"  Installing packages into venv...")
    pip_install(venv_py, install_packages)

    ver = check_module(venv_py, verify_module)
    if ver:
        return venv_py, ver
    return None, None


def detect_python_with(required_module):
    """Detect a Python that has ``required_module`` installed, WITHOUT auto-installing.

    Returns (path, version) or (None, None). Use for read-only checks (e.g.
    ``check`` commands) where installation side-effects are undesirable.
    """
    for py in _collect_python_candidates():
        if not py or not os.path.isfile(py):
            continue
        ver = check_module(py, required_module)
        if ver:
            return py, ver
    return None, None


def find_python(required_module, install_packages):
    """Find a Python interpreter with ``required_module`` installed.

    Auto-installs ``install_packages`` if not present. Creates the unified
    venv as a last resort (handles PEP 668 externally-managed environments).

    Returns (path, version) or (None, None).
    """
    if required_module in _PYTHON_CACHE:
        return _PYTHON_CACHE[required_module]

    candidates = _collect_python_candidates()

    # Phase 1: find a Python that already has the required module
    for py in candidates:
        if not py or not os.path.isfile(py):
            continue
        ver = check_module(py, required_module)
        if ver:
            _PYTHON_CACHE[required_module] = (py, ver)
            return py, ver

    # Phase 2: find any working Python and auto-install deps
    for py in candidates:
        if not py or not os.path.isfile(py):
            continue
        pip_check = subprocess.run(
            [py, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=10,
            env=make_subprocess_env(), encoding="utf-8", errors="replace",
        )
        if pip_check.returncode != 0:
            continue

        print(f"  Auto-installing: {', '.join(install_packages)}")
        print(f"  Using: {py}")
        pip_install(py, install_packages)

        ver = check_module(py, required_module)
        if ver:
            _PYTHON_CACHE[required_module] = (py, ver)
            return py, ver

    # Phase 3: system Python is externally-managed (PEP 668) -> create venv
    for py in candidates:
        if not py or not os.path.isfile(py):
            continue
        ver_check = subprocess.run(
            [py, "--version"], capture_output=True, text=True, timeout=5,
            env=make_subprocess_env(), encoding="utf-8", errors="replace",
        )
        if ver_check.returncode == 0:
            print(f"  System Python is externally-managed, creating isolated venv...")
            venv_py, venv_ver = _create_venv(
                py, install_packages, verify_module=required_module,
            )
            if venv_py:
                _PYTHON_CACHE[required_module] = (venv_py, venv_ver)
                return venv_py, venv_ver
            break  # don't try more candidates if venv creation failed

    return None, None


def find_ffmpeg(python=None):
    """Find ffmpeg executable.

    Strategy: system PATH -> imageio-ffmpeg (auto-installed pip package with
    bundled binary). Returns the ffmpeg command/path, or None.
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
        except Exception as e:
            debug_log(f"ffmpeg probe failed for '{exe}': {e}")
            pass

    # 2. Try imageio-ffmpeg (bundled static ffmpeg binary)
    if python is None:
        python, _ = find_python("yt_dlp", ["yt-dlp", "requests", "pysocks", "imageio-ffmpeg"])
    if python:
        if not check_module(python, "imageio_ffmpeg"):
            print("  Auto-installing: imageio-ffmpeg (bundled ffmpeg binary)")
            pip_install(python, ["imageio-ffmpeg"])
        try:
            result = subprocess.run(
                [python, "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                capture_output=True, text=True, timeout=15,
                env=make_subprocess_env(), encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                if path and os.path.isfile(path):
                    _CACHED_FFMPEG = path
                    return path
        except Exception as e:
            debug_log(f"imageio-ffmpeg probe failed: {e}")
            pass

    return None


# ─── Proxy helpers ───────────────────────────────────────────────────────

def is_socks_proxy(proxy_url):
    """Check if proxy URL is a SOCKS proxy."""
    return bool(proxy_url) and proxy_url.startswith(
        ("socks5://", "socks5h://", "socks4://")
    )


def build_spotdl_proxy_args(proxy):
    """Return spotdl CLI args for a proxy URL.

    spotDL only accepts HTTP/HTTPS in --proxy. For SOCKS5 proxies we must
    use --yt-dlp-args instead, which yt-dlp reads directly.

    Returns a list of CLI tokens, e.g. ["--proxy", "http://..."] or
    ["--yt-dlp-args", "--proxy socks5://..."]. Empty list if no proxy.
    Shared by music_helper._build_spotdl_cmd and spotify_helper.run_spotdl.
    """
    if not proxy:
        return []
    if is_socks_proxy(proxy):
        return ["--yt-dlp-args", f"--proxy {proxy}"]
    return ["--proxy", proxy]


def proxy_to_env(proxy_url):
    """Convert proxy URL to environment variables for Python requests."""
    if is_socks_proxy(proxy_url):
        return {"ALL_PROXY": proxy_url}
    return {"HTTP_PROXY": proxy_url, "HTTPS_PROXY": proxy_url}


# ─── Language / URL detection ────────────────────────────────────────────

def is_chinese(text):
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def auto_select_platform(query):
    """Pick the default platform based on query language."""
    return "bilibili" if is_chinese(query) else "youtube"


def needs_proxy(platform):
    return platform in PROXY_PLATFORMS


def is_spotify_url(text):
    return bool(SPOTIFY_RE.search(text))


def is_netease_url(text):
    """Check if text contains a NetEase Cloud Music song URL."""
    return bool(NETEASE_RE.search(text))


def extract_netease_song_id(text):
    """Extract the numeric song ID from a NetEase URL. Returns str or None."""
    m = NETEASE_RE.search(text)
    return m.group(1) if m else None


def is_youtube_url(text):
    """Check if text is a direct YouTube video URL (not a search query)."""
    return bool(YOUTUBE_RE.search(text))


def is_soundcloud_url(text):
    """Check if text is a SoundCloud track URL."""
    return bool(SOUNDCLOUD_RE.search(text))


def is_bandcamp_url(text):
    """Check if text is a Bandcamp track URL."""
    return bool(BANDCAMP_RE.search(text))


def is_direct_download_url(text):
    """Check if text is a URL that yt-dlp can download directly (no search needed).

    Covers YouTube, SoundCloud, and Bandcamp. Spotify/NetEase need special handling.
    """
    return is_youtube_url(text) or is_soundcloud_url(text) or is_bandcamp_url(text)


# ─── Misc ────────────────────────────────────────────────────────────────

def sanitize_filename(name):
    """Sanitize a string for use as a filename (cross-platform safe)."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def derive_query_from_filename(filepath):
    """Derive a metadata search query from an audio file's name.

    Strips the extension, replaces dash separators (ASCII and CJK variants)
    with spaces, and removes parenthetical / bracketed annotations such as
    "(Live)" or "【MV】". Returns "" if nothing useful could be derived.

    Shared by the ``meta`` commands of music_helper and spotify_helper so the
    filename→query logic stays in one place.
    """
    base = os.path.splitext(os.path.basename(filepath))[0]
    base = re.sub(r"\s*[\-－—–]\s*", " ", base)
    base = re.sub(r"\s+\(.*?\)|\s+【.*?】|\s+\[.*?\]", "", base)
    return base.strip()


# ─── Subprocess helpers ───────────────────────────────────────────────────


def make_subprocess_env():
    """Return an ``os.environ`` copy with ``PYTHONIOENCODING=utf-8`` set.

    Shared by every ``subprocess.run`` / ``Popen`` call in the project so
    that the encoding boilerplate lives in one place.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_python_script(python, script, args=(), timeout=30):
    """Run a Python inline script (``-c``) with consistent encoding and env.

    Args:
        python:  path to Python interpreter
        script:  inline Python source (passed via ``-c``)
        args:    iterable of positional arguments placed in ``sys.argv``
        timeout: subprocess timeout in seconds

    Returns:
        ``subprocess.CompletedProcess``

    Raises:
        ``subprocess.TimeoutExpired`` on timeout; any ``OSError`` on spawn failure.
    """
    env = make_subprocess_env()
    cmd = [python, "-c", script] + [str(a) for a in args]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env=env, encoding="utf-8", errors="replace",
    )


# ─── Debug logging ───────────────────────────────────────────────────────

DEBUG_LOG_DIR = os.path.join(HOME, ".melodymine")
DEBUG_LOG_PATH = os.path.join(DEBUG_LOG_DIR, "last_run.log")
_DEBUG_ENABLED = False


def set_debug(enabled):
    """Toggle debug logging. When enabled, write a session log to last_run.log."""
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = enabled
    if enabled:
        os.makedirs(DEBUG_LOG_DIR, exist_ok=True)
        with open(DEBUG_LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"=== MelodyMine debug session — {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")


def debug_log(message):
    """Append a line to the debug log if debug mode is on."""
    if not _DEBUG_ENABLED:
        return
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(message.rstrip("\n") + "\n")
    except Exception:
        pass  # never let logging break the actual operation


def is_debug():
    return _DEBUG_ENABLED


def run_streaming(cmd, env=None):
    """Run a subprocess, streaming combined stdout+stderr to print in real time.

    Returns the exit code. In debug mode, also tee output to last_run.log.
    """
    if env is None:
        env = make_subprocess_env()
    if is_debug():
        debug_log(f"$ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        print(line, end="")
        if is_debug():
            debug_log(line.rstrip("\n"))
    proc.wait()
    if is_debug():
        debug_log(f"[exit code {proc.returncode}]")
    return proc.returncode

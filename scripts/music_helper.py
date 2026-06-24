#!/usr/bin/env python3
"""
MelodyMine - Multi-platform audio downloader.

Bilibili: wbi API search + yt-dlp download (direct access, no proxy needed)
YouTube:  yt-dlp search + download (proxy optional, needed in China)
spotDL:   Spotify URL pipeline (optional, has known bugs)

Usage:
    python scripts/music_helper.py check
    python scripts/music_helper.py search "周杰伦 稻香"
    python scripts/music_helper.py download "周杰伦 稻香"
    python scripts/music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://host:port
    python scripts/music_helper.py download "https://open.spotify.com/track/xxx"
    python scripts/music_helper.py download "周杰伦 稻香" --dry-run --json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from melodymine_common import (
    BILI_UA,
    DEFAULT_OUTPUT,
    DEP_COMPAT,
    PROXY_PLATFORMS,
    SPOTIFY_RE,
    auto_select_platform,
    check_module,
    check_version_compat,
    debug_log,
    find_ffmpeg,
    find_python,
    is_chinese,
    is_spotify_url,
    needs_proxy,
    pip_install,
    proxy_to_env,
    run_streaming,
    sanitize_filename,
    set_debug,
)

# ─── Dependencies ────────────────────────────────────────────────────────

# pip packages required for full functionality
REQUIRED_PACKAGES = ["yt-dlp", "requests", "pysocks"]
OPTIONAL_PACKAGES = ["imageio-ffmpeg", "spotdl"]


def _find_music_python():
    """Find a Python with yt-dlp (auto-installs deps + imageio-ffmpeg)."""
    return find_python("yt_dlp", REQUIRED_PACKAGES + ["imageio-ffmpeg"])


def ensure_deps():
    """Ensure all dependencies are available. Called at the start of every command.

    Returns (python, yt_dlp_ver, ffmpeg_path) or (None, None, None).
    """
    py, ver = _find_music_python()
    if not py:
        return None, None, None
    ff = find_ffmpeg(py)
    return py, ver, ff


def has_spotdl(python):
    """Return spotdl version string if installed, else None."""
    return check_module(python, "spotdl")


# ─── Command builders (shared by dry-run and real execution) ─────────────

def _build_ytdlp_cmd(
    python, url_or_query, output, fmt, bitrate=None,
    embed_thumbnail=True, proxy=None, bili_ua=False, index=1,
    cookies=None, ffmpeg_location=None,
):
    """Build the yt-dlp command list.

    Single source of truth for both dry-run preview and real execution.
    ``python`` is the interpreter path (or literal "python" for dry-run).
    ``ffmpeg_location`` is only added when ffmpeg isn't on the system PATH.
    """
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
    if ffmpeg_location and ffmpeg_location not in ("ffmpeg", "ffmpeg.exe"):
        cmd.extend(["--ffmpeg-location", ffmpeg_location])
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
    if cookies:
        cmd.extend(["--cookies", cookies])
    return cmd


def _build_spotdl_cmd(python, url, output, fmt, bitrate=None, proxy=None):
    """Build the spotdl download command list.

    Single source of truth for both dry-run preview and real execution.
    """
    cmd = [
        python, "-m", "spotdl", "download", url,
        "--output", output,
        "--format", fmt,
        "--print-errors",
    ]
    if bitrate:
        cmd.extend(["--bitrate", str(bitrate)])
    if proxy:
        if proxy.startswith("socks5"):
            cmd.extend(["--yt-dlp-args", f"--proxy {proxy}"])
        else:
            cmd.extend(["--proxy", proxy])
    return cmd


# ─── JSON / Plan helpers ─────────────────────────────────────────────────


def _emit_json(payload):
    """Print one machine-readable JSON line for agents."""
    print(json.dumps(payload, ensure_ascii=False))


def _download_plan(
    query, platform="auto", fmt="mp3", output=None, proxy=None, bitrate=None,
    index=1, embed_thumbnail=True, no_metadata=False, cookies=None,
):
    """Build a side-effect-free execution plan for dry-run and JSON reporting."""
    if not output:
        output = DEFAULT_OUTPUT

    if is_spotify_url(query):
        command = _build_spotdl_cmd("python", query, output, fmt, bitrate, proxy)
        return {
            "ok": True,
            "dry_run": True,
            "engine": "spotdl",
            "platform": "spotify",
            "query": query,
            "format": fmt,
            "output": output,
            "proxy": proxy,
            "cookies": cookies,
            "command": command,
            "notes": ["Spotify URLs are handled by spotDL."],
        }

    selected = auto_select_platform(query) if platform == "auto" else platform
    notes = []

    if selected == "bilibili":
        url_slot = "https://www.bilibili.com/video/<bvid>"
        notes.append("Bilibili dry-run: bvid is resolved at runtime via wbi search.")
        notes.append("If Bilibili search/download fails, MelodyMine falls back to YouTube.")
    else:
        url_slot = f"ytsearch:{query}"
        notes.append("YouTube: yt-dlp search + download in one step.")

    command = _build_ytdlp_cmd(
        "python", url_slot, output, fmt, bitrate,
        embed_thumbnail=embed_thumbnail,
        bili_ua=(selected == "bilibili"),
        index=index, proxy=proxy, cookies=cookies,
        # ffmpeg_location omitted on dry-run — it's a runtime-resolved path
    )

    return {
        "ok": True,
        "dry_run": True,
        "engine": "yt-dlp",
        "platform": selected,
        "query": query,
        "format": fmt,
        "output": output,
        "proxy": proxy,
        "cookies": cookies,
        "index": index,
        "embed_thumbnail": embed_thumbnail,
        "metadata": not no_metadata,
        "command": command,
        "notes": notes,
    }


def _print_plan(plan):
    print("=== MelodyMine dry run ===")
    print(f"Platform : {plan['platform']}")
    print(f"Engine   : {plan['engine']}")
    print(f"Query    : {plan['query']}")
    print(f"Format   : {plan['format']}")
    print(f"Output   : {plan['output']}")
    if plan.get("proxy"):
        print(f"Proxy    : {plan['proxy']}")
    if plan.get("cookies"):
        print(f"Cookies  : {plan['cookies']}")
    print("Command  : " + " ".join(str(part) for part in plan["command"]))
    for note in plan.get("notes", []):
        print(f"Note     : {note}")


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
        python, _ = _find_music_python()
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


# ─── MusicBrainz Metadata Lookup (free, no auth, excellent for English songs) ─────

_MB_SEARCH_SCRIPT = r"""
import json, sys, urllib.request, urllib.parse, time

query = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3

UA = "MelodyMine/1.0 (music-downloader; +https://github.com/thintsing/MelodyMine)"
time.sleep(0.5)

mb_query = urllib.parse.quote(query)
mb_url = f"https://musicbrainz.org/ws/2/recording/?query={mb_query}&limit={limit}&fmt=json"

req = urllib.request.Request(mb_url)
req.add_header("User-Agent", UA)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)

results = []
for rec in data.get("recordings", []):
    title = rec.get("title", "")
    ac = rec.get("artist-credit", [])
    artist = ac[0]["name"] if ac else ""
    releases = rec.get("releases", [])
    album = releases[0]["title"] if releases else ""
    release_mbid = releases[0]["id"] if releases else ""
    duration_ms = rec.get("length", 0)
    pic_url = ""
    if release_mbid:
        time.sleep(0.3)
        try:
            ca_req = urllib.request.Request(
                f"https://coverartarchive.org/release/{release_mbid}/front-500"
            )
            ca_req.add_header("User-Agent", UA)
            with urllib.request.urlopen(ca_req, timeout=10) as ca_resp:
                if ca_resp.status == 200:
                    pic_url = ca_resp.url
        except Exception:
            try:
                ca_req2 = urllib.request.Request(
                    f"https://coverartarchive.org/release/{release_mbid}/front"
                )
                ca_req2.add_header("User-Agent", UA)
                with urllib.request.urlopen(ca_req2, timeout=10) as ca_resp2:
                    if ca_resp2.status == 200:
                        pic_url = ca_resp2.url
            except Exception:
                pass
    if title and artist:
        results.append({
            "title": title, "artist": artist, "album": album,
            "duration": duration_ms, "pic_url": pic_url,
        })
print(json.dumps(results, ensure_ascii=False))
"""


def musicbrainz_lookup(query, python=None, limit=5):
    """
    Search MusicBrainz for song metadata (artist, album, cover art).
    Free, no API key, no authentication needed.
    Returns list of dicts: {title, artist, album, duration, pic_url}
    """
    if python is None:
        python, _ = _find_music_python()
    if not python:
        return []
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    parts = query.strip().split(None, 1)
    if len(parts) >= 2:
        mb_query = f'artist:"{parts[0]}" AND recording:"{parts[1]}" AND NOT (cover OR remix OR karaoke OR live OR tribute OR instrumental OR edit)'
    else:
        mb_query = f'recording:"{parts[0]}" AND NOT (cover OR remix OR karaoke OR live OR tribute)'
    try:
        result = subprocess.run(
            [python, "-c", _MB_SEARCH_SCRIPT, mb_query, str(limit)],
            capture_output=True, text=True, timeout=30,
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


# Chinese text normalization for robust artist/title comparison
_CHINESE_NORM_MAP = str.maketrans({
    '倫': '伦', '傑': '杰', '樂': '乐', '國': '国', '雲': '云',
    '會': '会', '個': '个', '時': '时', '間': '间', '說': '说',
    '話': '话', '愛': '爱', '點': '点', '萬': '万', '龍': '龙',
    '聲': '声', '體': '体', '學': '学', '問': '问', '車': '车',
    '門': '门', '開': '开', '關': '关', '風': '风', '飛': '飞',
    '馬': '马', '魚': '鱼', '鳥': '鸟', '與': '与', '從': '从',
    '來': '来', '東': '东', '發': '发', '電': '电', '燈': '灯',
    '當': '当', '後': '后', '書': '书', '長': '长', '見': '见',
    '貝': '贝', '麵': '面',
})


def _norm_cn(s):
    """Normalize Chinese text: map traditional → simplified for matching."""
    return s.translate(_CHINESE_NORM_MAP) if s else s


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
        python, _ = _find_music_python()
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
        python, _ = _find_music_python()
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


def itunes_search(query, limit=5):
    """
    Search iTunes Search API (free, no auth).
    Returns list of dicts with keys: artist, title, album, cover, date, genre
    or empty list on failure.
    """
    try:
        import urllib.request, urllib.parse, json
        url = "https://itunes.apple.com/search?" + urllib.parse.urlencode({
            "term": query, "media": "music", "limit": str(limit)
        })
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    results = []
    for r in data.get("results", []):
        artwork = r.get("artworkUrl100", "")
        # Upgrade cover resolution: 100x100 -> 600x600
        if artwork:
            artwork = artwork.replace("100x100bb", "600x600bb")
        results.append({
            "artist": r.get("artistName", "").strip(),
            "title": r.get("trackName", "").strip(),
            "album": r.get("collectionName", "").strip(),
            "cover": artwork,
            "date": r.get("releaseDate", "")[:10],
            "genre": r.get("primaryGenreName", ""),
            "duration_ms": r.get("trackTimeMillis", 0),
        })
    return results


def enhance_metadata(python, search_query, bili_title, output_dir):
    """
    Post-download metadata enhancement (multi-source strategy).

    Layer 1: Parse user's search query
    Layer 2: MusicBrainz + NetEase + iTunes queried concurrently, each scored
    Layer 3: Parse Bilibili video title (fallback for artist/title only)
    The highest-scoring source wins; ties broken by cover availability.
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

    # ── Layer 2: Multi-source lookup (concurrent) ──
    # MusicBrainz + NetEase + iTunes run in parallel to cut wait time.
    print(f"  Looking up album info (MusicBrainz + NetEase + iTunes in parallel)...")

    def _score_mb(results, artist, title):
        best_score, best_data = -1, None
        for r in results:
            r_artist = r.get("artist", "").strip()
            r_title = r.get("title", "").strip()
            score = 0
            if _norm_cn(r_artist) == _norm_cn(artist):
                score += 20
            elif _norm_cn(artist) in _norm_cn(r_artist):
                score += 8
            if _norm_cn(r_title) == _norm_cn(title):
                score += 5
            elif _norm_cn(title) in _norm_cn(r_title) or _norm_cn(r_title) in _norm_cn(title):
                score += 2
            if score > best_score:
                best_score, best_data = score, r
        return best_score, best_data

    def _score_ne(results, artist, title):
        best_score, best_data = -1, None
        for r in results:
            r_artist_raw = r.get("artist", "")
            r_artist = _clean_artist(r_artist_raw)
            r_title = r.get("title", "").strip()
            is_collaboration = "," in r_artist_raw or "，" in r_artist_raw
            score = 0
            if _norm_cn(r_artist) == _norm_cn(artist) and not is_collaboration:
                score += 20
            elif _norm_cn(r_artist) == _norm_cn(artist) and is_collaboration:
                score += 5
            elif _norm_cn(artist) in _norm_cn(r_artist_raw):
                score += 3
            if _norm_cn(r_title) == _norm_cn(title):
                score += 5
            elif _norm_cn(title) in _norm_cn(r_title) or _norm_cn(r_title) in _norm_cn(title):
                score += 2
            if score > best_score:
                best_score, best_data = score, r
        return best_score, best_data

    def _score_it(results, artist, title):
        best_score, best_data = -1, None
        for r in results:
            r_artist = r.get("artist", "").strip()
            r_title = r.get("title", "").strip()
            score = 0
            if _norm_cn(r_artist) == _norm_cn(artist):
                score += 20
            elif _norm_cn(artist) in _norm_cn(r_artist):
                score += 8
            if _norm_cn(r_title) == _norm_cn(title):
                score += 5
            elif _norm_cn(title) in _norm_cn(r_title) or _norm_cn(r_title) in _norm_cn(title):
                score += 2
            if r.get("cover"):
                score += 3  # has cover art
            if r.get("album"):
                score += 2  # has album name
            if score > best_score:
                best_score, best_data = score, r
        return best_score, best_data

    # Fire all three queries concurrently; each returns its raw results.
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_mb = pool.submit(musicbrainz_lookup, search_query, python=python, limit=5)
        fut_ne = pool.submit(metadata_lookup, search_query, python=python, limit=10)
        fut_it = pool.submit(itunes_search, search_query, limit=10)
        # Wait for all; exceptions in a source just mean empty results for it.
        try:
            mb_results = fut_mb.result() or []
        except Exception:
            mb_results = []
        try:
            ne_results = fut_ne.result() or []
        except Exception:
            ne_results = []
        try:
            it_results = fut_it.result() or []
        except Exception:
            it_results = []

    # Score each source's results (pure CPU, microseconds — no need to parallelize).
    best_mb_score, mb_data = _score_mb(mb_results, artist, title)
    best_ne_score, ne_data = _score_ne(ne_results, artist, title)
    best_it_score, it_data = _score_it(it_results, artist, title)

    if mb_data:
        print(f"    Best: {mb_data['artist']} - {mb_data['title']} [MusicBrainz (score={best_mb_score})]")
    else:
        print(f"    No results from MusicBrainz")
    if ne_data:
        print(f"    Best: {_clean_artist(ne_data['artist'])} - {ne_data['title']} [NetEase (score={best_ne_score})]")
    else:
        print(f"    No results from NetEase")
    if it_data:
        print(f"    Best: {it_data['artist']} - {it_data['title']} [iTunes (score={best_it_score})]")
    else:
        print(f"    No results from iTunes")

    # Pick the winner
    # Collect all candidates with (source_key, score, data)
    candidates = []
    if mb_data:
        candidates.append(("MusicBrainz", best_mb_score, mb_data))
    if ne_data:
        candidates.append(("NetEase", best_ne_score, ne_data))
    if it_data:
        candidates.append(("iTunes", best_it_score, it_data))

    if not candidates:
        album, pic_url, source = "", "", "parsed query"
    else:
        # Sort by score descending, then by cover availability descending
        def sort_key(item):
            src, score, data = item
            has_cover = 1 if (src == "iTunes" and data.get("cover")) or data.get("pic_url") else 0
            return (score, has_cover)

        candidates.sort(key=sort_key, reverse=True)
        source, best_score, best_data = candidates[0]

        if source == "MusicBrainz":
            pic_url = best_data.get("pic_url", "")
            album = best_data.get("album", "").strip()
        elif source == "NetEase":
            pic_url = best_data.get("pic_url", "")
            album = best_data.get("album", "").strip()
        else:  # iTunes
            pic_url = best_data.get("cover", "")
            album = best_data.get("album", "").strip()

    if album:
        print(f"  Album: {album} (from {source})")
    if pic_url:
        print(f"  Cover: available (from {source})")
    else:
        print(f"  Cover: not available")

    # ── Download album cover ──
    cover_path = None
    if pic_url:
        cover_path = download_cover(pic_url, python)
        if cover_path:
            print(f"  Downloaded album cover")

    # ── Set ID3 tags with ffmpeg ──
    ok = set_metadata(filepath, title=title, artist=artist, album=album, cover_path=cover_path)
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
                pass

    if cover_path and os.path.isfile(cover_path):
        try:
            os.remove(cover_path)
        except Exception:
            pass


# ─── yt-dlp Download ─────────────────────────────────────────────────────

def _ytdlp_download(
    python, url_or_query, output, fmt, bitrate=None,
    embed_thumbnail=True, proxy=None, bili_ua=False, index=1,
    cookies=None,
):
    """Run yt-dlp to download and convert audio. Returns True on success."""
    # Tell yt-dlp where ffmpeg is (critical when using imageio-ffmpeg).
    # This is the one arg that differs between dry-run (omitted) and real run.
    ffmpeg_exe = find_ffmpeg(python)

    cmd = _build_ytdlp_cmd(
        python, url_or_query, output, fmt, bitrate,
        embed_thumbnail=embed_thumbnail, proxy=proxy, bili_ua=bili_ua,
        index=index, cookies=cookies, ffmpeg_location=ffmpeg_exe,
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    return run_streaming(cmd, env=env) == 0


# ─── Bilibili API Direct Download (Tier 2: bypasses yt-dlp 412) ──────────

def _bili_api_download(bvid, output, fmt="mp3", bitrate=None, python=None):
    """Download audio directly from Bilibili's playurl API, bypassing yt-dlp entirely."""
    if python is None:
        python, _ = _find_music_python()
    if not python:
        return False
    import urllib.request, urllib.error
    print("    ↳ yt-dlp blocked (412) — trying Bilibili API direct download...")

    # Step 1: Resolve aid + cid
    view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    view_req = urllib.request.Request(view_url)
    view_req.add_header("User-Agent", BILI_UA)
    try:
        with urllib.request.urlopen(view_req, timeout=15) as resp:
            vd = json.loads(resp.read().decode("utf-8"))["data"]
            aid, cid = vd["aid"], vd["cid"]
    except Exception as e:
        print(f"    [!] Failed to get video info: {e}")
        return False
    print(f"    Resolved: aid={aid}, cid={cid}")

    # Step 2: Get audio stream URL
    playurl = f"https://api.bilibili.com/x/player/playurl?avid={aid}&cid={cid}&qn=16&fnver=0&fnval=4048&fourk=1"
    play_req = urllib.request.Request(playurl)
    play_req.add_header("User-Agent", BILI_UA)
    play_req.add_header("Referer", "https://www.bilibili.com/")
    try:
        with urllib.request.urlopen(play_req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    [!] Failed to get playurl: {e}")
        return False
    audio_streams = data.get("data", {}).get("dash", {}).get("audio", [])
    audio_streams.sort(key=lambda s: s.get("bandwidth", 0), reverse=True)
    if not audio_streams:
        print("    [!] No audio streams")
        return False
    audio_url = audio_streams[0]["baseUrl"]
    if not audio_url:
        print("    [!] No baseUrl")
        return False
    print(f"    Audio stream found (codec: {audio_streams[0].get('codecs', '?')})")

    # Step 3: Download
    os.makedirs(output, exist_ok=True)
    raw_path = os.path.join(output, f"_bili_raw_{aid}.m4a")
    print("    Downloading audio stream...")
    try:
        dl_req = urllib.request.Request(audio_url)
        dl_req.add_header("User-Agent", BILI_UA)
        dl_req.add_header("Referer", "https://www.bilibili.com/")
        with urllib.request.urlopen(dl_req, timeout=120) as resp:
            with open(raw_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
    except Exception as e:
        print(f"    [!] Download failed: {e}")
        if os.path.isfile(raw_path): os.remove(raw_path)
        return False
    file_size_mb = os.path.getsize(raw_path) / (1024 * 1024)
    print(f"    Downloaded: {file_size_mb:.1f} MB")
    if file_size_mb < 0.1:
        os.remove(raw_path)
        return False

    # Step 4: Convert
    ffmpeg_exe = find_ffmpeg(python)
    if not ffmpeg_exe or fmt == "m4a":
        final = os.path.join(output, f"bilibili_audio_{aid}.m4a")
        if raw_path != final: os.rename(raw_path, final)
        print(f"    Saved: {final}")
        return True

    print(f"    Converting to {fmt}...")
    final_path = os.path.join(output, f"bilibili_audio_{aid}.{fmt}")
    convert_cmd = [ffmpeg_exe, "-y", "-i", raw_path]
    if fmt == "mp3":
        convert_cmd.extend(["-codec:a", "libmp3lame"])
        convert_cmd.extend(["-qscale:a", "2"] if not bitrate else ["-b:a", str(bitrate)])
    elif fmt == "flac":
        convert_cmd.extend(["-codec:a", "flac"])
    elif fmt == "opus":
        convert_cmd.extend(["-codec:a", "libopus"])
    elif fmt == "vorbis":
        convert_cmd.extend(["-codec:a", "libvorbis"])
    elif fmt == "wav":
        convert_cmd.extend(["-codec:a", "pcm_s16le"])
    else:
        convert_cmd.extend(["-codec:a", "libmp3lame", "-qscale:a", "2"])
    convert_cmd.append(final_path)
    try:
        result = subprocess.run(convert_cmd, capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            print(f"    [!] FFmpeg failed: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"    [!] FFmpeg error: {e}")
        return False
    finally:
        if os.path.isfile(raw_path): os.remove(raw_path)

    print(f"    Converted: {os.path.getsize(final_path) / (1024 * 1024):.1f} MB ({fmt.upper()})")
    return True


# ─── Commands ────────────────────────────────────────────────────────────

def cmd_setup():
    """One-shot bootstrap: find Python, install all deps, get ffmpeg."""
    print("=" * 60)
    print("  MelodyMine — First-Time Setup")
    print("=" * 60)
    print()

    # Step 1: Find Python via the shared discovery (auto-installs deps)
    print("[1/4] Finding Python interpreter + installing dependencies...")
    py, ytdlp_ver = _find_music_python()
    if not py:
        print("  [FAIL] No Python found on this system.")
        print("         Install Python 3.10+ from https://python.org")
        return False
    print(f"  Found: {py}")
    if ytdlp_ver:
        print(f"  yt-dlp: v{ytdlp_ver}")
    print()

    # Step 2: Verify packages
    print("[2/4] Verifying Python packages...")
    for pkg, mod in [("yt-dlp", "yt_dlp"), ("requests", "requests"),
                      ("pysocks", "socks"), ("imageio-ffmpeg", "imageio_ffmpeg")]:
        ver = check_module(py, mod)
        if ver:
            print(f"  [OK]   {pkg:20s} {ver}")
        else:
            print(f"  [FAIL] {pkg:20s} not installed")
    print()

    # Step 3: Find ffmpeg
    print("[3/4] Locating ffmpeg...")
    # Force re-detection (clear cache)
    import melodymine_common as _mc
    _mc._CACHED_FFMPEG = None
    ff = find_ffmpeg(py)
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
    print(f'    python scripts/music_helper.py download "周杰伦 稻香"')
    print()
    print("  Platform availability:")
    has_yt = check_module(py, "yt_dlp")
    has_req = check_module(py, "requests")
    has_socks = check_module(py, "socks")
    if has_yt and ff:
        print("    [OK] Bilibili  (Chinese songs, no proxy needed)")
    if has_yt and has_socks and ff:
        print("    [OK] YouTube   (English songs, needs --proxy socks5://...)")
    if has_req:
        print("    [OK] NetEase   (metadata lookup for album/cover)")
    sp = has_spotdl(py)
    if sp:
        print(f"    [OK] Spotify   (via spotDL v{sp})")
    else:
        print("    [--] Spotify   (optional: pip install 'spotdl>=4.2.0,<5.0.0')")
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
        print("         Run: python scripts/music_helper.py setup")
        return False

    if ff:
        print(f"  [OK]   FFmpeg:        {ff}")
    else:
        print("  [FAIL] FFmpeg not found")
        return False

    # requests (for Bilibili wbi search)
    req_ver = check_module(py, "requests")
    if req_ver:
        print(f"  [OK]   requests:      v{req_ver} (for Bilibili API)")
    else:
        print("  [--]   requests:      not installed (auto-installs on first use)")

    # PySocks (for SOCKS5 proxy)
    socks_ver = check_module(py, "socks")
    if socks_ver:
        print(f"  [OK]   PySocks:       available (for SOCKS5 proxy)")
    else:
        print("  [--]   PySocks:       not installed (auto-installs on first use)")

    sp_ver = has_spotdl(py)
    if sp_ver:
        print(f"  [OK]   spotDL:        v{sp_ver}  (optional, for Spotify URLs)")
    else:
        print("  [--]   spotDL:        not installed (optional)")

    # ── Version compatibility checks ──
    print("\n  Version compatibility:")
    checks = []
    if ytdlp_ver:
        checks.append(("yt_dlp", "yt-dlp", ytdlp_ver))
    if sp_ver:
        checks.append(("spotdl", "spotdl", sp_ver))
    for mod, display, ver in checks:
        status, msg = check_version_compat(mod, ver)
        if status == "ok":
            print(f"  [OK]   {display:13s} v{ver}")
        elif status == "warn":
            print(f"  [WARN] {display:13s} {msg}")
        else:
            print(f"  [FAIL] {display:13s} {msg}")

    print("\n  Platforms:")
    print("    - Bilibili  (Chinese songs, no proxy needed)")
    print("    - YouTube   (English songs, proxy optional — needed in China)")
    print("    - Spotify URL  (optional, via spotDL)")

    # ── External API health probe ──
    print("\n  External API reachability:")
    _check_api_health(py)

    print("\n=== Ready! ===")
    return True


def _check_api_health(python):
    """Concurrently probe the external APIs MelodyMine depends on.

    Reports each as [OK]/[FAIL] with latency, so users can self-diagnose
    whether a download failure is caused by a blocked/dead API rather than
    a local issue. Read-only, never installs anything, never blocks long.
    """
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor, as_completed

    probes = {
        "Bilibili": "https://api.bilibili.com/x/web-interface/nav",
        "NetEase":  "https://music.163.com",
        "iTunes":   "https://itunes.apple.com/search?term=test&limit=1",
        "MusicBrainz": "https://musicbrainz.org/ws/2/recording/?query=test&limit=1&fmt=json",
    }

    def _probe(name, url):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "MelodyMine/1.0 (health check)")
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=8) as resp:
                resp.read(1)  # read one byte to confirm response
            ms = (time.time() - t0) * 1000
            return name, True, f"{ms:.0f}ms"
        except Exception as e:
            return name, False, str(e)[:60]

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_probe, n, u) for n, u in probes.items()]
        results = {}
        for fut in as_completed(futures, timeout=12):
            try:
                name, ok, info = fut.result()
                results[name] = (ok, info)
            except Exception:
                pass  # timeout on a single probe

    for name in probes:  # print in stable order
        if name in results:
            ok, info = results[name]
            status = "[OK]  " if ok else "[FAIL]"
            print(f"    {status} {name:12s} {info}")
        else:
            print(f"    [FAIL] {name:12s} timed out (>12s)")


def cmd_search(query, platform="auto", limit=5, proxy=None):
    """Search for songs and print results."""
    py, _, _ = ensure_deps()
    if not py:
        print("ERROR: No Python with yt-dlp found. Run 'setup' first:")
        print("  python scripts/music_helper.py setup")
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
    no_metadata=False, cookies=None, dry_run=False, json_output=False,
    debug=False,
):
    """Download a song with automatic platform selection and fallback."""
    if debug:
        set_debug(True)
        debug_log(f"cmd_download: query={query!r} platform={platform} fmt={fmt} proxy={proxy}")

    if dry_run:
        plan = _download_plan(
            query, platform, fmt, output, proxy, bitrate, index,
            embed_thumbnail, no_metadata, cookies,
        )
        if json_output:
            _emit_json(plan)
        else:
            _print_plan(plan)
        return plan

    py, _, _ = ensure_deps()
    if not py:
        print("ERROR: No Python with yt-dlp found. Run 'setup' first:")
        print("  python scripts/music_helper.py setup")
        sys.exit(1)
    debug_log(f"python={py}")

    # ── Spotify URL → spotDL ──
    if is_spotify_url(query):
        debug_log("route: spotify → spotdl")
        return _download_via_spotdl(py, query, fmt, output, proxy, bitrate)

    if platform == "auto":
        platform = auto_select_platform(query)
        debug_log(f"auto-selected platform: {platform}")

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
                no_metadata=no_metadata, cookies=cookies,
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
            bili_ua=True, index=1, cookies=cookies,
        )
        if ok:
            if not no_metadata:
                enhance_metadata(py, query, item["title"], output)
            print(f"\n[OK] Download complete!")
            print(f"     Files saved to: {output}")
            return {
                "ok": True,
                "platform": "bilibili",
                "engine": "yt-dlp",
                "query": query,
                "source_url": url,
                "format": fmt,
                "output": output,
                "proxy": proxy,
                "cookies": cookies,
                "metadata": not no_metadata,
                "fallback": False,
            }

        # Tier 2: Bilibili API direct download
        print(f"\n  yt-dlp download failed (likely 412 Precondition Failed).")
        ok_api = _bili_api_download(
            item["bvid"], output, fmt, bitrate,
            python=py,
        )
        if ok_api:
            if not no_metadata:
                enhance_metadata(py, query, item["title"], output)
            print(f"\n[OK] Download complete (via Bilibili API direct)!")
            print(f"     Files saved to: {output}")
            return {
                "ok": True, "platform": "bilibili", "engine": "bili-api-direct",
                "query": query, "source_url": f"https://www.bilibili.com/video/{item['bvid']}",
                "format": fmt, "output": output,
                "metadata": not no_metadata, "fallback": "bili-api-direct",
            }

        # Tier 3: YouTube fallback
        print(f"\n  Bilibili all tiers failed. Falling back to YouTube...")
        return _do_youtube_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata, cookies=cookies,
        )

    # ── YouTube ──
    else:
        return _do_youtube_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata, cookies=cookies,
        )


def _do_youtube_download(
    py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
    no_metadata=False, cookies=None,
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
    if cookies:
        print(f"  Cookies  : {cookies}")
    print("=" * 60)
    print()

    ok = _ytdlp_download(
        py, search_query, output, fmt, bitrate, embed_thumbnail,
        proxy=proxy, index=index, cookies=cookies,
    )
    if ok:
        if not no_metadata:
            enhance_metadata(py, query, "", output)
        print(f"\n[OK] Download complete!")
        print(f"     Files saved to: {output}")
        return {
            "ok": True,
            "platform": "youtube",
            "engine": "yt-dlp",
            "query": query,
            "source_url": search_query,
            "format": fmt,
            "output": output,
            "proxy": proxy,
            "cookies": cookies,
            "metadata": not no_metadata,
        }

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
        pip_install(python, ["spotdl>=4.2.0,<5.0.0"])
        sp_ver = has_spotdl(python)
    if not sp_ver:
        print("ERROR: spotDL installation failed.")
        print("       Try manually: pip install spotdl")
        print("       Or search by song name instead of Spotify URL.")
        sys.exit(1)

    if not output:
        output = DEFAULT_OUTPUT
    os.makedirs(output, exist_ok=True)

    cmd = _build_spotdl_cmd(python, url, output, fmt, bitrate, proxy)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if proxy and proxy.startswith("socks5"):
        env["ALL_PROXY"] = proxy

    print("=" * 60)
    print("  Engine   : spotDL (Spotify URL)")
    print(f"  URL      : {url}")
    print(f"  Format   : {fmt}")
    print(f"  Output   : {output}")
    if proxy:
        print(f"  Proxy    : {proxy}")
    print("=" * 60)
    print()

    exit_code = run_streaming(cmd, env=env)

    if exit_code != 0:
        print(f"\n[FAIL] spotDL exited with code {exit_code}")
        print("\n--- Common spotDL Issues ---")
        print("  1. KeyError 'uri'   -> SpotipyFree API bug")
        print("  2. YouTube blocked  -> Ensure proxy is working")
        print("  3. Fallback         -> Search by song name instead of Spotify URL")
        sys.exit(1)

    print(f"\n[OK] Download complete!")
    print(f"     Files saved to: {output}")
    return {
        "ok": True,
        "platform": "spotify",
        "engine": "spotdl",
        "query": url,
        "source_url": url,
        "format": fmt,
        "output": output,
        "proxy": proxy,
        "cookies": None,
        "metadata": True,
    }


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
  download "周杰伦 稻香" --dry-run           Preview the command without executing
  download "周杰伦 稻香" --dry-run --json    Machine-readable plan for agents
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
    p_dl.add_argument("--cookies", default=None, help="cookies.txt path for YouTube sign-in/bot checks")
    p_dl.add_argument("--bitrate", default=None, help="Audio bitrate (e.g. 320K)")
    p_dl.add_argument("--index", type=int, default=1, help="Search result index (1-based)")
    p_dl.add_argument("--no-thumbnail", action="store_true")
    p_dl.add_argument("--no-metadata", action="store_true",
                      help="Skip metadata enhancement (multi-source lookup + ID3 tags + rename)")
    p_dl.add_argument("--dry-run", action="store_true",
                      help="Print the command that would run without executing")
    p_dl.add_argument("--json", action="store_true",
                      help="Output machine-readable JSON (use with --dry-run or after download)")
    p_dl.add_argument("--debug", action="store_true",
                      help="Write a session log to ~/.melodymine/last_run.log for troubleshooting")

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
        result = cmd_download(
            args.query,
            platform=args.platform,
            fmt=args.format,
            output=args.output,
            proxy=args.proxy,
            cookies=args.cookies,
            bitrate=args.bitrate,
            index=args.index,
            embed_thumbnail=not args.no_thumbnail,
            no_metadata=args.no_metadata,
            dry_run=args.dry_run,
            json_output=args.json,
            debug=args.debug,
        )
        # Emit JSON for non-dry-run successful downloads (dry-run already emitted).
        if args.json and not args.dry_run and isinstance(result, dict):
            _emit_json(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

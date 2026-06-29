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
    auto_select_platform,
    build_spotdl_proxy_args,
    check_module,
    check_version_compat,
    debug_log,
    derive_query_from_filename,
    extract_netease_song_id,
    find_ffmpeg,
    find_python,
    is_bandcamp_url,
    is_direct_download_url,
    is_netease_url,
    is_soundcloud_url,
    is_spotify_url,
    is_youtube_url,
    make_subprocess_env,
    pip_install,
    proxy_to_env,
    run_streaming,
    sanitize_filename,
    set_debug,
)

import bili_client
import cover_client
import mbrainz_client
import netease_client
import soulseek_client
import ytmusic_client

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
    cmd.extend(build_spotdl_proxy_args(proxy))
    return cmd


# ─── JSON / Plan helpers ─────────────────────────────────────────────────


def _emit_json(payload):
    """Print one machine-readable JSON line for agents."""
    print(json.dumps(payload, ensure_ascii=False))


def _download_plan(
    query, platform="auto", fmt="flac", output=None, proxy=None, bitrate=None,
    index=1, embed_thumbnail=True, no_metadata=False, cookies=None,
):
    """Build a side-effect-free execution plan for dry-run and JSON reporting."""
    if not output:
        output = DEFAULT_OUTPUT

    # ``auto`` is resolved at runtime by probing the source codec (network).
    # The dry-run is side-effect-free, so it can't probe — substitute a
    # representative concrete format so the printed command is valid, keep
    # ``format`` as ``auto`` in the JSON to reflect user intent, and note
    # that the real choice happens at runtime.
    auto_note = None
    cmd_fmt, cmd_bitrate = fmt, bitrate
    if fmt == "auto":
        cmd_fmt, cmd_bitrate, _ = _resolve_auto_fmt(None, bitrate)
        auto_note = ("Format 'auto' resolves at runtime by probing the source "
                     "codec: flac if lossless, else mp3 320K. "
                     "Preview command uses mp3 as a representative.")

    if is_spotify_url(query):
        command = _build_spotdl_cmd("python", query, output, cmd_fmt, cmd_bitrate, proxy)
        notes = ["Spotify URLs are handled by spotDL."]
        if auto_note:
            notes.append(auto_note)
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
            "notes": notes,
        }

    # NetEase URLs are resolved at runtime (requires network), so dry-run just notes it.
    netease_resolved = is_netease_url(query)

    # Direct download URLs (YouTube/SoundCloud/Bandcamp) skip search entirely.
    if is_direct_download_url(query):
        if is_youtube_url(query):
            src = "YouTube"
        elif is_soundcloud_url(query):
            src = "SoundCloud"
        else:
            src = "Bandcamp"
        command = _build_ytdlp_cmd(
            "python", query, output, cmd_fmt, cmd_bitrate,
            embed_thumbnail=embed_thumbnail, proxy=proxy, cookies=cookies,
            index=index,
        )
        return {
            "ok": True,
            "dry_run": True,
            "engine": "yt-dlp",
            "platform": src.lower(),
            "query": query,
            "format": fmt,
            "output": output,
            "proxy": proxy,
            "cookies": cookies,
            "index": index,
            "embed_thumbnail": embed_thumbnail,
            "metadata": not no_metadata,
            "command": command,
            "notes": [f"{src}: direct URL download via yt-dlp (no search step)."] + ([auto_note] if auto_note else []),
        }

    selected = auto_select_platform(query) if platform == "auto" else platform
    notes = []

    if selected == "bilibili":
        url_slot = "https://www.bilibili.com/video/<bvid>"
        notes.append("Bilibili dry-run: bvid is resolved at runtime via wbi search.")
        notes.append("Priority: Soulseek → Bilibili → YouTube.")
    else:
        url_slot = f"ytsearch:{query}"
        notes.append("Priority: Soulseek → YouTube (yt-dlp search + download).")

    if netease_resolved:
        notes.append("NetEase URL: resolved to song name at runtime, then downloaded via Bilibili/YouTube.")

    command = _build_ytdlp_cmd(
        "python", url_slot, output, cmd_fmt, cmd_bitrate,
        embed_thumbnail=embed_thumbnail,
        bili_ua=(selected == "bilibili"),
        index=index, proxy=proxy, cookies=cookies,
        # ffmpeg_location omitted on dry-run — it's a runtime-resolved path
    )

    if auto_note:
        notes.append(auto_note)

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


# ─── Metadata Enhancement (NetEase Music API + Title Parsing) ────────────

# ─── MusicBrainz Metadata Lookup (free, no auth, excellent for English songs) ─────

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


# English articles that should be grouped with the following token as the
# artist name, e.g. "The Weeknd Blinding Lights" -> ("The Weeknd", "Blinding Lights").
_ARTICLES = {"the", "a", "an"}


def parse_search_query(query):
    """
    Parse a user search query to extract artist and title.
    "周杰伦 稻香"                -> ("周杰伦", "稻香")
    "The Weeknd Blinding Lights" -> ("The Weeknd", "Blinding Lights")
    "稻香"                        -> (None, "稻香")

    For Chinese: first token = artist, rest = title
    For English: if the first token is an article (The/A/An), group it with the
    next token as the artist name.
    """
    parts = query.strip().split()
    if len(parts) >= 2:
        artist = parts[0]
        title = " ".join(parts[1:])
        # Group a leading English article with the next token so band names like
        # "The Weeknd", "The Beatles", "A Tribe Called Quest" stay intact.
        if artist.lower() in _ARTICLES and len(parts) >= 3:
            artist = f"{parts[0]} {parts[1]}"
            title = " ".join(parts[2:])
        return artist, title
    return None, query.strip()

def resolve_netease_url(url):
    """Resolve a NetEase song URL to an 'Artist Title' search query.

    Returns a query string (e.g. "周杰伦 稻香") or None on failure.
    """
    song_id = extract_netease_song_id(url)
    if not song_id:
        return None
    data = netease_client.detail(song_id)
    if not data:
        return None
    artist = _clean_artist(data.get("artist", ""))
    title = data.get("title", "").strip()
    if artist and title:
        return f"{artist} {title}"
    if title:
        return title
    return None


# ─── Bilibili result ranking (deprioritise accompaniment/instrumental) ───

# Keywords that indicate a search result is an accompaniment, instrumental, or
# karaoke version rather than the original song with vocals.
_ACCOMPANIMENT_RE = re.compile(
    r"伴奏|纯音乐|卡拉OK|卡拉ok|karaoke|instrumental|backing\s*track|"
    r"accompaniment|off\s*vocal|无人声|消音|静音版?",
    re.IGNORECASE,
)


def _is_accompaniment(title):
    """Return True if a Bilibili video title looks like an accompaniment /
    instrumental / karaoke version (no lead vocals)."""
    return bool(_ACCOMPANIMENT_RE.search(title or ""))


def rank_bili_results(results):
    """Reorder Bilibili search results so non-accompaniment entries come first.

    Within each group (vocal / accompaniment) results keep their original
    API order, which already reflects Bilibili relevance. This means the
    default --index 1 picks the most relevant *vocal* version instead of a
    backing track that happened to rank highest.

    Returns a new list; does not mutate the input. Prints nothing.
    """
    vocal = [r for r in results if not _is_accompaniment(r.get("title", ""))]
    accomp = [r for r in results if _is_accompaniment(r.get("title", ""))]
    return vocal + accomp


# Noise patterns to strip from Bilibili titles (pre-compiled for performance).
_NOISE_PATTERNS = [re.compile(p) for p in [
    r"完整版", r"无损音质", r"无损", r"高清", r"超清", r"高品质",
    r"官方MV", r"官方", r"\bMV\b", r"\bOfficial\b", r"\bHD\b",
    r"\bLyrics?\b", r"歌词版?", r"歌词", r"现场版?", r"\bLive\b",
    r"纯音乐", r"伴奏", r"翻唱", r"字幕版?", r"音频版?", r"音频",
    r"\(.*?\)", r"（.*?）", r"【.*?】", r"［.*?］",
    r"\d{4}", r"｜.*", r"\|.*",
]]


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


_AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".opus", ".wav", ".vorbis", ".ogg", ".webm"}


def _list_audio_files(output_dir):
    """Return a set of absolute path strings for audio files currently in output_dir.

    Used to snapshot the directory *before* a download so that
    find_downloaded_file can identify only the newly-created file(s)
    afterward, ignoring pre-existing audio.
    """
    p = Path(output_dir)
    if not p.exists():
        return set()
    return {str(f) for f in p.iterdir() if f.is_file() and f.suffix.lower() in _AUDIO_EXTS}


def find_downloaded_file(output_dir, before=None):
    """Find the most recently downloaded audio file in output_dir.

    yt-dlp sets each file's mtime to the source upload date (not the download
    time), so sorting by mtime can pick a pre-existing file whose upload date
    is newer than the just-downloaded one — and metadata would then be written
    to the wrong file. To avoid this, pass ``before``: a set of file paths
    captured by _list_audio_files *before* the download; only files not in
    that snapshot are considered. Recency falls back to ctime (creation/change
    time), which better reflects the actual download time than mtime.
    """
    output_path = Path(output_dir)
    if not output_path.exists():
        return None
    files = [f for f in output_path.iterdir()
             if f.is_file() and f.suffix.lower() in _AUDIO_EXTS]
    if before:
        files = [f for f in files if str(f) not in before]
    if not files:
        return None
    files.sort(key=lambda f: f.stat().st_ctime, reverse=True)
    return str(files[0])


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


# ─── Metadata scoring (shared by enhance_metadata, testable independently) ──


def _score_metadata_candidate(r, artist, title, *, collaboration_aware=False, bonus_fields=False):
    """Score a single metadata result (from MusicBrainz / NetEase / iTunes)
    against a parsed artist/title pair.

    - collaboration_aware: for NetEase, which returns comma-joined multi-artist
      strings — reduces the exact-artist score and uses the raw (uncleaned)
      artist for the contains check.
    - bonus_fields: for iTunes, adds small bonuses for having cover art and
      an album name.
    """
    # Guard: empty query artist/title can never produce a meaningful match.
    # (Python's ``"" in "anything"`` is always True — a phantom match.)
    if not artist or not title:
        return 0

    r_artist_raw = r.get("artist") or ""
    if collaboration_aware:
        r_artist = _clean_artist(r_artist_raw)
    else:
        r_artist = r_artist_raw.strip()
    r_title = (r.get("title") or "").strip()
    is_collab = collaboration_aware and ("," in r_artist_raw or "，" in r_artist_raw)

    score = 0
    if _norm_cn(r_artist) == _norm_cn(artist):
        score += 5 if is_collab else 20
    elif collaboration_aware:
        # NetEase path: match against the raw (comma-joined) artist string,
        # exactly as the original _score_ne did — never the +8 branch.
        if _norm_cn(artist) in _norm_cn(r_artist_raw):
            score += 3
    elif _norm_cn(artist) in _norm_cn(r_artist):
        score += 8

    if _norm_cn(r_title) == _norm_cn(title):
        score += 5
    elif _norm_cn(title) in _norm_cn(r_title) or _norm_cn(r_title) in _norm_cn(title):
        score += 2

    if bonus_fields:
        cover = r.get("cover") or r.get("pic_url")
        if cover:
            score += 3  # has cover art
        if r.get("album"):
            score += 2  # has album name
    return score


def _best_metadata_candidate(results, artist, title, **kwargs):
    """Return ``(best_score, best_data)`` across a list of metadata results
    using ``_score_metadata_candidate``.  Returns ``(-1, None)`` when the
    list is empty.

    Extra keyword arguments are forwarded to ``_score_metadata_candidate``
    so callers can enable ``collaboration_aware`` or ``bonus_fields``.
    """
    best_score, best_data = -1, None
    for r in results:
        score = _score_metadata_candidate(r, artist, title, **kwargs)
        if score > best_score:
            best_score, best_data = score, r
    return best_score, best_data


def enhance_metadata(search_query, bili_title, output_dir, embed_thumbnail=True, filepath=None, before_snapshot=None):
    """
    Post-download metadata enhancement (multi-source strategy).

    Layer 1: Parse user's search query
    Layer 2: MusicBrainz + NetEase + iTunes queried concurrently, each scored
    Layer 3: Parse Bilibili video title (fallback for artist/title only)
    The highest-scoring source wins; ties broken by cover availability.
    When ``embed_thumbnail`` is False, cover art is neither downloaded nor
    embedded (respects --no-thumbnail).
    Never raises — metadata enhancement is best-effort.

    If ``filepath`` is provided, it is used directly; otherwise the most
    recently created audio file in ``output_dir`` is enhanced. Pass
    ``before_snapshot`` (from _list_audio_files, captured before the
    download) so the newly-downloaded file is identified correctly even
    when the output dir already holds older audio.
    """
    if filepath is None:
        filepath = find_downloaded_file(output_dir, before=before_snapshot)
    if not filepath:
        print("  [!] Could not find downloaded file for metadata")
        return
    if not os.path.isfile(filepath):
        print(f"  [!] File not found: {filepath}")
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

    # Fire all three queries concurrently; each returns its raw results.
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_mb = pool.submit(mbrainz_client.lookup, search_query, 5)
        fut_ne = pool.submit(netease_client.search, search_query, 10)
        fut_it = pool.submit(itunes_search, search_query, 10)
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
    best_mb_score, mb_data = _best_metadata_candidate(mb_results, artist, title)
    best_ne_score, ne_data = _best_metadata_candidate(ne_results, artist, title, collaboration_aware=True)
    best_it_score, it_data = _best_metadata_candidate(it_results, artist, title, bonus_fields=True)

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
    if embed_thumbnail and pic_url:
        cover_path = cover_client.download(pic_url)
        if cover_path:
            print(f"  Downloaded album cover")
    elif not embed_thumbnail:
        print(f"  Cover: skipped (--no-thumbnail)")

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

    env = make_subprocess_env()

    return run_streaming(cmd, env=env) == 0


# ─── Shared ffmpeg conversion ────────────────────────────────────────────

# ffmpeg codec mapping shared by all direct-download converters.
_FMT_CODEC = {
    "mp3": "libmp3lame",
    "flac": "flac",
    "opus": "libopus",
    "vorbis": "libvorbis",
    "wav": "pcm_s16le",
    "m4a": "aac",
}


def _ffmpeg_convert(ffmpeg_exe, raw_path, final_path, fmt, bitrate=None):
    """Convert a raw audio file to the target format via ffmpeg.

    Shared by the Bilibili API direct and NetEase direct download paths.
    Removes ``raw_path`` on success or failure. Returns True on success.
    For lossy formats (mp3/opus/vorbis) ``bitrate`` is applied when given;
    mp3 without a bitrate uses VBR quality 2.
    """
    convert_cmd = [ffmpeg_exe, "-y", "-i", raw_path, "-codec:a", _FMT_CODEC.get(fmt, "libmp3lame")]
    if fmt == "mp3":
        convert_cmd.extend(["-b:a", str(bitrate)] if bitrate else ["-qscale:a", "2"])
    elif bitrate:
        convert_cmd.extend(["-b:a", str(bitrate)])
    convert_cmd.append(final_path)
    try:
        result = subprocess.run(
            convert_cmd, capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            print(f"    [!] FFmpeg failed: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"    [!] FFmpeg error: {e}")
        return False
    finally:
        if os.path.isfile(raw_path):
            os.remove(raw_path)

    print(f"    Converted: {os.path.getsize(final_path) / (1024 * 1024):.1f} MB ({fmt.upper()})")
    return True


# ─── Auto format: detect lossless vs lossy source ────────────────────────

# Codec substrings that indicate a genuinely lossless source stream.
_LOSSLESS_CODEC_RE = re.compile(r"flac|alac|pcm_|\bpcm\b|wav|aiff|truehd", re.IGNORECASE)


def _auto_fmt_from_codec(codec):
    """Decide the output format + bitrate for ``--format auto``.

    Real lossless sources (flac/alac/wav/pcm) are kept as flac; everything
    else (AAC/Opus/MP3) is encoded to mp3 320K — no more fake-lossless upcast.

    Returns ``(fmt, bitrate, reason)``.
    """
    c = codec or ""
    if c and _LOSSLESS_CODEC_RE.search(c):
        return "flac", None, f"源音频 {c} 为无损 → 保留无损 (flac)"
    return "mp3", "320K", (f"源音频 {c} 为有损 → mp3 320K" if c else "源音频格式未知 → 按 mp3 320K 处理")


def _bili_resolve_audio(bvid, python=None):
    """Resolve a Bilibili video to (audio_url, codec) of its best audio stream.

    Uses the official playurl API (cheap, no yt-dlp). Returns (None, None) on
    failure. Shared by the auto-format probe and the Bilibili API direct
    download path.
    """
    import urllib.request
    try:
        view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        view_req = urllib.request.Request(view_url)
        view_req.add_header("User-Agent", BILI_UA)
        with urllib.request.urlopen(view_req, timeout=15) as resp:
            vd = json.loads(resp.read().decode("utf-8"))["data"]
            aid, cid = vd["aid"], vd["cid"]
        playurl = (
            "https://api.bilibili.com/x/player/playurl"
            f"?avid={aid}&cid={cid}&qn=16&fnver=0&fnval=4048&fourk=1"
        )
        play_req = urllib.request.Request(playurl)
        play_req.add_header("User-Agent", BILI_UA)
        play_req.add_header("Referer", "https://www.bilibili.com/")
        with urllib.request.urlopen(play_req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None, None
    audio_streams = data.get("data", {}).get("dash", {}).get("audio", [])
    audio_streams.sort(key=lambda s: s.get("bandwidth", 0), reverse=True)
    if not audio_streams:
        return None, None
    return audio_streams[0].get("baseUrl"), audio_streams[0].get("codecs", "")


def _probe_ytdlp_codec(python, target, index=1, timeout=30, proxy=None, cookies=None):
    """Probe the audio codec yt-dlp would download for ``target``.

    Runs ``yt-dlp -J`` (metadata only, no download) and inspects the best
    audio-only format. Returns a codec string (e.g. ``flac``, ``opus``,
    ``mp4a.40.2``) or None on failure.
    """
    cmd = [
        python, "-m", "yt_dlp", "-J", "--no-warnings",
        "--playlist-items", str(index), target,
    ]
    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies:
        cmd.extend(["--cookies", cookies])
    env = make_subprocess_env()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=env, encoding="utf-8", errors="replace",
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except Exception:
        return None
    # Playlist / search result → pick the chosen entry.
    if isinstance(data, dict) and data.get("_type") == "playlist":
        entries = [e for e in (data.get("entries") or []) if e]
        if not entries:
            return None
        data = entries[min(index - 1, len(entries) - 1)]
    if not isinstance(data, dict):
        return None
    # requested_formats = what yt-dlp actually selected (most accurate).
    req = data.get("requested_formats") or []
    audio_req = [f for f in req if f.get("vcodec") == "none"]
    if audio_req:
        return audio_req[0].get("acodec") or audio_req[0].get("ext")
    # Otherwise pick the best audio-only format from the full list.
    formats = data.get("formats") or []
    audio_fmts = [
        f for f in formats
        if f.get("vcodec") == "none" and f.get("acodec") and f.get("acodec") != "none"
    ]
    pool = audio_fmts or formats
    if not pool:
        return data.get("acodec") or data.get("ext")
    best = max(pool, key=lambda f: (f.get("abr") or 0))
    return best.get("acodec") or best.get("ext")


def _resolve_auto_fmt(codec, user_bitrate):
    """Resolve ``auto`` → concrete (fmt, bitrate) honoring a user override.

    ``user_bitrate`` (may be None) always wins over the auto-chosen bitrate.
    """
    fmt, auto_br, reason = _auto_fmt_from_codec(codec)
    bitrate = user_bitrate or auto_br
    return fmt, bitrate, reason


# ─── Bilibili API Direct Download (Tier 2: bypasses yt-dlp 412) ──────────

def _bili_api_download(bvid, output, fmt="flac", bitrate=None, python=None):
    """Download audio directly from Bilibili's playurl API, bypassing yt-dlp entirely."""
    if python is None:
        python, _ = _find_music_python()
    if not python:
        return False
    import urllib.request
    print("    -> yt-dlp blocked (412) - trying Bilibili API direct download...")

    # Step 1+2: Resolve audio stream URL + codec (shared with auto-format probe).
    audio_url, codec = _bili_resolve_audio(bvid, python=python)
    if not audio_url:
        print("    [!] Could not resolve Bilibili audio stream (no audio streams)")
        return False
    print(f"    Audio stream found (codec: {codec or '?'})")

    # Resolve auto format from the real codec.
    if fmt == "auto":
        fmt, bitrate, reason = _resolve_auto_fmt(codec, bitrate)
        print(f"    [auto] {reason}")
    aid = bvid  # used for temp filename; aid unknown here without extra call

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

    # Step 4: Convert (or keep raw if target is m4a / lossless flac from flac source)
    ffmpeg_exe = find_ffmpeg(python)
    if not ffmpeg_exe or fmt == "m4a":
        final = os.path.join(output, f"bilibili_audio_{aid}.m4a")
        if raw_path != final: os.rename(raw_path, final)
        print(f"    Saved: {final}")
        return True

    print(f"    Converting to {fmt}...")
    final_path = os.path.join(output, f"bilibili_audio_{aid}.{fmt}")
    return _ffmpeg_convert(ffmpeg_exe, raw_path, final_path, fmt, bitrate)


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
        results = bili_client.search(query, limit=limit)
        if results:
            results = rank_bili_results(results)
            for i, r in enumerate(results, 1):
                tag = " [伴奏/纯音乐]" if _is_accompaniment(r.get("title", "")) else ""
                print(f"  {i}. [{r['duration']}] {r['title']}{tag}")
                print(f"     Uploader: {r['uploader']} | Plays: {r['play']} | bvid: {r['bvid']}")
                print()
            print(f"Top {len(results)} results. Use --index N to download a specific result.")
            print("Tip: 伴奏/纯音乐结果已排到列表后方，默认下载带人声版本。")
        else:
            print("No results or search failed.")
            print("Tip: Try --platform youtube --proxy socks5://host:port")
    elif platform == "ytmusic":
        results = ytmusic_client.search(query, limit=limit)
        if results:
            for i, r in enumerate(results, 1):
                dur = r.get("duration") or "?"
                dur_str = f"{dur//60}:{dur%60:02d}" if isinstance(dur, int) else str(dur)
                print(f"  {i}. [{dur_str}] {r['title']}")
                print(f"     Artist: {r['artist']}" + (f" | Album: {r['album']}" if r['album'] else ""))
                print(f"     {r['url']}")
                print()
            print(f"Top {len(results)} results. Use --index N to download a specific result.")
        else:
            print("No results (ytmusicapi returned empty).")
            print("Tip: Try --platform youtube or --proxy socks5://host:port")
    elif platform == "soulseek":
        print(f"Searching Soulseek for: {query}")
        print("=" * 60)
        results = soulseek_client.search(query, wait=15, max_results=limit * 10)
        if results:
            # Group by user
            from collections import Counter
            user_count = Counter(r["username"] for r in results)
            print(f"Found {len(results)} files from {len(user_count)} users:\n")
            displayed = set()
            for r in results[:limit]:
                name = r["filename"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
                size_mb = r["filesize"] / 1024 / 1024
                slot_flag = "[FREE]" if r["has_free_slots"] else "[QUEUE]"
                print(f"  {name}")
                print(f"     User: {r['username']:20s} | {size_mb:.1f}MB | {r['extension']} {slot_flag}")
                print()
        else:
            print("No Soulseek results.")
            print("Make sure SLSK_USERNAME and SLSK_PASSWORD are set.")
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

        env = make_subprocess_env()
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


def cmd_meta(filepath, query=None, embed_thumbnail=True, json_output=False):
    """Update metadata for an existing audio file.

    Uses the same multi-source lookup (MusicBrainz + NetEase + iTunes) as the
    download path. If ``query`` is omitted, the function tries to derive an
    artist/title query from the filename (e.g. "Artist - Title.mp3").
    """
    py, _, _ = ensure_deps()
    if not py:
        print("ERROR: No Python with yt-dlp found. Run 'setup' first:")
        print("  python scripts/music_helper.py setup")
        sys.exit(1)

    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    if not query:
        query = derive_query_from_filename(filepath)

    output_dir = os.path.dirname(filepath) or "."
    print("=" * 60)
    print("  MelodyMine — Update metadata for existing file")
    print("=" * 60)
    print(f"  File     : {filepath}")
    print(f"  Query    : {query}")
    print(f"  Thumbnail: {'embed' if embed_thumbnail else 'skip'}")
    print()

    enhance_metadata(query, "", output_dir, embed_thumbnail=embed_thumbnail, filepath=filepath)

    print("\n[OK] Metadata update complete!")
    result = {
        "ok": True,
        "operation": "meta",
        "file": filepath,
        "query": query,
    }
    if json_output:
        _emit_json(result)
    return result


def cmd_download(
    query, platform="auto", fmt="flac", output=None,
    proxy=None, bitrate=None, index=1, embed_thumbnail=True,
    no_metadata=False, cookies=None, dry_run=False, json_output=False,
    debug=False, slsk_user=None, slsk_pass=None,
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
        # spotDL downloads via YouTube (lossy) → auto resolves to mp3.
        if fmt == "auto":
            fmt, bitrate, reason = _resolve_auto_fmt("opus", bitrate)
            debug_log(f"[auto] spotify: {reason}")
        return _download_via_spotdl(py, query, fmt, output, proxy, bitrate)

    # ── NetEase URL → resolve → try direct audio → fallback to Bilibili/YouTube ──
    if is_netease_url(query):
        debug_log("route: netease url → resolve → direct/bilibili/youtube")
        print("[NetEase] Resolving song info from URL...")
        song_id = extract_netease_song_id(query)
        resolved = resolve_netease_url(query, python=py)
        if resolved:
            print(f"  Resolved: {resolved}")
        else:
            print("  [!] Could not resolve NetEase URL, using raw URL as query")

        # Tier 1: try NetEase direct audio (works for free/non-copyrighted songs)
        if not output:
            output = DEFAULT_OUTPUT
        if song_id and resolved:
            before = _list_audio_files(output)
            ok = _netease_direct_download(song_id, resolved, output, fmt, bitrate, py)
            if ok:
                if not no_metadata:
                    enhance_metadata(resolved, "", output, embed_thumbnail=embed_thumbnail, before_snapshot=before)
                print(f"\n[OK] Download complete (via NetEase direct)!")
                print(f"     Files saved to: {output}")
                return {
                    "ok": True, "platform": "netease", "engine": "netease-outer-url",
                    "query": resolved, "source_url": query,
                    "format": fmt, "output": output,
                    "metadata": not no_metadata, "fallback": False,
                }
            print("    Falling back to Bilibili/YouTube search...")

        # Tier 2: fall through to normal Bilibili/YouTube pipeline
        query = resolved or query

    # ── Direct download URLs (YouTube/SoundCloud/Bandcamp) → yt-dlp directly ──
    if is_direct_download_url(query):
        debug_log(f"route: direct url → yt-dlp ({'youtube' if is_youtube_url(query) else 'soundcloud' if is_soundcloud_url(query) else 'bandcamp'})")
        return _download_direct(py, query, fmt, output, proxy, bitrate,
                                index, embed_thumbnail, no_metadata, cookies)

    if platform == "auto":
        platform = auto_select_platform(query)
        debug_log(f"auto-selected platform: {platform}")

    if not output:
        output = DEFAULT_OUTPUT
    os.makedirs(output, exist_ok=True)
    # Snapshot existing audio so enhance_metadata can target only the new file.
    before = _list_audio_files(output)

    # ── Bilibili: Soulseek first → Bilibili → YouTube ──
    if platform == "bilibili":
        # Tier 1: Soulseek P2P (best quality, often lossless)
        print("=" * 60)
        print(f"  Platform : Soulseek (P2P) — primary")
        print(f"  Query    : {query}")
        print(f"  Format   : {fmt}")
        print(f"  Output   : {output}")
        print("=" * 60)
        print()
        soulseek_result = _do_soulseek_download(
            query, output, fmt, bitrate, embed_thumbnail, no_metadata,
            slsk_user=slsk_user, slsk_pass=slsk_pass,
            proxy=proxy,
        )
        if soulseek_result.get("ok"):
            return soulseek_result

        # Tier 2: Bilibili wbi search + yt-dlp download
        print(f"\n  Soulseek failed. Falling back to Bilibili...")
        print("=" * 60)
        print(f"  Platform : Bilibili (direct, no proxy)")
        print(f"  Query    : {query}")
        print(f"  Format   : {fmt}")
        print(f"  Output   : {output}")
        print("=" * 60)
        print()

        # Step 1: wbi search
        print("[1/3] Searching Bilibili...")
        results = bili_client.search(query, limit=max(index, 5))
        if not results:
            print("\n  Bilibili search failed (rate-limited or network issue).")
            print("  Falling back to YouTube...")
            return _do_youtube_download(
                py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
                no_metadata=no_metadata, cookies=cookies, before_snapshot=before,
            )

        # Reorder so vocal versions rank above accompaniment/instrumental ones.
        results = rank_bili_results(results)
        skipped_accomp = sum(1 for r in results if _is_accompaniment(r.get("title", "")))
        if skipped_accomp:
            print(f"  (优先选择带人声版本，已将 {skipped_accomp} 个伴奏/纯音乐结果排后)")

        # Step 2: Pick result and download
        item = results[min(index - 1, len(results) - 1)]
        bvid = item["bvid"]
        url = f"https://www.bilibili.com/video/{bvid}"
        print(f"  Found: [{item['duration']}] {item['title']}")
        print(f"  bvid: {bvid}")
        print()
        print("[2/3] Downloading via yt-dlp...")

        # Resolve auto format from the real audio codec (Bilibili playurl API).
        if fmt == "auto":
            _, codec = _bili_resolve_audio(item["bvid"], python=py)
            fmt, bitrate, reason = _resolve_auto_fmt(codec, bitrate)
            print(f"  [auto] {reason}")

        ok = _ytdlp_download(
            py, url, output, fmt, bitrate, embed_thumbnail,
            bili_ua=True, index=1, cookies=cookies,
        )
        if ok:
            if not no_metadata:
                enhance_metadata(query, item["title"], output, embed_thumbnail=embed_thumbnail, before_snapshot=before)
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
                "fallback": "bilibili-after-soulseek",
            }

        # Tier 3: Bilibili API direct download
        print(f"\n  yt-dlp download failed (likely 412 Precondition Failed).")
        ok_api = _bili_api_download(
            item["bvid"], output, fmt, bitrate,
            python=py,
        )
        if ok_api:
            if not no_metadata:
                enhance_metadata(query, item["title"], output, embed_thumbnail=embed_thumbnail, before_snapshot=before)
            print(f"\n[OK] Download complete (via Bilibili API direct)!")
            print(f"     Files saved to: {output}")
            return {
                "ok": True, "platform": "bilibili", "engine": "bili-api-direct",
                "query": query, "source_url": f"https://www.bilibili.com/video/{item['bvid']}",
                "format": fmt, "output": output,
                "metadata": not no_metadata, "fallback": "bili-api-direct-after-soulseek",
            }

        # Tier 4: YouTube fallback
        print(f"\n  Bilibili all tiers failed. Falling back to YouTube...")
        result = _do_youtube_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata, cookies=cookies, before_snapshot=before,
        )
        if result.get("ok"):
            return result

        # Tier 5: Soulseek retry (already failed as Tier 1, skip)
        print(f"\n  All platforms exhausted. Download failed.")
        return {"ok": False, "platform": "bilibili", "query": query,
                "error": "All download tiers exhausted (Soulseek, Bilibili, YouTube)"}

    # ── YouTube Music (ytmusicapi search + yt-dlp download) ──
    if platform == "ytmusic":
        return _do_ytmusic_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata, cookies=cookies, before_snapshot=before,
        )

    # ── Soulseek ──
    if platform == "soulseek":
        return _do_soulseek_download(
            query, output, fmt, bitrate, embed_thumbnail, no_metadata,
            slsk_user=slsk_user, slsk_pass=slsk_pass,
            proxy=proxy,
        )

    # ── YouTube (Soulseek first → YouTube) ──
    else:
        # Tier 1: Soulseek P2P
        soulseek_result = _do_soulseek_download(
            query, output, fmt, bitrate, embed_thumbnail, no_metadata,
            slsk_user=slsk_user, slsk_pass=slsk_pass,
            proxy=proxy,
        )
        if soulseek_result.get("ok"):
            return soulseek_result

        # Tier 2: YouTube
        print("\n  Soulseek failed. Falling back to YouTube...")
        result = _do_youtube_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata, cookies=cookies, before_snapshot=before,
        )
        if result.get("ok"):
            return result

        print(f"\n  All platforms exhausted. Download failed.")
        return {"ok": False, "platform": "youtube", "query": query,
                "error": "All download tiers exhausted (Soulseek, YouTube)"}





def _do_soulseek_download(
    query, output, fmt, bitrate, embed_thumbnail, no_metadata,
    slsk_user=None, slsk_pass=None,
    proxy="",
):
    """Download from Soulseek P2P network.

    Uses a single persistent session (search_and_download) to avoid
    re-login overhead. Falls back to multi-candidate retry if the
    combined call fails.
    """
    if not output:
        output = DEFAULT_OUTPUT
    os.makedirs(output, exist_ok=True)

    print("=" * 60)
    print(f"  Platform : Soulseek (P2P)")
    print(f"  Query    : {query}")
    print(f"  Format   : {fmt}")
    print(f"  Output   : {output}")
    print("=" * 60)
    print()

    print("[1/2] Searching + downloading from Soulseek network...")
    if proxy:
        print(f"  Proxy: {proxy}")

    # Tier 1: search_and_download in one session (efficient)
    debug_log("soulseek: tier 1 — search_and_download")
    ok, path = soulseek_client.search_and_download(
        query, output,
        username=slsk_user, password=slsk_pass,
        wait=20, timeout=600,
        proxy=proxy)

    if ok and path:
        print(f"\n[OK] Download complete! -> {path}")
        if not no_metadata:
            enhance_metadata(
                query, "", output,
                embed_thumbnail=embed_thumbnail, filepath=path)
        return {
            "ok": True, "platform": "soulseek", "engine": "p2p",
            "query": query, "format": fmt, "output": output,
            "metadata": not no_metadata,
        }

    # Tier 2: Multi-candidate retry with timeout scaling
    print("  search_and_download did not succeed. Trying multi-candidate mode...")
    debug_log("soulseek: tier 2 — search + download_best")

    results = soulseek_client.search(
        query, username=slsk_user, password=slsk_pass, wait=20,
        proxy=proxy)

    if not results:
        print("  No Soulseek results.")
        return {"ok": False, "platform": "soulseek", "error": "no results"}

    # Divide candidates by format and free-slot status
    flac_free = [r for r in results if r["extension"] == "flac" and r["has_free_slots"]]
    flac_all  = [r for r in results if r["extension"] == "flac"]
    mp3_free  = [r for r in results if r["extension"] in ("mp3",) and r["has_free_slots"]]
    mp3_all   = [r for r in results if r["extension"] in ("mp3",)]
    other     = [r for r in results if r["extension"] not in ("flac", "mp3")]

    candidates = (flac_free or flac_all or mp3_free or mp3_all or other)

    print(f"  Found {len(results)} files, trying download...")
    if candidates:
        ok, path = soulseek_client.download_best(
            candidates, output,
            username=slsk_user, password=slsk_pass, max_retries=2,
            proxy=proxy)

        if ok and path:
            print(f"\n[OK] Download complete! -> {path}")
            if not no_metadata:
                enhance_metadata(query, "", output,
                                 embed_thumbnail=embed_thumbnail, filepath=path)
            return {
                "ok": True, "platform": "soulseek", "engine": "p2p",
                "query": query, "format": fmt, "output": output,
                "metadata": not no_metadata,
            }

    print("\n[FAIL] Soulseek download failed.")
    return {"ok": False, "platform": "soulseek", "error": "download failed"}

def _do_ytmusic_download(
    py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
    no_metadata=False, cookies=None, before_snapshot=None,
):
    """Download via YouTube Music API search + yt-dlp direct URL.

    Uses ``ytmusicapi`` for search (no cookies needed), then hands the
    ``music.youtube.com/watch?v=ID`` URL to yt-dlp.  Falls back to the
    standard YouTube yt-dlp search path if ytmusic search fails.
    """
    print("=" * 60)
    print(f"  Platform : YouTube Music (ytmusicapi search)")
    print(f"  Query    : {query}")
    print(f"  Format   : {fmt}")
    print(f"  Output   : {output}")
    print(f"  Proxy    : none (direct connection)")
    print("=" * 60)
    print()

    # Step 1: ytmusicapi search
    print("[1/2] Searching YouTube Music...")
    results = ytmusic_client.search(query, limit=max(index, 5))

    if not results:
        print("  YouTube Music search returned no results.")
        print("  Falling back to standard YouTube search...")
        return _do_youtube_download(
            py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
            no_metadata=no_metadata, cookies=cookies, before_snapshot=before_snapshot,
        )

    # Show results and let user pick
    for i, r in enumerate(results, 1):
        dur = r.get("duration")
        dur_str = f"{dur//60}:{dur%60:02d}" if isinstance(dur, int) else str(dur or "?")
        tag = " [selected]" if i == index else ""
        print(f"  {i}. [{dur_str}] {r['title']}{tag}")
        print(f"     Artist: {r['artist']}" + (f" | Album: {r['album']}" if r['album'] else ""))
        print()

    # Step 2: download
    item = results[min(index - 1, len(results) - 1)]
    video_id = item["videoId"]
    music_url = f"https://music.youtube.com/watch?v={video_id}"
    print(f"[2/2] Downloading via yt-dlp...")
    print(f"  Source: {item['title']}")
    print(f"  URL:    {music_url}")
    print()

    ok = _download_direct(
        py, music_url, fmt, output, proxy, bitrate,
        index=1, embed_thumbnail=embed_thumbnail, no_metadata=no_metadata,
        cookies=cookies, before_snapshot=before_snapshot,
    )
    if ok:
        return {
            "ok": True,
            "platform": "ytmusic",
            "engine": "yt-dlp",
            "query": query,
            "source_url": music_url,
            "format": fmt,
            "output": output,
            "proxy": proxy,
            "cookies": cookies,
            "metadata": not no_metadata,
        }

    # yt-dlp failed on music.youtube.com — fall back to standard YouTube
    print("  yt-dlp failed on music.youtube.com URL.")
    print("  Falling back to standard YouTube search...")
    return _do_youtube_download(
        py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
        no_metadata=no_metadata, cookies=cookies, before_snapshot=before_snapshot,
    )


def _do_youtube_download(
    py, query, output, fmt, proxy, bitrate, index, embed_thumbnail,
    no_metadata=False, cookies=None, before_snapshot=None,
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

    # Snapshot existing audio if the caller didn't, so enhance_metadata targets
    # only the new file (yt-dlp mtime = upload date, not download time).
    if before_snapshot is None:
        before_snapshot = _list_audio_files(output)

    # Resolve auto format by probing the source codec (metadata only, no download).
    if fmt == "auto":
        codec = _probe_ytdlp_codec(py, search_query, index=index, proxy=proxy, cookies=cookies)
        fmt, bitrate, reason = _resolve_auto_fmt(codec, bitrate)
        print(f"  [auto] {reason}")

    ok = _ytdlp_download(
        py, search_query, output, fmt, bitrate, embed_thumbnail,
        proxy=proxy, index=index, cookies=cookies,
    )
    if ok:
        if not no_metadata:
            enhance_metadata(query, "", output, embed_thumbnail=embed_thumbnail, before_snapshot=before_snapshot)
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


def _download_direct(
    py, url, fmt, output, proxy, bitrate,
    index, embed_thumbnail, no_metadata, cookies, before_snapshot=None,
):
    """Download a direct URL (YouTube/SoundCloud/Bandcamp) via yt-dlp.

    No search step — yt-dlp downloads the URL directly.
    """
    if is_youtube_url(url):
        source = "YouTube"
    elif is_soundcloud_url(url):
        source = "SoundCloud"
    elif is_bandcamp_url(url):
        source = "Bandcamp"
    else:
        source = "Direct URL"

    if not output:
        output = DEFAULT_OUTPUT
    os.makedirs(output, exist_ok=True)
    # Snapshot existing audio so enhance_metadata targets only the new file.
    if before_snapshot is None:
        before_snapshot = _list_audio_files(output)

    print("=" * 60)
    print(f"  Source   : {source} (direct URL)")
    print(f"  URL      : {url}")
    print(f"  Format   : {fmt}")
    print(f"  Output   : {output}")
    if proxy:
        print(f"  Proxy    : {proxy}")
    if cookies:
        print(f"  Cookies  : {cookies}")
    print("=" * 60)
    print()

    # Resolve auto format by probing the source codec (metadata only, no download).
    if fmt == "auto":
        codec = _probe_ytdlp_codec(py, url, index=index, proxy=proxy, cookies=cookies)
        fmt, bitrate, reason = _resolve_auto_fmt(codec, bitrate)
        print(f"  [auto] {reason}")

    ok = _ytdlp_download(
        py, url, output, fmt, bitrate, embed_thumbnail,
        proxy=proxy, index=index, cookies=cookies,
    )
    if ok:
        if not no_metadata:
            enhance_metadata(url, "", output, embed_thumbnail=embed_thumbnail, before_snapshot=before_snapshot)
        print(f"\n[OK] Download complete!")
        print(f"     Files saved to: {output}")
        return {
            "ok": True,
            "platform": source.lower(),
            "engine": "yt-dlp",
            "query": url,
            "source_url": url,
            "format": fmt,
            "output": output,
            "proxy": proxy,
            "cookies": cookies,
            "metadata": not no_metadata,
        }

    print(f"\n[FAIL] {source} download failed.")
    if is_youtube_url(url) and not proxy:
        print("  → If you're in China, YouTube is blocked. Add: --proxy socks5://HOST:PORT")
    elif is_youtube_url(url):
        print("  → Check proxy is working, or try: --cookies cookies.txt")
    else:
        print("  → Check the URL is valid and publicly accessible.")
    sys.exit(1)


def _netease_direct_download(song_id, song_name, output, fmt, bitrate, python):
    """Try to download audio directly from NetEase's outer URL.

    NetEase exposes a 302 redirect endpoint:
      https://music.163.com/song/media/outer/url?id=<id>.mp3
    Free songs redirect to a CDN audio file; copyrighted songs redirect to
    a 404 page. This function returns True on success, False if the song is
    restricted or unavailable.
    """
    import urllib.request
    import urllib.error

    outer_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
    print("    ↳ Trying NetEase direct audio...")

    # The outer URL always serves 128k mp3 — auto resolves to mp3 (no upcast).
    if fmt == "auto":
        fmt, bitrate, reason = _resolve_auto_fmt("mp3", bitrate)
        print(f"    [auto] {reason}")

    # Follow the redirect to check if we get audio or a 404 page
    req = urllib.request.Request(outer_url)
    req.add_header("User-Agent", BILI_UA)
    req.add_header("Referer", "https://music.163.com/")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        final_url = resp.url
        if "404" in final_url:
            print("    [!] NetEase direct: song is restricted (404 redirect)")
            return False
        content_type = resp.headers.get("Content-Type", "")
        if "audio" not in content_type and "octet-stream" not in content_type:
            print(f"    [!] NetEase direct: not audio (content-type: {content_type})")
            return False
    except Exception as e:
        print(f"    [!] NetEase direct: {e}")
        return False

    # We have a real audio stream — download it
    os.makedirs(output, exist_ok=True)
    raw_path = os.path.join(output, f"_netease_raw_{song_id}.mp3")
    print(f"    Downloading from NetEase CDN...")
    try:
        req2 = urllib.request.Request(final_url)
        req2.add_header("User-Agent", BILI_UA)
        req2.add_header("Referer", "https://music.163.com/")
        with urllib.request.urlopen(req2, timeout=120) as r:
            with open(raw_path, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
    except Exception as e:
        print(f"    [!] NetEase download failed: {e}")
        if os.path.isfile(raw_path):
            os.remove(raw_path)
        return False

    size_mb = os.path.getsize(raw_path) / (1024 * 1024)
    if size_mb < 0.1:
        os.remove(raw_path)
        print("    [!] NetEase direct: file too small (<100KB)")
        return False
    print(f"    Downloaded: {size_mb:.1f} MB")

    # Convert if needed
    ffmpeg_exe = find_ffmpeg(python)
    if not ffmpeg_exe or fmt == "mp3":
        final_path = os.path.join(output, f"{sanitize_filename(song_name)}.mp3")
        if raw_path != final_path:
            os.rename(raw_path, final_path)
        print(f"    Saved: {os.path.basename(final_path)}")
        return True

    print(f"    Converting to {fmt}...")
    final_path = os.path.join(output, f"{sanitize_filename(song_name)}.{fmt}")
    return _ffmpeg_convert(ffmpeg_exe, raw_path, final_path, fmt, bitrate)


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

    env = make_subprocess_env()
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
  meta "D:\\Music\\song.mp3"               Update metadata for an existing file
  meta "D:\\Music\\song.mp3" --query "Artist Song"  Specify lookup query
        """,
    )
    sub = parser.add_subparsers(dest="operation")

    sub.add_parser("setup", help="First-time setup: install all dependencies automatically")
    sub.add_parser("check", help="Verify dependencies (auto-installs if missing)")

    p_search = sub.add_parser("search", help="Search for songs (no download)")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--platform", default="auto", choices=["auto", "bilibili", "youtube", "ytmusic", "soulseek"])
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--proxy", default=None)

    p_meta = sub.add_parser("meta", help="Update metadata for an existing audio file")
    p_meta.add_argument("filepath", help="Path to the audio file")
    p_meta.add_argument("--query", default=None,
                        help="Search query for metadata lookup (default: derive from filename)")
    p_meta.add_argument("--no-thumbnail", action="store_true",
                        help="Skip cover art embedding")
    p_meta.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON after update")

    p_dl = sub.add_parser("download", help="Download a song")
    p_dl.add_argument("query", help="Song name, artist, Spotify URL, or search query")
    p_dl.add_argument("--platform", default="auto", choices=["auto", "bilibili", "youtube", "ytmusic", "soulseek"])
    p_dl.add_argument("--format", default="auto",
                      choices=["auto", "mp3", "flac", "m4a", "opus", "wav", "vorbis"],
                      help="Output format. 'auto' probes the source: flac if lossless, else mp3 320K")
    p_dl.add_argument("--output", default=None, help="Output dir (default: ~/Music/MelodyMine)")
    p_dl.add_argument("--proxy", default=None, help="Proxy for YouTube/Soulseek (e.g. socks5://127.0.0.1:7897)")
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
    p_dl.add_argument("--slsk-user", default=None, help="Soulseek username (or set SLSK_USERNAME env)")
    p_dl.add_argument("--slsk-pass", default=None, help="Soulseek password (or set SLSK_PASSWORD env)")

    args = parser.parse_args()

    if args.operation == "setup":
        ok = cmd_setup()
        sys.exit(0 if ok else 1)
    elif args.operation == "check":
        ok = cmd_check()
        sys.exit(0 if ok else 1)
    elif args.operation == "search":
        cmd_search(args.query, args.platform, args.limit, args.proxy)
    elif args.operation == "meta":
        cmd_meta(
            args.filepath,
            query=args.query,
            embed_thumbnail=not args.no_thumbnail,
            json_output=args.json,
        )
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
            slsk_user=args.slsk_user,
            slsk_pass=args.slsk_pass,
        )
        # Emit JSON for non-dry-run successful downloads (dry-run already emitted).
        if args.json and not args.dry_run and isinstance(result, dict):
            _emit_json(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

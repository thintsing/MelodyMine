#!/usr/bin/env python3
"""MelodyMine metadata enhancement module.

Extracted from ``music_helper.py`` to eliminate the circular import with
``spotify_helper.py``.  Both helpers now import metadata from here.

Provides:
- Query / title parsing (parse_search_query, parse_bili_title)
- Multi-source metadata lookup (enhance_metadata)
- Tag reading / writing (read_audio_tags, set_metadata)
- iTunes search (free, no auth)
- Bilibili result ranking (rank_bili_results)
"""

import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cover_client
import lyrics_client
import mbrainz_client
import netease_client
from melodymine_common import (
    find_ffmpeg,
    is_accompaniment,
    is_derivative,
    norm_cn,
    sanitize_filename,
    strip_version_tag,
    text_sim,
)

# ─── Audio file extensions (canonical source — shared by all modules) ────

_AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".opus", ".wav", ".vorbis", ".ogg", ".webm"}


def list_audio_files(output_dir):
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
    captured by list_audio_files *before* the download; only files not in
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


# ─── Chinese text normalization ────────────────────────────────────────
# norm_cn lives in melodymine_common so lyric matching can use it too.


def _clean_artist(name):
    """Clean up artist name from API (remove trailing dashes, periods, etc.)."""
    if not name:
        return ""
    name = name.split(",")[0].split("，")[0]
    name = name.rstrip("-－—–.。，,·・")
    return name.strip()


# ─── Query parsing ─────────────────────────────────────────────────────

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
        if artist.lower() in _ARTICLES and len(parts) >= 3:
            artist = f"{parts[0]} {parts[1]}"
            title = " ".join(parts[2:])
        return artist, title
    return None, query.strip()


# ─── Bilibili title parsing ────────────────────────────────────────────

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

    m = re.match(r"^(.+?)《(.+?)》", title)
    if m:
        artist = m.group(1).strip()
        song_name = m.group(2).strip()

    if not artist:
        m = re.match(r"^[【［](.+?)[】］]\s*(.+)", title)
        if m:
            artist = m.group(1).strip()
            song_name = m.group(2).strip()

    if not artist:
        m = re.match(r"^(.+?)\s*[-－—–]\s*(.+)", title)
        if m:
            artist = m.group(1).strip()
            song_name = m.group(2).strip()

    if song_name:
        for p in _NOISE_PATTERNS:
            song_name = re.sub(p, "", song_name)
        song_name = song_name.strip(" -｜|\t")

    if artist:
        for p in _NOISE_PATTERNS:
            artist = re.sub(p, "", artist)
        artist = artist.strip(" -｜|\t")

    return artist, song_name


# ─── Search result ranking ─────────────────────────────────────────────

def rank_bili_results(results):
    """Reorder Bilibili search results so non-accompaniment entries come first.

    Within each group (vocal / accompaniment) results keep their original
    API order, which already reflects Bilibili relevance. This means the
    default --index 1 picks the most relevant *vocal* version instead of a
    backing track that happened to rank highest.
    """
    vocal = [r for r in results if not is_accompaniment(r.get("title", ""))]
    accomp = [r for r in results if is_accompaniment(r.get("title", ""))]
    return vocal + accomp


# How much longer than the query a title may be before it looks like a video
# upload ("你不要担心：承载了多少人的青春，《请回答1988》主题曲") rather than a release.
_PROSE_TITLE_SLACK = 8


def rank_search_results(results, query=None):
    """Reorder CJK catalogue results so the original recording comes first.

    Kuwo and Kugou both rank by popularity, which puts cover channels, live
    cuts and video-style uploads above the original. Score each result by how
    well it matches the query, then demote accompaniments, derivative versions
    and prose titles. Ties keep their API order.

    This narrows the candidates; it cannot identify *the* original when the
    query names no artist, since several unrelated artists may have recorded
    the same song.
    """
    q_artist, q_title = parse_search_query(query) if query else (None, "")
    want_title = strip_version_tag(q_title or query or "")

    scored = []
    for item in results:
        raw_title = item.get("title") or ""
        clean_title = strip_version_tag(raw_title)
        relevance = text_sim(want_title, clean_title)
        if q_artist:
            relevance = 0.6 * relevance + 0.4 * text_sim(q_artist, item.get("artist"))

        penalty = 0.0
        if is_accompaniment(raw_title):
            penalty += 0.5
        if is_derivative(raw_title):
            penalty += 0.3
        if len(clean_title) - len(want_title) > _PROSE_TITLE_SLACK:
            penalty += 0.2
        scored.append((penalty - relevance, item))

    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored]


# ─── Audio tag I/O ─────────────────────────────────────────────────────

def read_audio_tags(filepath, python=None):
    """Read artist and title tags from an audio file via ffmpeg.

    Returns (artist, title) tuple. Each is None if missing or unreadable.
    Never raises — returns (None, None) on any failure.

    Uses ``ffmpeg -f ffmetadata`` rather than ffprobe: the bundled
    imageio-ffmpeg build ships ffmpeg only, so an ffprobe-based reader
    silently found nothing on machines without a system install.
    """
    ffmpeg_exe = find_ffmpeg(python)
    if not ffmpeg_exe:
        return None, None

    try:
        result = subprocess.run(
            [ffmpeg_exe, "-v", "quiet", "-i", filepath, "-f", "ffmetadata", "-"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except Exception:
        return None, None

    if result.returncode != 0:
        return None, None

    tags = {}
    for line in result.stdout.splitlines():
        if line.startswith(";") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        tags.setdefault(key.strip().lower(), value.strip())

    return tags.get("artist") or None, tags.get("title") or None


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

    base, ext = os.path.splitext(filepath)
    tmp_path = base + ".meta_tmp" + ext
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    cmd = [ffmpeg_exe, "-y", "-i", filepath]
    has_cover = cover_path and os.path.isfile(cover_path)
    if has_cover:
        cmd.extend(["-i", cover_path])

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


# ─── iTunes Search ─────────────────────────────────────────────────────

def itunes_search(query, limit=5):
    """
    Search iTunes Search API (free, no auth).
    Returns list of dicts with keys: artist, title, album, cover, date, genre
    or empty list on failure.
    """
    try:
        import urllib.parse
        import urllib.request
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


# ─── Metadata scoring ──────────────────────────────────────────────────

def _score_metadata_candidate(r, artist, title, *, collaboration_aware=False, bonus_fields=False):
    """Score a single metadata result (from MusicBrainz / NetEase / iTunes)
    against a parsed artist/title pair.

    - collaboration_aware: for NetEase, which returns comma-joined multi-artist
      strings — reduces the exact-artist score and uses the raw (uncleaned)
      artist for the contains check.
    - bonus_fields: for iTunes, adds small bonuses for having cover art and
      an album name.
    """
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
    if norm_cn(r_artist) == norm_cn(artist):
        score += 5 if is_collab else 20
    elif collaboration_aware:
        if norm_cn(artist) in norm_cn(r_artist_raw):
            score += 3
    elif norm_cn(artist) in norm_cn(r_artist):
        score += 8

    if norm_cn(r_title) == norm_cn(title):
        score += 5
    elif norm_cn(title) in norm_cn(r_title) or norm_cn(r_title) in norm_cn(title):
        score += 2

    if bonus_fields:
        cover = r.get("cover") or r.get("pic_url")
        if cover:
            score += 3
        if r.get("album"):
            score += 2
    return score


def _best_metadata_candidate(results, artist, title, **kwargs):
    """Return ``(best_score, best_data)`` across a list of metadata results
    using ``_score_metadata_candidate``.  Returns ``(-1, None)`` when the
    list is empty.
    """
    best_score, best_data = -1, None
    for r in results:
        score = _score_metadata_candidate(r, artist, title, **kwargs)
        if score > best_score:
            best_score, best_data = score, r
    return best_score, best_data


# ─── Lyrics helper ──────────────────────────────────────────────────────

def _fetch_and_save_lyrics(artist, title, album, filepath):
    """Fetch lyrics from LRCLIB and save as .lrc file.

    Returns the .lrc path on success, None on failure. Never raises.
    """
    try:
        data = lyrics_client.get_lyrics(artist, title, album=album)
        if not data:
            print("  Lyrics: not found")
            return None
        synced = data.get("synced_lyrics", "")
        plain = data.get("plain_lyrics", "")
        lrc_path = lyrics_client.save_lrc(filepath, synced, plain)
        return lrc_path
    except Exception:
        return None


# ─── Main metadata enhancement ─────────────────────────────────────────

def enhance_metadata(search_query, bili_title, output_dir, embed_thumbnail=True,
                     filepath=None, before_snapshot=None, fetch_lyrics=True):
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
    ``before_snapshot`` (from list_audio_files, captured before the
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

    # ── Skip if file already has meaningful metadata ──
    existing_artist, existing_title = read_audio_tags(filepath)
    if existing_artist and existing_title:
        print(f"\n  File already tagged: {existing_artist} - {existing_title}")
        print("  Skipping metadata enhancement.")
        if fetch_lyrics:
            lrc_base = os.path.splitext(filepath)[0] + ".lrc"
            if not os.path.isfile(lrc_base):
                print("  Fetching lyrics for existing file...")
                lrc_path = _fetch_and_save_lyrics(existing_artist, existing_title, None, filepath)
                if lrc_path:
                    print(f"  Lyrics: {os.path.basename(lrc_path)}")
        return

    print("\n[3/3] Enhancing metadata...")

    # ── Layer 1: Parse search query ──
    artist, title = parse_search_query(search_query)
    if artist and title:
        print(f"  From search query: artist={artist}, title={title}")
    elif bili_title:
        artist, title = parse_bili_title(bili_title)
        if artist and title:
            print(f"  From Bilibili title: artist={artist}, title={title}")

    if not artist or not title:
        print("  [!] Could not determine artist/title, keeping original tags")
        return

    # ── Layer 2: Multi-source lookup (concurrent) ──
    print("  Looking up album info (MusicBrainz + NetEase + iTunes in parallel)...")

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_mb = pool.submit(mbrainz_client.lookup, search_query, 5)
        fut_ne = pool.submit(netease_client.search, search_query, 10)
        fut_it = pool.submit(itunes_search, search_query, 10)
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

    best_mb_score, mb_data = _best_metadata_candidate(mb_results, artist, title)
    best_ne_score, ne_data = _best_metadata_candidate(ne_results, artist, title, collaboration_aware=True)
    best_it_score, it_data = _best_metadata_candidate(it_results, artist, title, bonus_fields=True)

    if mb_data:
        print(f"    Best: {mb_data['artist']} - {mb_data['title']} [MusicBrainz (score={best_mb_score})]")
    else:
        print("    No results from MusicBrainz")
    if ne_data:
        print(f"    Best: {_clean_artist(ne_data['artist'])} - {ne_data['title']} [NetEase (score={best_ne_score})]")
    else:
        print("    No results from NetEase")
    if it_data:
        print(f"    Best: {it_data['artist']} - {it_data['title']} [iTunes (score={best_it_score})]")
    else:
        print("    No results from iTunes")

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
        print("  Cover: not available")

    # ── Download album cover ──
    cover_path = None
    if embed_thumbnail and pic_url:
        cover_path = cover_client.download(pic_url)
        if cover_path:
            print("  Downloaded album cover")
    elif not embed_thumbnail:
        print("  Cover: skipped (--no-thumbnail)")

    # ── Set ID3 tags with ffmpeg ──
    ok = set_metadata(filepath, title=title, artist=artist, album=album, cover_path=cover_path)
    if ok:
        print(f"  [OK] Metadata embedded: {artist} - {title}" + (f" | {album}" if album else ""))
    else:
        print("  [!] Failed to set metadata (ffmpeg error)")

    # ── Rename file ──
    new_base = sanitize_filename(f"{artist} - {title}")
    if new_base:
        ext = os.path.splitext(filepath)[1]
        new_path = os.path.join(os.path.dirname(filepath), new_base + ext)
        if new_path != filepath and not os.path.exists(new_path):
            try:
                os.rename(filepath, new_path)
                filepath = new_path
                print(f"  Renamed: {os.path.basename(new_path)}")
            except Exception:
                pass

    # ── Fetch lyrics ──
    if fetch_lyrics:
        lrc_path = _fetch_and_save_lyrics(artist, title, album, filepath)
        if lrc_path:
            print(f"  Lyrics: {os.path.basename(lrc_path)}")

    if cover_path and os.path.isfile(cover_path):
        try:
            os.remove(cover_path)
        except Exception:
            pass


# ─── Audio file integrity check ───────────────────────────────────────

def verify_audio_file(filepath, min_size_kb=100):
    """Quick integrity check on a downloaded audio file.

    Uses ffprobe to confirm the file is a valid, playable audio file.
    Reports file size and duration.

    Returns a dict::
        {"ok": True, "size_mb": 5.2, "duration_s": 210.5, "codec": "mp3"}
        {"ok": False, "error": "file too small (12 KB)"}

    Never raises — returns error dict on any failure.
    """
    if not os.path.isfile(filepath):
        return {"ok": False, "error": "file not found", "path": filepath}

    size_bytes = os.path.getsize(filepath)
    size_mb = size_bytes / (1024 * 1024)
    size_kb = size_bytes / 1024

    if size_kb < min_size_kb:
        return {"ok": False, "error": f"file too small ({size_kb:.0f} KB)", "path": filepath}

    ffmpeg_exe = find_ffmpeg()
    if not ffmpeg_exe:
        return {"ok": True, "size_mb": size_mb, "note": "ffprobe unavailable, size check only"}

    ffprobe_exe = os.path.join(os.path.dirname(ffmpeg_exe), "ffprobe")
    if os.name == "nt":
        ffprobe_exe += ".exe"
    if not os.path.isfile(ffprobe_exe):
        ffprobe_exe = "ffprobe"

    try:
        result = subprocess.run(
            [ffprobe_exe, "-v", "error",
             "-show_entries", "format=duration,format_name",
             "-of", "csv=p=0",
             filepath],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"ffprobe failed: {result.stderr[:200]}", "path": filepath}

        parts = result.stdout.strip().split(",")
        duration_s = float(parts[0]) if len(parts) >= 1 and parts[0] else None
        codec = parts[1] if len(parts) >= 2 and parts[1] else None

        mins = int(duration_s // 60) if duration_s else 0
        secs = int(duration_s % 60) if duration_s else 0

        return {
            "ok": True,
            "size_mb": round(size_mb, 1),
            "duration_s": duration_s,
            "duration_str": f"{mins}:{secs:02d}" if duration_s else "?",
            "codec": codec,
            "path": filepath,
        }
    except Exception as e:
        return {"ok": True, "size_mb": round(size_mb, 1), "note": f"ffprobe error ({e}), size OK"}

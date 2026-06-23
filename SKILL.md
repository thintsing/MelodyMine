---
name: melodymine
description: "Download music from Bilibili, YouTube, and Spotify. Triggers when user wants to download songs, sync playlists, or save music. Supports: download music, download song, download album, 下载歌曲, 下载音乐, 下载这首歌, 下载歌单, 用MelodyMine下载, save music, sync music."
---

# MelodyMine Music Downloader Skill

> **Execute, Don't Explain** — When triggered, directly run download commands. Don't just explain how to use the tool.

## Trigger Conditions

Activate this skill when the user wants to:
- Download a song, album, or playlist (any platform)
- Save music from a URL (Spotify, Bilibili, YouTube)
- Convert music format (to MP3, FLAC, etc.)
- Search for music to download

**Trigger phrases**: "下载歌曲", "下载音乐", "下载这首歌", "download music", "download song", "save this track", "下载周杰伦", "帮我下载", "download from spotify", "download from bilibili"

## Architecture

```
User says "下载周杰伦的稻香"
    ↓
AI parses intent → extracts song name / artist
    ↓
Auto-detect language:
  Chinese → Bilibili (direct, no proxy needed)
  English → YouTube (needs proxy)
    ↓
music_helper.py download "query"
    ↓
[1/3] Search (Bilibili wbi API / YouTube yt-dlp search)
[2/3] Download (yt-dlp → ffmpeg convert → embed thumbnail)
[3/3] Metadata Enhancement:
      ├─ Parse search query → extract artist + title
      ├─ NetEase Music API → lookup album + cover (best-effort)
      ├─ ffmpeg → write clean ID3 tags (title, artist, album)
      └─ Rename file → "Artist - Title.mp3"
    ↓
Report file path to user
```

## Quick Start (AI Execution Guide)

### Step 0: First-Time Setup (REQUIRED on new machines)

The FIRST time this skill runs on a new machine, run setup to auto-install all dependencies:

```bash
python music_helper.py setup
# or
python3 music_helper.py setup
```

This works on **Windows, macOS, and Linux**. It will:
1. Find a Python interpreter (scans PATH, WorkBuddy venv, pyenv, conda, Homebrew, common install locations)
2. Auto-install pip packages: `yt-dlp`, `requests`, `pysocks`, `imageio-ffmpeg`
3. Handle PEP 668 (externally-managed-environment on modern Debian/Ubuntu/Fedora) by falling back to `--user` or creating an isolated venv
4. Locate ffmpeg (system PATH → or auto-installed `imageio-ffmpeg` bundled binary)
5. Report platform availability

**After setup succeeds, skip to Step 1 for all future downloads.**

If `setup` fails (no Python found), ask user to install Python 3.10+ from https://python.org

### Step 0b: Verify Dependencies (optional, auto-installs if missing)

```bash
python music_helper.py check
```

**The helper auto-detects the right Python** — you don't need to know the path.
On subsequent runs, `check` will auto-install any missing packages.

**How to call the script**: Use any `python` or `python3` to launch `music_helper.py`.
The script internally finds the correct Python with yt-dlp installed via `find_python()`.

```bash
# Any Python works to launch the script — it finds the right one internally
python music_helper.py check      # Windows
python3 music_helper.py check     # macOS / Linux
```

### Step 1: Download

```bash
# Chinese song → auto-selects Bilibili (no proxy needed!)
python music_helper.py download "周杰伦 稻香" --format mp3

# English song → auto-selects YouTube (proxy optional — needed in China, not elsewhere)
python music_helper.py download "The Weeknd Blinding Lights"
# In China, add proxy:
python music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://HOST:PORT

# Spotify URL → uses spotDL (auto-installed)
python music_helper.py download "https://open.spotify.com/track/xxx"

# Force a specific platform
python music_helper.py download "周杰伦 稻香" --platform bilibili
python music_helper.py download "The Weeknd" --platform youtube --proxy socks5://HOST:PORT
```

### Step 2: Verify & Report

```bash
# Check if file was downloaded
ls ~/Music/MelodyMine/
```

Report to user: song name, file path, format.

## Command Reference

### setup (first-time only)
```bash
python music_helper.py setup
```
Auto-installs ALL dependencies: finds Python, pip-installs yt-dlp/requests/pysocks/imageio-ffmpeg,
locates ffmpeg (system or bundled). Run this once on a new machine.

### check
```bash
python music_helper.py check
```
Verify all dependencies. Auto-installs missing packages. Use this to verify setup worked.

### search
```bash
python music_helper.py search "周杰伦 稻香"                    # Auto (Bilibili)
python music_helper.py search "The Weeknd" --proxy socks5://... # YouTube
```

### download
```bash
python music_helper.py download "query" [options]

Options:
  --platform {auto,bilibili,youtube}  Default: auto (by language)
  --format {mp3,flac,m4a,opus,wav}     Default: mp3
  --output PATH                        Default: ~/Music/MelodyMine/
  --proxy URL                          For YouTube (e.g. socks5://host:port)
  --bitrate RATE                       e.g. 320K, 128K
  --index N                            Which search result (default: 1)
  --no-thumbnail                       Skip embedding cover art
  --no-metadata                        Skip metadata enhancement (keep original tags)
```

## Platform Strategy

| Platform | Proxy Needed | Search Method | Reliability |
|----------|-------------|---------------|-------------|
| **Bilibili** | Never | wbi API (custom) | High (Chinese songs) |
| **YouTube** | Only in China | yt-dlp ytsearch | Medium (bot detection) |
| **Spotify URL** | Only in China | spotDL | Low (SpotipyFree bug) |

### Auto-Platform Selection
- Query contains Chinese characters → **Bilibili** (direct access, no proxy)
- Query is English/other → **YouTube** (proxy optional — try without first)
- Query is a Spotify URL → **spotDL**

### Fallback Chain
1. Try auto-selected platform
2. If Bilibili fails → fallback to YouTube (with or without proxy)
3. If YouTube fails → report error with diagnostics (suggest proxy if in China)

## Proxy Configuration

- **Bilibili**: NO proxy needed (works worldwide)
- **YouTube**: Proxy needed **only in China**. Outside China, direct connection works.
  - If user is in China and hasn't provided a proxy, ASK them for one.
  - Common formats: `socks5://host:port`, `http://host:port`
- **spotDL**: Proxy passed via `--yt-dlp-args` (SOCKS5) or `--proxy` (HTTP)

**How to detect if user is in China**: If YouTube download fails with network
timeout or connection error, suggest adding `--proxy`. If it succeeds without
proxy, the user is not in China (or has a VPN).

## Decision Tree for AI

### First time on a new machine (any request)
```
1. Run: python music_helper.py setup
2. If setup fails → ask user to install Python 3.10+ from https://python.org
3. If setup succeeds → proceed with the download request
```

### User: "下载周杰伦的稻香"
```
1. Auto-detect: Chinese → Bilibili
2. Run: music_helper.py download "周杰伦 稻香" --format mp3
   (No proxy needed!)
3. If Bilibili fails → auto-fallback to YouTube (no proxy needed outside China)
4. Report file path
```

### User: "Download Blinding Lights by The Weeknd"
```
1. Auto-detect: English → YouTube
2. Run: music_helper.py download "The Weeknd Blinding Lights"
   (No proxy needed outside China — try direct first!)
3. If YouTube fails with network error → user is likely in China
   → ASK user for proxy: "Looks like YouTube is blocked. Got a proxy? (e.g. socks5://host:port)"
   → Retry: music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://USER_PROXY
4. Report file path
```

### User: "下载这个 https://open.spotify.com/track/xxx"
```
1. Detect: Spotify URL → spotDL (auto-installed if missing)
2. Run: music_helper.py download "https://open.spotify.com/track/xxx"
   (Add --proxy if in China)
3. If spotDL fails (KeyError 'uri') → search by song name instead
4. Report file path
```

### User: "用FLAC格式下载稻香"
```
1. Run: music_helper.py download "周杰伦 稻香" --format flac
2. Report file path
```

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `412 Precondition Failed` | Bilibili API rate-limited | Retry after a few seconds (auto-retry built in) |
| `Sign in to confirm you're not a bot` | YouTube bot detection | Export cookies from browser, use `--cookies` |
| `KeyError: 'uri'` | spotDL SpotipyFree bug | Search by song name instead of Spotify URL |
| `Invalid proxy server` | spotDL doesn't support SOCKS5 | Helper auto-converts to `--yt-dlp-args` |
| No results found | Search query too specific | Try English name or broader query |
| File not found after download | Output dir mismatch | Check `--output` path |

## Known Issues

1. **Bilibili rate limiting**: Making too many API requests in quick succession triggers 412.
   The helper auto-retries once after 2s delay. In normal usage (one download at a time), this is not an issue.

2. **YouTube bot detection**: YouTube may block automated downloads through proxies.
   Solution: Export browser cookies using "Get cookies.txt" extension and pass via `--cookies`.

3. **spotDL SpotipyFree bug**: Processing Spotify URLs may fail with `KeyError: 'uri'`.
   Workaround: Search by song name instead of Spotify URL. Or use `--use-official-api` (requires Spotify login).

## File Structure

```
MelodyMine/
├── SKILL.md                      ← This file
├── scripts/
│   ├── music_helper.py           ← Main helper (setup/check/search/download + metadata)
│   ├── spotify_helper.py         ← Advanced spotDL operations (sync/save/meta/url)
│   └── requirements.txt           ← Python deps (auto-installed by `setup`)
└── references/
    ├── usage.md                  ← Detailed CLI reference
    └── config.md                 ← Configuration reference
```

## Environment Requirements

**The only hard requirement is Python 3.10+**. Everything else is auto-installed.
Works on **Windows, macOS, and Linux** (including headless servers).

| Dependency | How it's resolved | Required for |
|-----------|-------------------|-------------|
| **Python 3.10+** | User must have it installed | Running the script |
| yt-dlp | Auto `pip install` via `setup` or `check` | All downloads |
| requests | Auto `pip install` | Bilibili search, NetEase metadata |
| pysocks | Auto `pip install` | SOCKS5 proxy (YouTube in China) |
| imageio-ffmpeg | Auto `pip install` | ffmpeg (if system ffmpeg not found) |
| ffmpeg | System PATH → or imageio-ffmpeg bundled binary | Audio conversion, ID3 tags |
| spotdl | Auto `pip install` on first Spotify URL | Spotify URL downloads (optional) |

**Python detection covers**:
- Windows: `py`, `python`, LOCALAPPDATA, ProgramFiles, WorkBuddy venv
- macOS: Homebrew (`/opt/homebrew`), python.org framework, `/usr/local/bin`, WorkBuddy venv
- Linux: `/usr/bin/python3`, pyenv, conda/miniconda, asdf, `~/.local/bin`, WorkBuddy venv

**PEP 668 (externally-managed-environment)**:
On modern Debian/Ubuntu/Fedora, `pip install` into system Python is blocked.
The helper handles this automatically:
1. Try regular `pip install`
2. If blocked, try `pip install --user`
3. If still blocked, create an isolated venv at `~/.cache/melodymine-venv`

**The `setup` command handles everything**: `python music_helper.py setup`

## Technical Details

### Bilibili wbi Search
The helper implements Bilibili's wbi signing algorithm to call the official search API directly,
bypassing yt-dlp's broken `bilisearch:` extractor. This returns reliable search results with
video IDs (BV numbers), which are then passed to yt-dlp for the actual audio download.

### Metadata Enhancement (3-Layer Strategy)
After download, the helper automatically enhances metadata:

1. **Parse search query**: "周杰伦 稻香" → artist=周杰伦, title=稻香
2. **NetEase Music API**: Look up album name and cover art (best-effort)
   - Searches NetEase Music's free API for the song
   - Scores results: solo artist exact match (score 20+) = high confidence
   - Only writes album name when a high-confidence match is found
   - Skips album if only covers/remixes are available (avoids wrong info)
3. **ffmpeg ID3 tags**: Writes clean title, artist, album to the file
4. **File rename**: "周杰伦《稻香》完整版无损音质.mp3" → "周杰伦 - 稻香.mp3"

Use `--no-metadata` to skip this step entirely (keep Bilibili's original tags and filename).

### Audio Pipeline
```
Search (wbi API / yt-dlp) → yt-dlp download (bestaudio) → ffmpeg convert (mp3/flac) → embed thumbnail
  → metadata enhancement (ID3 tags + rename)
```

# MelodyMine

> Download music from Bilibili, YouTube, and Spotify — with clean metadata, cross-platform, zero-config.

MelodyMine is a self-bootstrapping music downloader. Give it a song name, and it searches, downloads, tags, and renames the file automatically. No manual ffmpeg setup, no dependency hell — just `python music_helper.py setup` and you're ready.

## Features

- **Multi-platform**: Bilibili (Chinese songs), YouTube (international), Spotify URLs
- **Clean metadata**: Auto-fetches album name and cover art from NetEase Music, writes ID3 tags, renames files to `Artist - Title.mp3`
- **Self-bootstrapping**: One `setup` command installs everything (yt-dlp, requests, pysocks, ffmpeg)
- **Cross-platform**: Windows, macOS, Linux (including headless servers)
- **PEP 668 aware**: Handles externally-managed Python on modern Debian/Ubuntu/Fedora
- **Smart platform routing**: Chinese query → Bilibili (no proxy needed), English query → YouTube
- **Bilibili wbi search**: Custom implementation bypasses yt-dlp's broken bilisearch extractor

## Quick Start

```bash
# 1. Clone
git clone https://github.com/thintsing/MelodyMine.git
cd MelodyMine

# 2. Setup (installs all dependencies automatically)
python scripts/music_helper.py setup

# 3. Download
python scripts/music_helper.py download "周杰伦 稻香"
python scripts/music_helper.py download "The Weeknd Blinding Lights"
```

That's it. The only prerequisite is **Python 3.10+**.

## Platform Support

| Platform | Proxy Needed | Search Method | Best For |
|----------|-------------|---------------|----------|
| **Bilibili** | Never | wbi API (custom) | Chinese songs |
| **YouTube** | Only in China | yt-dlp ytsearch | International songs |
| **Spotify URL** | Only in China | spotDL (auto-installed) | Spotify links |

### Auto-Platform Selection

- Query contains Chinese characters → **Bilibili** (direct access, no proxy)
- Query is English/other → **YouTube** (proxy optional — try without first)
- Query is a Spotify URL → **spotDL**

If the primary platform fails, MelodyMine automatically falls back to the next.

## Usage

### Download

```bash
# Chinese song → auto-selects Bilibili (no proxy needed!)
python scripts/music_helper.py download "周杰伦 稻香" --format mp3

# English song → auto-selects YouTube
python scripts/music_helper.py download "The Weeknd Blinding Lights"

# In China? Add a proxy for YouTube:
python scripts/music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://HOST:PORT

# Spotify URL → uses spotDL (auto-installed)
python scripts/music_helper.py download "https://open.spotify.com/track/xxx"

# Force a specific platform
python scripts/music_helper.py download "周杰伦 稻香" --platform bilibili
python scripts/music_helper.py download "The Weeknd" --platform youtube --proxy socks5://HOST:PORT

# High quality FLAC
python scripts/music_helper.py download "周杰伦 稻香" --format flac --bitrate 320K

# Pick a different search result
python scripts/music_helper.py download "稻香" --index 2
```

### Search (preview without downloading)

```bash
python scripts/music_helper.py search "周杰伦 稻香"
python scripts/music_helper.py search "The Weeknd" --proxy socks5://HOST:PORT
```

### Check Dependencies

```bash
python scripts/music_helper.py check
```

### All Options

```
python scripts/music_helper.py download "query" [options]

Options:
  --platform {auto,bilibili,youtube}  Default: auto (by language)
  --format {mp3,flac,m4a,opus,wav}     Default: mp3
  --output PATH                        Default: ~/Music/MelodyMine/
  --proxy URL                          For YouTube (e.g. socks5://host:port)
  --bitrate RATE                       e.g. 320K, 128K
  --index N                            Which search result (default: 1)
  --no-thumbnail                       Skip embedding cover art
  --no-metadata                        Skip metadata enhancement
```

## How Metadata Enhancement Works

After downloading, MelodyMine automatically cleans up the file:

```
Search query: "周杰伦 稻香"
    ↓
Layer 1: Parse query → artist=周杰伦, title=稻香
    ↓
Layer 2: NetEase Music API → album="魔杰座", cover art URL
         (scoring filters out covers/remixes — only high-confidence matches)
    ↓
Layer 3: ffmpeg writes ID3 tags (title, artist, album, cover)
    ↓
File renamed: "周杰伦《稻香》完整版无损音质.mp3" → "周杰伦 - 稻香.mp3"
```

Use `--no-metadata` to skip this step and keep the original tags.

## Environment Requirements

**The only hard requirement is Python 3.10+.** Everything else is auto-installed.

| Dependency | How it's resolved | Required for |
|-----------|-------------------|-------------|
| **Python 3.10+** | User must have it installed | Running the script |
| yt-dlp | Auto `pip install` via `setup` | All downloads |
| requests | Auto `pip install` | Bilibili search, NetEase metadata |
| pysocks | Auto `pip install` | SOCKS5 proxy (YouTube in China) |
| imageio-ffmpeg | Auto `pip install` | ffmpeg (if system ffmpeg not found) |
| ffmpeg | System PATH → or imageio-ffmpeg bundled binary | Audio conversion, ID3 tags |
| spotdl | Auto `pip install` on first Spotify URL | Spotify URL downloads (optional) |

**Python detection covers**:
- Windows: `py`, `python`, LOCALAPPDATA, ProgramFiles
- macOS: Homebrew, python.org framework, `/usr/local/bin`
- Linux: `/usr/bin/python3`, pyenv, conda/miniconda, asdf, `~/.local/bin`

**PEP 668 (externally-managed-environment)**:
On modern Debian/Ubuntu/Fedora, `pip install` into system Python is blocked.
MelodyMine handles this automatically:
1. Try regular `pip install`
2. If blocked, try `pip install --user`
3. If still blocked, create an isolated venv at `~/.cache/melodymine-venv`

## Use with AI Assistants

MelodyMine ships with a `SKILL.md` — a declarative skill definition that tells any AI assistant how to use this tool. It works with **WorkBuddy**, **OpenClaw**, **Hermes**, and any platform that supports file-based skill definitions.

### Install as a skill

Copy the `MelodyMine` folder to your AI assistant's skills directory:

| Platform | Path |
|----------|------|
| WorkBuddy | `~/.workbuddy/skills/melodymine/` |
| OpenClaw | `~/.openclaw/skills/melodymine/` |
| Hermes | `~/.hermes/skills/melodymine/` |
| Custom | Place wherever your platform reads skill definitions |

Then restart your AI assistant and just say:

> 下载周杰伦的稻香

The AI will handle platform selection, download, metadata tagging, and file renaming — all automatically.

### Standalone CLI usage

Don't have an AI assistant? MelodyMine works perfectly as a plain CLI tool:

```bash
python scripts/music_helper.py download "周杰伦 稻香"
```

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `412 Precondition Failed` | Bilibili API rate-limited | Auto-retries after 2s. Normal usage won't trigger this. |
| `Sign in to confirm you're not a bot` | YouTube bot detection | Export browser cookies, use `--cookies` |
| `KeyError: 'uri'` | spotDL SpotipyFree bug | Search by song name instead of Spotify URL |
| YouTube timeout | YouTube blocked in your region | Add `--proxy socks5://HOST:PORT` |
| No Python found | Python not installed | Install Python 3.10+ from https://python.org |

## File Structure

```
MelodyMine/
├── README.md                        ← You are here
├── LICENSE                          ← MIT
├── SKILL.md                         ← AI assistant skill definition (WorkBuddy / OpenClaw / Hermes)
├── .gitignore
├── scripts/
│   ├── music_helper.py              ← Main script (setup/check/search/download)
│   ├── spotify_helper.py            ← Advanced spotDL operations (sync/save/meta)
│   └── requirements.txt             ← Python dependencies
└── references/
    ├── usage.md                     ← spotDL CLI reference
    └── config.md                    ← spotDL configuration reference
```

## Technical Details

### Bilibili wbi Search

MelodyMine implements Bilibili's wbi signing algorithm to call the official search API directly, bypassing yt-dlp's broken `bilisearch:` extractor. This returns reliable search results with video IDs (BV numbers), which are then passed to yt-dlp for the actual audio download.

### Audio Pipeline

```
Search (wbi API / yt-dlp) → yt-dlp download (bestaudio) → ffmpeg convert (mp3/flac)
  → embed thumbnail → metadata enhancement (ID3 tags + rename)
```

## License

MIT — see [LICENSE](LICENSE).

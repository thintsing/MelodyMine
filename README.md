<div align="center">

# MelodyMine

### Multi-Platform Music Downloader & Metadata Engine

[![CI](https://img.shields.io/github/actions/workflow/status/thintsing/MelodyMine/ci.yml?branch=main&logo=github&label=CI)](https://github.com/thintsing/MelodyMine/actions)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxwYXRoIGQ9Ik0xMiAyTDMgN3YxMGw5IDUgOS01VjdsLTktNXptMCAyLjJMMTguNSA3IDEyIDEwLjIgNS41IDcuMiAxMiA0LjJ6TTUgOC4ybDYgMy4zIDYtMy4zVjE1bC02IDMuMy02LTMuM1Y4LjJ6Ii8+PC9zdmc+)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-10%2B-orange)](#supported-platforms)
[![Tests](https://img.shields.io/badge/tests-58%20passing-brightgreen?logo=pytest)](tests/)

[English](README.md) | [简体中文](README.zh-CN.md)

Search, download, and tag music from **10+ platforms** — with lossless FLAC, auto metadata, synced lyrics, and zero-config setup. One CLI to rule them all.

</div>

---

## Highlights

| Capability | Details |
| :--- | :--- |
| **10+ Sources** | Bilibili, YouTube, YouTube Music, Spotify, Soulseek P2P, Kuwo, Audius, NetEase, SoundCloud, Bandcamp |
| **Lossless Audio** | FLAC / WAV / ALAC from Kuwo, Soulseek, NetEase — auto-detected per source |
| **Smart Metadata** | MusicBrainz + NetEase + iTunes multi-source lookup, cover art embedding, auto rename |
| **Synced Lyrics** | LRCLIB integration — time-synced `.lrc` files saved alongside every track |
| **Zero Config** | Auto-detects Python runtime, installs deps, finds ffmpeg — one `setup` command |
| **AI-Native** | Runs as a standalone CLI or as a file-based skill for AI assistants |
| **Stdlib-First** | API clients use Python stdlib only — minimal dependencies, maximum portability |

## Supported Platforms

| Platform | Type | Auth | Lossless | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **Bilibili** | Search + Download | None | Via yt-dlp | Default for Chinese queries; WBI API search |
| **YouTube** | Search + Download | Optional | Via yt-dlp | Default for international queries; proxy support |
| **YouTube Music** | Search + Download | None | Via yt-dlp | Catalog search via `ytmusicapi` |
| **Spotify** | URL Download | None | Via spotDL | Paste any Spotify URL; auto-installs spotDL |
| **Soulseek** | P2P Search + Download | Username/Pass | Native FLAC | Multi-candidate retry; persistent session |
| **Kuwo** | Search + Direct Download | None | Native FLAC | Third-party CDN resolution; lossless & high-bitrate |
| **Audius** | Search + Stream | None | 320kbps MP3 | Web3 music platform; zero auth required |
| **NetEase** | URL Resolve + Download | None | 128kbps MP3 | CDN direct for free songs; auto fallback |
| **SoundCloud** | Direct Download | None | Via yt-dlp | Paste URL directly |
| **Bandcamp** | Direct Download | None | Via yt-dlp | Paste URL directly |

## Quick Start

```bash
# One-time setup (auto-detects Python, installs deps, finds ffmpeg)
python scripts/music_helper.py setup

# Download — just type the song name
python scripts/music_helper.py download "周杰伦 稻香"
python scripts/music_helper.py download "The Weeknd Blinding Lights"

# Lossless FLAC from Kuwo
python scripts/music_helper.py download "周杰伦 稻香" --platform kuwo --format flac

# Paste any URL
python scripts/music_helper.py download "https://open.spotify.com/track/..."
python scripts/music_helper.py download "https://music.163.com/song?id=185809"
```

## Usage

### Search & Download

```bash
# Search only — see results before committing
python scripts/music_helper.py search "周杰伦 稻香" --platform kuwo

# Pick a specific search result
python scripts/music_helper.py download "稻香" --index 2

# Force a platform
python scripts/music_helper.py download "周杰伦 稻香" --platform bilibili
python scripts/music_helper.py download "Air Supply" --platform soulseek
python scripts/music_music.py download "周杰伦 稻香" --platform kuwo --format flac

# Format & output control
python scripts/music_helper.py download "周杰伦 稻香" --format mp3 --bitrate 320K
python scripts/music_helper.py download "Artist Song" --output "D:\Music"

# Proxy & cookies for restricted networks
python scripts/music_helper.py download "The Weeknd" --proxy socks5://127.0.0.1:7897
python scripts/music_helper.py download "Artist Song" --cookies "cookies.txt"

# Skip lyrics or metadata
python scripts/music_helper.py download "Song" --no-lyrics
python scripts/music_helper.py download "Song" --no-metadata
```

### Metadata & Lyrics

```bash
# Update metadata for an existing file (multi-source lookup + cover + lyrics)
python scripts/music_helper.py meta "D:\Music\song.mp3"
python scripts/music_helper.py meta "D:\Music\song.mp3" --query "周杰伦 稻香"
```

### Dry Run & JSON

```bash
# Preview what would happen without downloading
python scripts/music_helper.py download "周杰伦 稻香" --platform kuwo --dry-run

# Machine-readable output for automation
python scripts/music_helper.py download "周杰伦 稻香" --json
```

## CLI Reference

```
python scripts/music_helper.py download "query" [options]

Options:
  --platform {auto,bilibili,youtube,ytmusic,soulseek,kuwo}
                                      Platform to search (default: auto)
  --format {auto,mp3,flac,m4a,opus,wav,vorbis}
                                      Output format (default: auto)
  --output PATH                       Output directory
  --proxy URL                         Proxy URL (e.g. socks5://host:port)
  --cookies PATH                      cookies.txt for YouTube
  --bitrate RATE                      Audio bitrate (e.g. 320K)
  --index N                           Search result index (1-based)
  --no-thumbnail                      Skip cover art embedding
  --no-lyrics                         Skip lyrics fetching
  --no-metadata                       Skip metadata enhancement
  --dry-run                           Preview without executing
  --json                              Machine-readable JSON output
  --debug                             Write session log for troubleshooting
  --slsk-user USER                    Soulseek username (or SLSK_USERNAME env)
  --slsk-pass PASS                    Soulseek password (or SLSK_PASSWORD env)

python scripts/music_helper.py meta "filepath" [options]

Options:
  --query QUERY                       Search query for metadata lookup
  --no-thumbnail                      Skip cover art embedding
  --no-lyrics                         Skip lyrics fetching
  --json                              Machine-readable JSON output
```

## Platform Routing

| Input | Route | Fallback Chain |
| :--- | :--- | :--- |
| Chinese query | Auto → Bilibili | Soulseek → Bilibili → YouTube |
| English / international query | Auto → YouTube | Soulseek → YouTube |
| `--platform kuwo` | Kuwo direct | Kuwo search → CDN download |
| Spotify URL | spotDL | — |
| NetEase URL | NetEase CDN | NetEase → Bilibili → YouTube |
| YouTube / SoundCloud / Bandcamp URL | yt-dlp direct | — |
| `--platform soulseek` | Soulseek P2P | Soulseek → YouTube |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    music_helper.py                       │
│              (CLI entry + platform dispatch)             │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│ Bilibili │ YouTube  │  Kuwo    │ Soulseek │  NetEase    │
│  Pipeline│ Pipeline │ Pipeline │ Pipeline │  Pipeline   │
├──────────┴──────────┴──────────┴──────────┴─────────────┤
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  metadata.py │  │ lyrics_client│  │ melodymine    │  │
│  │  (MusicBrainz│  │ (LRCLIB API) │  │ _common.py    │  │
│  │  + NetEase + │  │ synced .lrc  │  │ (Python/venv/ │  │
│  │  iTunes +    │  │ plain lyrics │  │  pip/ffmpeg)  │  │
│  │  cover art)  │  │              │  │               │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │bili_     │ │kuwo_     │ │audius_   │ │netease_   │  │
│  │client.py │ │client.py │ │client.py │ │client.py  │  │
│  │(WBI API) │ │(3rd-party│ │(Audius   │ │(CDN URL)  │  │
│  │          │ │ CDN API) │ │ REST API)│ │           │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ytmusic_  │ │soulseek_ │ │mbrainz_  │ │cover_     │  │
│  │client.py │ │client.py │ │client.py │ │client.py  │  │
│  │(ytmusic- │ │(aioslsk  │ │(Music-   │ │(URL→file) │  │
│  │ api)     │ │ P2P)     │ │ Brainz)  │ │           │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
└─────────────────────────────────────────────────────────┘
```

## AI Skill Integration

Drop MelodyMine into any AI assistant's skill directory:

| Platform | Path |
| :--- | :--- |
| WorkBuddy | `~/.workbuddy/skills/melodymine/` |
| OpenClaw | `~/.openclaw/workspace/skills/melodymine/` |
| Hermes | `~/.hermes/skills/melodymine/` |

Then just ask naturally:

```text
下载周杰伦的稻香，要无损音质
Download Blinding Lights by The Weeknd
下载这个 Spotify 链接 https://open.spotify.com/track/...
```

## Testing

```bash
# Run all 58 tests
python -m pytest tests/ -v

# Run a specific test module
python -m unittest tests.test_new_clients -v
```

## File Structure

```
MelodyMine/
├── scripts/
│   ├── music_helper.py        # CLI entry + platform dispatch + download pipelines
│   ├── melodymine_common.py   # Shared infra: Python/venv/pip/ffmpeg/proxy detection
│   ├── metadata.py            # Multi-source metadata (MusicBrainz + NetEase + iTunes)
│   ├── spotify_helper.py      # Advanced spotDL operations (playlist sync, URL resolve)
│   ├── bili_client.py         # Bilibili WBI API search (stdlib only)
│   ├── kuwo_client.py         # Kuwo Music search + CDN download URL (stdlib only)
│   ├── audius_client.py       # Audius Web3 music search + stream (stdlib only)
│   ├── kugou_client.py        # Kugou Music search + download (stdlib only)
│   ├── migu_client.py         # Migu Music search + download (stdlib only)
│   ├── netease_client.py      # NetEase Cloud Music API (stdlib only)
│   ├── ytmusic_client.py      # YouTube Music API search (ytmusicapi)
│   ├── soulseek_client.py     # Soulseek P2P search/download (aioslsk)
│   ├── lyrics_client.py       # LRCLIB lyrics API — synced + plain (stdlib only)
│   ├── mbrainz_client.py      # MusicBrainz metadata lookup (stdlib only)
│   └── cover_client.py        # Cover art downloader (stdlib only)
├── tests/                     # 58 unit tests (stdlib unittest + mocked HTTP)
├── .github/workflows/ci.yml   # GitHub Actions CI (ruff + pytest)
├── SKILL.md                   # AI assistant skill definition
└── references/                # spotDL CLI & config reference docs
```

## Disclaimer

MelodyMine is for **personal learning and archival use only**. Downloading copyrighted audio may be illegal in your jurisdiction. Do not distribute, share, or monetize downloaded files. You are solely responsible for complying with your local laws and the terms of service of each platform.

This project does not host, store, or transmit any copyrighted content, does not bypass DRM, and is not affiliated with or endorsed by any of the mentioned platforms.

## License

MIT

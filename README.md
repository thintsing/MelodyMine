# MelodyMine

[简体中文](README.zh-CN.md)

Download music from Bilibili, YouTube, YouTube Music, Spotify, and Soulseek (P2P) with automatic search, audio conversion, metadata cleanup, and zero-config dependency setup.

MelodyMine runs as a standalone CLI or as a file-based skill for AI assistants — WorkBuddy, Hermes, and OpenClaw. It auto-detects each platform's bundled Python runtime (WorkBuddy/Hermes ship one; OpenClaw users install Python once), so first-run setup is a single command on any of them.

## Features

- Bilibili for Chinese music queries, using direct WBI search plus `yt-dlp`.
- YouTube for English and international music queries.
- YouTube Music catalog search via `ytmusicapi` (no cookies needed for search).
- Spotify URL downloads through spotDL.
- Soulseek P2P downloads via `aioslsk` — multi-candidate retry with FLAC→MP3 fallback.
- Automatic, zero-config setup: auto-detects the host assistant's Python runtime (WorkBuddy/Hermes bundled, uv-managed, or system), installs pip packages, and falls back to `imageio-ffmpeg` for ffmpeg.
- Shared dependency layer (`melodymine_common.py`) with a unified venv — dependencies install once and are reused across both helpers and every supported assistant.
- Metadata cleanup with title, artist, album, cover, and `Artist - Title` renaming.
- Proxy and cookies support for restricted networks or YouTube bot checks.

## Quick Start

From the repository or skill root:

```bash
python scripts/music_helper.py setup
python scripts/music_helper.py download "周杰伦 稻香"
python scripts/music_helper.py download "The Weeknd Blinding Lights"
```

The only hard prerequisite is Python 3.10+. `setup` installs the Python packages MelodyMine needs.

## Common Commands

Download a Chinese song. Auto mode prefers Bilibili:

```bash
python scripts/music_helper.py download "周杰伦 稻香"
```

Download an English song. Auto mode prefers YouTube:

```bash
python scripts/music_helper.py download "The Weeknd Blinding Lights"
```

Download from a Spotify URL:

```bash
python scripts/music_helper.py download "https://open.spotify.com/track/..."
```

Download from a NetEase URL (resolved to song name, then Bilibili/YouTube):

```bash
python scripts/music_helper.py download "https://music.163.com/song?id=185809"
```

Download from a direct URL (YouTube / SoundCloud / Bandcamp):

```bash
python scripts/music_helper.py download "https://www.youtube.com/watch?v=..."
python scripts/music_helper.py download "https://soundcloud.com/artist/song"
python scripts/music_helper.py download "https://artist.bandcamp.com/track/song"
```

Search without downloading:

```bash
python scripts/music_helper.py search "周杰伦 稻香"
python scripts/music_helper.py search "The Weeknd" --platform youtube
```

Force a platform:

```bash
python scripts/music_helper.py download "周杰伦 稻香" --platform bilibili
python scripts/music_helper.py download "The Weeknd Blinding Lights" --platform youtube
python scripts/music_helper.py download "Air Supply Complete" --platform soulseek
```

Choose format, bitrate, output folder, or search result:

```bash
python scripts/music_helper.py download "周杰伦 稻香" --format flac --bitrate 320K
python scripts/music_helper.py download "稻香" --index 2
python scripts/music_helper.py download "Artist Song" --output "D:\Music"
```

Use a proxy for YouTube when direct access fails:

```bash
python scripts/music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://HOST:PORT
```

Use cookies when YouTube asks for sign-in or bot confirmation:

```bash
python scripts/music_helper.py download "Artist Song" --cookies "D:\path\cookies.txt"
```

Update metadata for an already-downloaded file:

```bash
python scripts/music_helper.py meta "D:\Music\song.mp3"
python scripts/music_helper.py meta "D:\Music\song.mp3" --query "周杰伦 稻香"
```

Check dependencies:

```bash
python scripts/music_helper.py check
```

## CLI Options

```text
python scripts/music_helper.py download "query" [options]

Options:
  --platform {auto,bilibili,youtube,ytmusic,soulseek}
                                      Default: auto
  --format {auto,mp3,flac,m4a,opus,wav,vorbis}
                                      Default: auto (flac if lossless, else mp3 320K)
  --output PATH
  --proxy URL                         e.g. socks5://host:port
  --cookies PATH                      cookies.txt for YouTube checks
  --bitrate RATE                      e.g. 320K
  --index N                           1-based search result index
  --no-thumbnail
  --no-metadata
  --dry-run                           Preview command without executing
  --json                              Machine-readable JSON output
  --slsk-user USER                    Soulseek username (or set SLSK_USERNAME env var)
  --slsk-pass PASS                    Soulseek password (or set SLSK_PASSWORD env var)

python scripts/music_helper.py meta "filepath" [options]

Options:
  --query QUERY                       Search query for metadata lookup (default: derive from filename)
  --no-thumbnail                      Skip cover art embedding
  --json                              Machine-readable JSON output
```

## Platform Routing

| Input | Default Route | Notes |
| --- | --- | --- |
| Chinese query | Bilibili | No proxy expected. Falls back to YouTube if needed. |
| English or non-Chinese query | YouTube | Try direct first; add proxy after network failure. |
| Spotify URL | spotDL | Auto-installs spotDL on first use if possible. |
| NetEase URL (`music.163.com`) | NetEase direct → Bilibili/YouTube | Song name extracted via NetEase API. Tries NetEase CDN direct download first (free songs), falls back to Bilibili/YouTube if copyrighted. |
| YouTube/SoundCloud/Bandcamp URL | yt-dlp direct | No search step — downloads the URL directly. YouTube may need `--proxy`. |
| Soulseek P2P (`--platform soulseek`) | Soulseek network | Searches direct from sharers. Requires `SLSK_USERNAME` and `SLSK_PASSWORD` env vars. Downloads via single persistent session with multi-candidate retry. Auto-fallback after YouTube. Proxy auto-detected from `ALL_PROXY`/`HTTP_PROXY` env vars or common Clash ports (7897/7890/1080); proxies all connections (server + peer). |
| Chinese query → YouTube fail → Soulseek | Auto-fallback | When Bilibili & YouTube both fail, Soulseek is tried automatically. |

## Advanced Spotify Operations

Use `scripts/spotify_helper.py` for playlist sync, metadata-only saves, URL resolution, or metadata updates:

```bash
python scripts/spotify_helper.py sync "https://open.spotify.com/playlist/..." --save-file playlist.spotdl
python scripts/spotify_helper.py save "https://open.spotify.com/album/..." --save-file album.spotdl
python scripts/spotify_helper.py url "Artist - Song"
python scripts/spotify_helper.py meta "D:\Music\song.mp3"
python scripts/spotify_helper.py meta "D:\Music\song.mp3" --query "Artist - Song"
```

See `references/usage.md` for spotDL option details and `references/config.md` for spotDL configuration fields.

## Install As An AI Skill

Copy this folder to your assistant's skills directory:

| Platform | Example path |
| --- | --- |
| WorkBuddy | `~/.workbuddy/skills/melodymine/` |
| OpenClaw | `~/.openclaw/workspace/skills/melodymine/` |
| Hermes | `~/.hermes/skills/melodymine/` |
| Custom | Any directory your assistant scans for file-based skills |

> Runtime note: WorkBuddy and Hermes ship a bundled Python that MelodyMine auto-detects on first run. OpenClaw runs on Node.js and does **not** bundle Python, so OpenClaw users must install Python 3.10+ from python.org before first use — `setup` will then locate it.

Then restart the assistant and ask naturally:

```text
下载周杰伦的稻香
Download Blinding Lights by The Weeknd
下载这个 https://open.spotify.com/track/...
```

The assistant should read `SKILL.md`, run setup if needed, execute the download command, and report the saved path.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| No Python found | Install Python 3.10+ from python.org, then rerun setup. |
| Bilibili `412 Precondition Failed` | Retry after a few seconds; the helper already retries once. |
| YouTube timeout | Retry with `--proxy socks5://HOST:PORT` if you have a proxy. |
| YouTube asks for sign-in or bot confirmation | Export YouTube cookies to cookies.txt and pass `--cookies PATH`. |
| Spotify `KeyError: 'uri'` | Search by song name instead of Spotify URL, or use `spotify_helper.py --use-official-api` when appropriate. |
| Metadata is wrong | Retry with a more exact `Artist Song` query or add `--no-metadata`. |

## File Structure

```text
MelodyMine/
├── SKILL.md
├── README.md
├── scripts/
│   ├── melodymine_common.py   # Shared infra: Python/venv/pip/ffmpeg/proxy detection
│   ├── music_helper.py       # Main setup/search/download helper
│   ├── spotify_helper.py     # Advanced spotDL operations
│   ├── soulseek_client.py    # Soulseek P2P search/download (aioslsk)
│   ├── bili_client.py        # Bilibili WBI API search (stdlib only)
│   ├── netease_client.py     # NetEase Cloud Music API client (stdlib only)
│   ├── ytmusic_client.py     # YouTube Music API search (ytmusicapi)
│   ├── mbrainz_client.py     # MusicBrainz metadata lookup (stdlib only)
│   ├── cover_client.py       # Cover art downloader (stdlib only)
│   └── requirements.txt
├── tests/
│   ├── test_helpers.py       # Unit tests for pure functions (stdlib unittest)
│   ├── test_api_clients.py   # Unit tests for API client modules
│   ├── test_ytmusic_client.py# Unit tests for YouTube Music search
│   └── test_soulseek_client.py # Unit tests for Soulseek client helpers
└── references/
    ├── usage.md              # spotDL CLI reference
    └── config.md             # spotDL config reference
```

## Disclaimer

MelodyMine is for **personal learning and archival use only**. Downloading copyrighted audio may be illegal in your jurisdiction regardless of intent. Do not distribute, share, or monetize downloaded files. You are solely responsible for complying with your local laws and the terms of service of Bilibili, YouTube, and Spotify.

This project:
- does not host, store, or transmit any copyrighted content,
- does not bypass digital rights management (DRM),
- is not affiliated with or endorsed by Bilibili, YouTube, Spotify, NetEase, Apple, or MusicBrainz.

If you are a rights holder and believe this tool facilitates infringement, open an issue. The maintainers will cooperate.

## License

MIT. See `LICENSE`.

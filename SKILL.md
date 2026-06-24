---
name: melodymine
description: "Download music with MelodyMine from Bilibili, YouTube, Spotify URLs, and NetEase URLs. Use when the user asks to download/save songs, albums, playlists, music URLs, Chinese songs, English songs, Spotify tracks, NetEase/网易云 links, Bilibili/YouTube audio, FLAC/MP3 music, or says phrases like 下载歌曲, 下载音乐, 下载这首歌, 下载歌单, 下载这个链接, 用 MelodyMine 下载, download music, download song, save this track, sync Spotify playlist."
---

# MelodyMine

Use MelodyMine to execute music downloads directly. Do not only explain commands unless the user asks for explanation.

Assume commands run from the skill root directory unless the assistant platform provides a different skill path.

## First Run

On a new machine, run setup once before downloading:

```bash
python scripts/music_helper.py setup
```

If setup fails because Python is missing, ask the user to install Python 3.10+ and stop. The helper installs `yt-dlp`, `requests`, `pysocks`, `imageio-ffmpeg`, and locates ffmpeg automatically.

For later requests, use `check` only when dependency health is uncertain:

```bash
python scripts/music_helper.py check
```

## Choose The Command

Use `scripts/music_helper.py` for normal search and download:

```bash
python scripts/music_helper.py download "query"
python scripts/music_helper.py search "query"
```

Use `scripts/spotify_helper.py` only for advanced Spotify operations such as playlist sync, metadata-only save, URL resolution, or updating metadata:

```bash
python scripts/spotify_helper.py sync "https://open.spotify.com/playlist/..." --save-file playlist.spotdl
python scripts/spotify_helper.py save "https://open.spotify.com/album/..." --save-file album.spotdl
python scripts/spotify_helper.py meta "/path/to/song.mp3"
python scripts/spotify_helper.py url "Artist - Song"
```

Read `references/usage.md` only when the user needs advanced spotDL options. Read `references/config.md` only when editing or explaining spotDL configuration.

## Download Workflow

1. Extract the song, artist, album, playlist, URL, requested format, output path, proxy, and search-result index from the user request.
2. If this is the first MelodyMine use on the machine, run `setup` first. Otherwise `download` and `check` auto-ensure dependencies — no explicit `setup` needed.
3. Select platform:
   - Spotify URL: pass the URL to `music_helper.py download`.
   - NetEase URL (`music.163.com/song?id=xxx`): pass the URL to `music_helper.py download` — it resolves the song name first, then downloads via Bilibili/YouTube.
   - Query containing Chinese characters: use auto mode, which prefers Bilibili.
   - English or non-Chinese query: use auto mode, which prefers YouTube.
4. Add options requested by the user.
5. Run the command.
6. Report the saved path, format, and any fallback or warning.

## Core Examples

Chinese song, default FLAC:

```bash
python scripts/music_helper.py download "周杰伦 稻香"
```

English song:

```bash
python scripts/music_helper.py download "The Weeknd Blinding Lights"
```

Spotify URL:

```bash
python scripts/music_helper.py download "https://open.spotify.com/track/..."
```

NetEase URL (resolved to song name, then downloaded via Bilibili/YouTube):

```bash
python scripts/music_helper.py download "https://music.163.com/song?id=185809"
```

Force platform:

```bash
python scripts/music_helper.py download "周杰伦 稻香" --platform bilibili
python scripts/music_helper.py download "The Weeknd Blinding Lights" --platform youtube
```

Specify format, bitrate, output, or result index:

```bash
python scripts/music_helper.py download "周杰伦 稻香" --format flac --bitrate 320K
python scripts/music_helper.py download "稻香" --index 2
python scripts/music_helper.py download "Artist Song" --output "/path/to/music"
```

Use a proxy for YouTube when direct access fails:

```bash
python scripts/music_helper.py download "The Weeknd Blinding Lights" --proxy socks5://HOST:PORT
```

Use cookies when YouTube reports bot/sign-in checks:

```bash
python scripts/music_helper.py download "Artist Song" --cookies "/path/to/cookies.txt"
```

## Options

`music_helper.py download` supports:

- `--platform {auto,bilibili,youtube}`: default `auto`.
- `--format {mp3,flac,m4a,opus,wav,vorbis}`: default `flac`.
- `--output PATH`: default platform music folder.
- `--proxy URL`: for YouTube or Spotify download networking.
- `--cookies PATH`: cookies.txt for YouTube bot/sign-in checks.
- `--bitrate RATE`: for example `320K` or `128K`.
- `--index N`: 1-based search result index.
- `--no-thumbnail`: skip cover embedding.
- `--no-metadata`: skip multi-source metadata lookup, ID3 cleanup, and file rename.
- `--dry-run`: print the command that would run without executing.
- `--json`: output machine-readable JSON (use with `--dry-run` or after a successful download).
- `--debug`: write a session log to `~/.melodymine/last_run.log` for troubleshooting.

## Platform Behavior

| Input | Primary Path | Notes |
| --- | --- | --- |
| Chinese query | Bilibili | No proxy expected. If yt-dlp hits 412, falls back to Bilibili API direct (Tier 2), then YouTube. |
| English/non-Chinese query | YouTube | Try direct first. Add proxy only after network failure. |
| Spotify URL | spotDL through `music_helper.py` | May need proxy in restricted regions. For playlist sync use `spotify_helper.py`. |
| NetEase URL (`music.163.com/song?id=xxx`) | Resolved to song name, then Bilibili/YouTube | The URL is translated to "Artist Title" via NetEase API, then downloaded via the normal pipeline. |

## Error Handling

Execute the first matching row. Do not explain the table to the user — just run the recovery action and report the outcome.

| Symptom (match against stderr/output) | Recovery action (run this, don't just suggest it) |
| --- | --- |
| `412 Precondition Failed` during Bilibili download | The helper already retries once and falls back to Bilibili API direct, then YouTube. If all tiers failed, tell the user Bilibili is rate-limiting and retry the same command after 10s. |
| YouTube `timeout` / `unreachable` / connection refused | Ask the user for a proxy, then retry: `download "<query>" --proxy socks5://HOST:PORT`. Do not retry without a proxy if the first attempt already timed out. |
| YouTube `Sign in to confirm you're not a bot` | Ask the user to export cookies.txt (e.g. via "Get cookies.txt" browser extension for YouTube), then retry: `download "<query>" --cookies /path/cookies.txt`. |
| Spotify `KeyError: 'uri'` | Extract the track name from the Spotify URL or ask the user for it, then download by name instead: `download "Artist Song"`. Do not retry the same Spotify URL. |
| `No results` on any platform | Try: (1) `Artist Title` format, (2) force the other platform via `--platform`, (3) broaden the query. Try up to 2 variants before reporting failure to the user. |
| Download succeeds but `metadata is wrong` | Retry once with `--no-metadata` to at least fix the filename, then offer the user a manual retry with a more exact `Artist Song` query. |
| `spotdl` not installed / install failed | Fall back to searching the song name via `download "Artist Song"` (Bilibili/YouTube path). Do not block on spotDL. |

General rules:
- If a recovery action needs information from the user (proxy, cookies, track name), ask once, then proceed.
- If the same error recurs after the recovery action, stop and report the raw error to the user — do not loop.
- Never silently retry the identical failing command more than twice.

## Reporting

After a successful command, tell the user:

- the downloaded song or source URL,
- the output directory or file path printed by the helper,
- the format,
- whether fallback, proxy, cookies, or metadata cleanup was used.

If the command fails, summarize the real error and the next concrete retry command.

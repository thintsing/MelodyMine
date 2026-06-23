---
name: melodymine
description: "Download music with MelodyMine from Bilibili, YouTube, and Spotify URLs. Use when the user asks to download/save songs, albums, playlists, music URLs, Chinese songs, English songs, Spotify tracks, Bilibili/YouTube audio, FLAC/MP3 music, or says phrases like 下载歌曲, 下载音乐, 下载这首歌, 下载歌单, 用 MelodyMine 下载, download music, download song, save this track, sync Spotify playlist."
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
2. Run setup first if this is the first MelodyMine use on the machine.
3. Select platform:
   - Spotify URL: pass the URL to `music_helper.py download`.
   - Query containing Chinese characters: use auto mode, which prefers Bilibili.
   - English or non-Chinese query: use auto mode, which prefers YouTube.
4. Add options requested by the user.
5. Run the command.
6. Report the saved path, format, and any fallback or warning.

## Core Examples

Chinese song, default MP3:

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
- `--format {mp3,flac,m4a,opus,wav,vorbis}`: default `mp3`.
- `--output PATH`: default platform music folder.
- `--proxy URL`: for YouTube or Spotify download networking.
- `--cookies PATH`: cookies.txt for YouTube bot/sign-in checks.
- `--bitrate RATE`: for example `320K` or `128K`.
- `--index N`: 1-based search result index.
- `--no-thumbnail`: skip cover embedding.
- `--no-metadata`: skip NetEase lookup, ID3 cleanup, and file rename.

## Platform Behavior

| Input | Primary Path | Notes |
| --- | --- | --- |
| Chinese query | Bilibili | No proxy expected. Falls back to YouTube if Bilibili fails. |
| English/non-Chinese query | YouTube | Try direct first. Add proxy only after network failure. |
| Spotify URL | spotDL through `music_helper.py` | May need proxy in restricted regions. For playlist sync use `spotify_helper.py`. |

## Error Handling

| Symptom | Action |
| --- | --- |
| Bilibili `412 Precondition Failed` | Retry after a few seconds; the helper already retries once. |
| YouTube timeout or unreachable | Retry with `--proxy socks5://HOST:PORT` if the user can provide one. |
| YouTube asks to sign in or confirms bot detection | Ask for a cookies.txt file and retry with `--cookies PATH`. |
| Spotify `KeyError: 'uri'` | Retry by searching the song name instead of using the Spotify URL, or use `spotify_helper.py` with `--use-official-api` if credentials/auth are available. |
| No results | Broaden the query, try artist + title, or force the other platform. |
| Download succeeds but metadata is wrong | Retry with `--no-metadata`, or use a more exact `Artist Song` query. |

## Reporting

After a successful command, tell the user:

- the downloaded song or source URL,
- the output directory or file path printed by the helper,
- the format,
- whether fallback, proxy, cookies, or metadata cleanup was used.

If the command fails, summarize the real error and the next concrete retry command.

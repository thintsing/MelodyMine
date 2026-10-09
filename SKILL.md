---
name: melodymine
description: "Download music with MelodyMine from Bilibili, YouTube, YouTube Music, Spotify URLs, NetEase URLs, Kuwo, Kugou, Audius, and Soulseek P2P. Use when the user asks to download/save songs, albums, playlists, music URLs, Chinese songs, English songs, Spotify tracks, NetEase/网易云 links, Bilibili/YouTube audio, FLAC/MP3 music, lyrics/歌词, backfill lyrics for a library, save a multi-part Bilibili audiobook (有声书/听书) into Audiobookshelf, or says phrases like 下载歌曲, 下载音乐, 下载这首歌, 下载歌单, 下载这个链接, 下载有声书, 放到听书目录, 用 MelodyMine 下载, download music, download song, save this track, sync Spotify playlist."
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
python scripts/spotify_helper.py meta "/path/to/song.mp3" --query "Artist - Song"
python scripts/spotify_helper.py url "Artist - Song"
```

You can also update metadata for any existing audio file with `music_helper.py meta`:

```bash
python scripts/music_helper.py meta "/path/to/song.mp3"
python scripts/music_helper.py meta "/path/to/song.mp3" --query "周杰伦 稻香"
```

Backfill lyrics for a whole library with `music_helper.py lyrics-sync`. It reads each track's tags (or falls back to its filename), fetches synced lyrics, and writes a sibling `.lrc` with the same basename. The audio files are never modified:

```bash
python scripts/music_helper.py lyrics-sync "/path/to/music"
python scripts/music_helper.py lyrics-sync "/path/to/music" --dry-run
python scripts/music_helper.py lyrics-sync "/path/to/music" --overwrite --json
```

Read `references/usage.md` only when the user needs advanced spotDL options. Read `references/config.md` only when editing or explaining spotDL configuration.

## Download Workflow

1. Extract the song, artist, album, playlist, URL, requested format, output path, proxy, and search-result index from the user request.
2. If this is the first MelodyMine use on the machine, run `setup` first. Otherwise `download` and `check` auto-ensure dependencies — no explicit `setup` needed.
3. Select platform:
   - Spotify URL: pass the URL to `music_helper.py download`.
   - NetEase URL (`music.163.com/song?id=xxx`): pass the URL to `music_helper.py download` — it resolves the song name first, then downloads via NetEase direct → Bilibili → YouTube.
   - Bilibili URL (`bilibili.com/video/BV...`, `/list/...?bvid=`, or a `b23.tv` short link): pass the URL as-is — it is routed straight to Bilibili with no search step. The bvid is extracted when present; `b23.tv` short links are handed to yt-dlp, which follows the redirect.
   - Query containing Chinese characters: use auto mode, which prefers Kugou → Kuwo → Soulseek → Bilibili → YouTube. The two CJK catalogues answer from their own CDN with the ranked studio original, so this is both faster and more accurate than searching a video platform.
   - English or non-Chinese query: use auto mode, which prefers Soulseek → YouTube.
   - Force `--platform bilibili` when you specifically want a video-platform upload (live sets, remixes, MV audio) rather than the catalogue original.
4. Add options requested by the user. If the user wants a fast download without Soulseek, add `--quick`.
5. Run the command.
6. Report the saved path, format, fallback tier, and any warning.

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

Bilibili URL (bvid extracted, no search step):

```bash
python scripts/music_helper.py download "https://www.bilibili.com/video/BV1TfN2emEZh"
python scripts/music_helper.py download "https://www.bilibili.com/list/ml1266054064?oid=1&bvid=BV1TfN2emEZh"
python scripts/music_helper.py download "https://b23.tv/abcDEF"
```

Kuwo Music (酷我音乐) — search and download directly:

```bash
python scripts/music_helper.py download "周杰伦 稻香" --platform kuwo
python scripts/music_helper.py search "周杰伦" --platform kuwo
```

Kugou Music (酷狗音乐) — search and download directly, best source for Chinese lossless:

```bash
python scripts/music_helper.py download "周杰伦 稻香" --platform kugou --format flac
python scripts/music_helper.py search "周杰伦" --platform kugou
```

Audius — decentralized music streaming (zero auth required):

```bash
python scripts/music_helper.py download "Song Name" --platform audius
python scripts/music_helper.py search "Artist Name" --platform audius
```

YouTube Music — catalog search (no cookies needed):

```bash
python scripts/music_helper.py download "Song Name" --platform ytmusic
python scripts/music_helper.py search "Artist Name" --platform ytmusic
```

Direct URL (YouTube / SoundCloud / Bandcamp — yt-dlp downloads directly, no search):

```bash
python scripts/music_helper.py download "https://www.youtube.com/watch?v=..."
python scripts/music_helper.py download "https://soundcloud.com/artist/song"
python scripts/music_helper.py download "https://artist.bandcamp.com/track/song"
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

Force Soulseek (P2P) for hard-to-find songs or lossless FLAC:

```bash
python scripts/music_helper.py download "Air Supply Complete" --platform soulseek
```

Fast download — skip Soulseek, go straight to Bilibili/YouTube:

```bash
python scripts/music_helper.py download "周杰伦 稻香" --quick
python scripts/music_helper.py download "The Weeknd Blinding Lights" --quick
```

Search Soulseek network only (no download):

```bash
python scripts/music_helper.py search "X Japan FLAC" --platform soulseek
```

Inspect what a platform actually has before downloading — `search --json` returns one machine-readable line, so you can read the real titles, artists and durations instead of guessing from a formatted list:

```bash
python scripts/music_helper.py search "周杰伦 稻香" --platform kugou --json
```

> **Note**: Soulseek requires credentials. Set `SLSK_USERNAME` and `SLSK_PASSWORD` environment variables, or pass `--slsk-user USER --slsk-pass PASS`. Search returns results from all users; download auto-selects the best FLAC from a user with free slots.

## Options

`music_helper.py download` supports:

- `--platform {auto,bilibili,youtube,ytmusic,soulseek,kuwo,kugou,audius}`: default `auto`.
- `--format {auto,mp3,flac,m4a,opus,wav,vorbis}`: default `auto`. `auto` probes the source codec: flac if lossless (flac/alac/wav/pcm), else mp3 320K — no fake-lossless upcast.
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
- `--slsk-user USER`: Soulseek username (or set `SLSK_USERNAME` env var).
- `--slsk-pass PASS`: Soulseek password (or set `SLSK_PASSWORD` env var).
- `--quick`: skip Soulseek P2P tier — go straight to Bilibili/YouTube for faster downloads.
- `--no-lyrics`: skip lyrics fetching and embedding (saves time if you don't need synced lyrics).

`music_helper.py meta "filepath"` supports:

- `--query QUERY`: search query for metadata lookup (default: derive from filename).
- `--no-thumbnail`: skip cover art embedding.
- `--no-lyrics`: skip lyrics fetching and embedding.
- `--json`: output machine-readable JSON after the update.

`music_helper.py search "query"` supports:

- `--platform`: same choices as `download`.
- `--limit N`: number of results (default 5).
- `--json`: emit one JSON line with `ok`, `platform`, `count` and the raw `results`.

In auto mode `search` resolves to the same source `download` would try first — Kugou for a Chinese query, YouTube otherwise — so `--index N` means the same thing in both commands.

`music_helper.py lyrics-sync "directory"` supports:

- `--overwrite`: re-fetch lyrics for tracks that already have a `.lrc`.
- `--dry-run`: report what would be written without touching the disk.
- `--limit N`: stop after N audio files.
- `--json`: emit one JSON line with `scanned`, `written`, `existing`, `not_found`, `no_title` and `failed` counts.

Tracks whose title cannot be determined — no usable tags and a filename like `01.mp3` — are counted as `no_title` and skipped, because wrong lyrics are worse than none.

## Platform Behavior

| Input | Primary Path | Notes |
| --- | --- | --- |
| Chinese query | Kugou → Kuwo → Soulseek → Bilibili → YouTube | The CJK catalogues are tried first: direct CDN, native FLAC, studio original ranked to the top, ~15s and no proxy. Each failure falls through to the next tier, so a VIP-only or missing track still ends up downloaded. Use `--quick` to skip Soulseek. |
| English/non-Chinese query | Soulseek → YouTube | Soulseek first, then YouTube. Use `--quick` to skip Soulseek. Add proxy only after network failure. |
| Spotify URL | spotDL through `music_helper.py` | May need proxy in restricted regions. For playlist sync use `spotify_helper.py`. |
| NetEase URL (`music.163.com/song?id=xxx`) | NetEase direct → Bilibili/YouTube | Resolves song name via NetEase API, tries NetEase CDN direct download first (free songs), falls back to Bilibili/YouTube. |
| Bilibili URL (`bilibili.com`, `b23.tv`) | Bilibili direct | No search step, so there is no risk of grabbing the wrong upload. `b23.tv` short links are resolved by yt-dlp. |
| Force Kuwo (`--platform kuwo`) | Kuwo API direct | Search and download via Kuwo Music API, no auth required. Studio originals rank first. ⚠️ VIP/licensed tracks may resolve to an ~11s preview — the helper detects this, rejects the file and reports it. Retry with `--platform kugou`. |
| Force Kugou (`--platform kugou`) | Kugou API direct | Best source for Chinese lossless FLAC, no auth required. Studio originals rank first. The CDN certificate does not match its hostnames, so audio is fetched over plain HTTP — the URL itself is signed and single-use. |
| Force Audius (`--platform audius`) | Audius decentralized network | Search and stream from Audius P2P network. Zero auth required. Independent artists and remixes — mainstream catalogues are usually missing, so prefer Kuwo/Kugou/Bilibili for known songs. |
| Force YouTube Music (`--platform ytmusic`) | YouTube Music catalog | Search YouTube Music catalog and download via yt-dlp. No cookies needed for search. |
| YouTube/SoundCloud/Bandcamp URL | yt-dlp direct download | No search step — yt-dlp downloads the URL directly. YouTube may need proxy/cookies. |
| Force Soulseek (`--platform soulseek`) | Soulseek P2P network | ⚠️ Requires `SLSK_USERNAME` and `SLSK_PASSWORD` env vars. Downloads the best FLAC from the first user with free slots. |
| Force quick (`--quick`) | Bilibili or YouTube (skip Soulseek) | Skips the Soulseek P2P tier entirely. Useful when Soulseek is slow/unavailable or for faster downloads. |

## Audiobooks (multi-part Bilibili uploads)

For a `bilibili.com/video/BV...` upload whose parts are the chapters of one
book, use the audiobook pipeline instead of `music_helper.py download`. Each
part becomes one `.m4a` tagged album/artist/title/track, so the player can
resume inside a 14-hour book.

```
python scripts/bili_album_probe.py BV1nFcLzaEGb probe.txt   # read the part list first
python scripts/bili_album_dl.py --bvid BV1nFcLzaEGb --out <dir> \
    --album "人类简史：从动物到上帝" --artist "尤瓦尔·赫拉利" --strip-regex "^完整版："
python scripts/bili_album_verify.py <dir>                    # re-derives names/tags from book.json
python scripts/douban_cover.py --out <dir> "书名"             # pick the edition by the infobox
```

- The real book title, author and translator live in the video `desc`, not in
  `title`; P1 is usually a summary, and P2 often carries a `完整版：` prefix.
- `--album`/`--artist` must be set from `desc` — the uploader name is a site
  handle, not the author. Read the probe output before choosing.
- Leave `--comment` empty. A comment, or the `desc` atom ffmpeg inherits from
  the source, becomes the book synopsis, and Audiobookshelf caches it per item
  path and will not drop it afterwards.
- On Windows a Chinese argument does not survive cmd's argv encoding: write a
  small UTF-8 driver that sets `sys.argv` and `exec(compile(open(...)))` the
  downloader.
- `bili_album_verify.py` output (`md5.txt`, `verify.txt`) is what the server
  install is checked against; see `scripts/audiobook_install.sh` for the package
  layout and pack `pkg.tgz` with `--files-from`, since part titles contain spaces.

## Error Handling

Execute the first matching row. Do not explain the table to the user — just run the recovery action and report the outcome.

| Symptom (match against stderr/output) | Recovery action (run this, don't just suggest it) |
| --- | --- |
| `412 Precondition Failed` during Bilibili download | The helper already retries once and falls back to Bilibili API direct, then YouTube. If all tiers failed, tell the user Bilibili is rate-limiting and retry the same command after 10s. |
| YouTube `timeout` / `unreachable` / connection refused | Ask the user for a proxy, then retry: `download "<query>" --proxy socks5://HOST:PORT`. Do not retry without a proxy if the first attempt already timed out. |
| YouTube `Sign in to confirm you're not a bot` | Ask the user to export cookies.txt (e.g. via "Get cookies.txt" browser extension for YouTube), then retry: `download "<query>" --cookies /path/cookies.txt`. |
| Spotify `KeyError: 'uri'` | Extract the track name from the Spotify URL or ask the user for it, then download by name instead: `download "Artist Song"`. Do not retry the same Spotify URL. |
| `No results` on any platform | Try: (1) `Artist Title` format, (2) force the other platform via `--platform`, (3) broaden the query. Try up to 2 variants before reporting failure to the user. |
| `Source returned a preview clip` / `VIP/preview-only` | The platform only licenses a snippet of that track — the file is deleted, nothing was saved. Auto mode already falls through to the next tier on its own, so this only surfaces when a platform was forced. Retry with `--platform kugou`, or drop `--platform` entirely and let auto mode walk the chain. Do not retry the same platform. |
| Downloaded file is a cover, live or 伴奏 version | Auto mode already ranks those below the studio original, so this means the catalogue's top hit genuinely is a cover. Run `search "<query>" --platform kugou --json`, pick the right `hash` by artist, and re-download with `--platform kugou --index N`. |
| `lyrics-sync` reports a high `not_found` count | LRCLIB has no synced lyrics for those tracks. Report the count and the filenames — do not loop. For a specific track you know the real artist/title of, run `meta "<filepath>" --query "Artist - Title"` instead. |
| Soulseek `no results` | Ensure `SLSK_USERNAME` and `SLSK_PASSWORD` are set. Try a broader query with fewer words. |
| Soulseek `credentials not set` / `SLSK_USERNAME not set` | Ask the user to provide Soulseek credentials (set env vars `SLSK_USERNAME` and `SLSK_PASSWORD`, or pass `--slsk-user` `--slsk-pass`). If unavailable, retry with `--quick` to skip Soulseek. |
| Soulseek `download failed` / timeout | The remote user may be offline or have a full queue. Retry the same command — Soulseek picks a different result. |
| Download succeeds but `metadata is wrong` | Retry once with `--no-metadata` to at least fix the filename, then offer the user a manual retry with a more exact `Artist Song` query. For already-downloaded files, use `python scripts/music_helper.py meta "/path/to/song.mp3" --query "Artist Song"`. |
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
- whether fallback, proxy, cookies, metadata cleanup, or lyrics fetching was used.

After `lyrics-sync`, report the scanned/written counts and list the tracks that got `not_found` or `no_title`, so the user knows which ones still need attention.

If the command fails, summarize the real error and the next concrete retry command.

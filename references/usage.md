# MelodyMine — spotDL Usage Reference

Complete command reference for spotDL v4, the engine MelodyMine uses for Spotify URL downloads. MelodyMine's `spotify_helper.py` wraps these operations.

## Operations

| Operation | Description |
|-----------|-------------|
| `download` | Download songs to disk with embedded metadata (default) |
| `save` | Save Spotify metadata to `.spotdl` file without downloading |
| `sync` | Sync local directory with a Spotify playlist/album |
| `meta` | Update metadata on existing audio files |
| `web` | Launch web UI (browser interface) |
| `url` | Get YouTube download URL for Spotify tracks |

## Query Types

| Query | Example |
|-------|---------|
| Spotify track URL | `https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b` |
| Spotify album URL | `https://open.spotify.com/album/4yP0hdKOZPNshxUOjY0cZj` |
| Spotify playlist URL | `https://open.spotify.com/playlist/37i9dQZF1E8UXBoz02kGID` |
| Spotify artist URL | `https://open.spotify.com/artist/1Xyo4u8uXC1ZmMpatF05PJ` |
| Search string | `'The Weeknd - Blinding Lights'` |
| YouTube + Spotify pair | `"https://www.youtube.com/watch?v=XXX\|https://open.spotify.com/track/YYY"` |
| Liked songs | `saved` (requires `--user-auth`) |
| All user playlists | `all-user-playlists` (requires `--user-auth`) |
| All saved playlists | `all-saved-playlists` (requires `--user-auth`) |
| All followed artists | `all-user-followed-artists` (requires `--user-auth`) |
| All saved albums | `all-user-saved-albums` (requires `--user-auth`) |

## Full CLI Options Reference

### Main Options

```
spotdl {download,save,web,sync,meta,url} [options] QUERY
```

### Audio/Lyrics Providers

```
--audio [{youtube,youtube-music,slider-kz,soundcloud,bandcamp,piped} ...]
    Audio provider(s) to use. Multiple = fallback chain.
    Default: youtube-music

--lyrics [{genius,musixmatch,azlyrics,synced} ...]
    Lyrics provider(s). Default: genius azlyrics musixmatch
    Use 'synced' for .lrc synchronized lyrics (requires --generate-lrc)

--genius-access-token GENIUS_TOKEN
    Custom Genius API token for better lyrics results
```

### Spotify Options

```
--user-auth
    Login with your Spotify account (required for liked songs / personal playlists)

--client-id CLIENT_ID
    Spotify app client ID (uses built-in public ID by default)

--client-secret CLIENT_SECRET
    Spotify app client secret

--auth-token AUTH_TOKEN
    Direct Spotify authorization token

--cache-path CACHE_PATH
    Where to store spotipy cache file

--no-cache
    Disable all caching

--max-retries MAX_RETRIES
    Max metadata fetch retries (default: 3)

--headless
    Run in headless mode (no browser popup for auth)

--use-cache-file
    Use local Spotify metadata cache (may be outdated)

--use-official-api
    Force Spotipy official API instead of SpotipyFree
```

### FFmpeg / Quality Options

```
--ffmpeg FFMPEG
    Path to ffmpeg executable (default: system ffmpeg)

--threads THREADS
    Parallel download threads (default: 4)

--bitrate {auto,disable,8k,16k,24k,32k,40k,48k,64k,80k,96k,112k,128k,160k,192k,224k,256k,320k,0-9}
    Output bitrate.
    - auto: match source bitrate
    - disable: skip conversion (best for m4a/opus to preserve quality)
    - 0-9: variable bitrate (VBR)
    Default: 128k

--ffmpeg-args FFMPEG_ARGS
    Extra ffmpeg arguments as a string
```

### Output Options

```
--format {mp3,flac,ogg,opus,m4a,wav}
    Output audio format (default: mp3)

--output OUTPUT
    File naming template. Variables: {title},{artists},{artist},{album},{album-artist},
    {genre},{disc-number},{disc-count},{duration},{year},{original-date},{track-number},
    {tracks-count},{isrc},{track-id},{publisher},{list-length},{list-position},{list-name},{output-ext}
    Default: "{artists} - {title}.{output-ext}"

--save-file SAVE_FILE
    File to save/load song data (.spotdl extension required)
    Use '-' to print to stdout (save operation only)

--preload
    Pre-fetch download URL to speed up downloads

--m3u [M3U]
    Generate M3U playlist. Use {list} or {list[0]} for dynamic naming.

--cookie-file COOKIE_FILE
    Path to cookies.txt (for YouTube Music Premium quality)

--overwrite {skip,metadata,force}
    How to handle existing files:
    - skip: don't re-download (default)
    - metadata: only update metadata
    - force: always re-download

--restrict [{strict,ascii,none}]
    Sanitize filenames for compatibility

--print-errors
    Print failed downloads summary on exit

--save-errors SAVE_ERRORS
    Write error log to file

--sponsor-block
    Remove sponsor segments from YouTube videos

--archive ARCHIVE
    Track downloaded songs to prevent re-downloads

--playlist-numbering
    Use playlist name as album; playlist art as cover art

--scan-for-songs
    Scan output directory for existing files

--fetch-albums
    Download all albums from queried songs

--id3-separator ID3_SEPARATOR
    ID3 tag separator for multi-value fields (mp3 only, default: /)

--ytm-data
    Use YouTube Music metadata instead of Spotify

--add-unavailable
    Include unavailable songs in m3u/archive files

--generate-lrc
    Generate .lrc synchronized lyric files (needs 'synced' provider)

--force-update-metadata
    Re-apply metadata even if file already has it

--sync-without-deleting
    Sync without removing songs no longer in playlist

--max-filename-length MAX_FILENAME_LENGTH
    Enforce max filename length (OS limit still applies)

--yt-dlp-args YT_DLP_ARGS
    Pass extra arguments directly to yt-dlp

--detect-formats [{mp3,flac,ogg,opus,m4a,wav} ...]
    Detect already-downloaded songs in different formats

--redownload
    Re-download in a different format (use with meta + --format)

--skip-album-art
    Skip downloading album art (meta operation)

--ignore-albums [IGNORE_ALBUMS ...]
    Skip songs belonging to specified albums

--skip-explicit
    Skip explicit tracks

--proxy PROXY
    HTTP(s) proxy for downloads (e.g., http://host:port)

--create-skip-file
    Create .skip marker files for successful downloads

--respect-skip-file
    Skip download if .skip file exists for that song

--sync-remove-lrc
    Remove .lrc files when sync removes a song
```

### Web Server Options

```
--host HOST           Web server host (default: localhost)
--port PORT           Web server port (default: 8800)
--keep-alive          Keep server alive when no clients connected
--allowed-origins [ALLOWED_ORIGINS ...]
--web-use-output-dir  Use --output dir instead of session dir
--keep-sessions       Keep session dirs after server closes
--enable-tls          Enable TLS
--cert-file, --key-file, --ca-file  TLS certificate files
```

### Misc Options

```
--log-level {CRITICAL,FATAL,ERROR,WARN,WARNING,INFO,MATCH,DEBUG,NOTSET}
--simple-tui          Simple text UI (no rich formatting)
--log-format          Custom Python logging format string
--download-ffmpeg     Download FFmpeg to spotDL directory
--download-deno       Download Deno to spotDL directory
--generate-config     Generate default config file
--check-for-updates   Check for new version
--version, -v         Show version
```

## Common Workflows

### High Quality Download (YTM Premium)

```bash
# 1. Export cookies from music.youtube.com (use Get cookies.txt browser extension)
# 2. Change YTM quality to highest in settings
spotdl download 'Artist - Song' \
  --format m4a \
  --bitrate disable \
  --cookie-file cookies.txt
```

### Organized Library Download

```bash
spotdl download https://open.spotify.com/album/... \
  --output "{artist}/{album}/{track-number:02d} - {title}.{output-ext}" \
  --format flac
```

### Playlist Sync Workflow

```bash
# Step 1: Initialize (first time)
spotdl sync https://open.spotify.com/playlist/... --save-file my-playlist.spotdl

# Step 2: Sync regularly (adds new, removes deleted)
spotdl sync my-playlist.spotdl

# With M3U generation
spotdl sync my-playlist.spotdl --m3u my-playlist.m3u8
```

### Batch Download with Archive

```bash
spotdl download https://open.spotify.com/artist/... \
  --archive downloaded.txt \
  --threads 8 \
  --print-errors
```

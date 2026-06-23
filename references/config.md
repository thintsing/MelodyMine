# spotDL Configuration Reference

## Config File Location

- **Windows**: `C:\Users\<user>\.spotdl\config.json`
- **Linux/macOS**: `~/.config/spotdl/config.json`
  (fallback: `~/.spotdl/config.json` for pre-v4.4.3)

## Generate Config

```bash
spotdl --generate-config
# Warning: overwrites existing config
```

## Load Config

The config file loads automatically if it exists, or pass `--config` flag explicitly.
To disable auto-loading:

```json
{ "load_config": false }
```

## Full Default Config

```json
{
    "client_id": "f8a606e5583643beaa27ce62c48e3fc1",
    "client_secret": "f6f4c8f73f0649939286cf417c811607",
    "auth_token": null,
    "user_auth": false,
    "headless": false,
    "cache_path": "/Users/username/.spotdl/.spotipy",
    "no_cache": false,
    "max_retries": 3,
    "use_cache_file": false,
    "use_official_api": false,
    "audio_providers": ["youtube-music"],
    "lyrics_providers": ["genius", "azlyrics", "musixmatch"],
    "playlist_numbering": false,
    "scan_for_songs": false,
    "m3u": null,
    "output": "{artists} - {title}.{output-ext}",
    "overwrite": "skip",
    "search_query": null,
    "ffmpeg": "ffmpeg",
    "bitrate": "128k",
    "ffmpeg_args": null,
    "format": "mp3",
    "save_file": null,
    "filter_results": true,
    "album_type": null,
    "threads": 4,
    "cookie_file": null,
    "restrict": null,
    "print_errors": false,
    "sponsor_block": false,
    "preload": false,
    "archive": null,
    "load_config": true,
    "log_level": "INFO",
    "simple_tui": false,
    "fetch_albums": false,
    "id3_separator": "/",
    "ytm_data": false,
    "add_unavailable": false,
    "generate_lrc": false,
    "force_update_metadata": false,
    "only_verified_results": false,
    "sync_without_deleting": false,
    "max_filename_length": null,
    "yt_dlp_args": null,
    "detect_formats": null,
    "save_errors": null,
    "ignore_albums": null,
    "proxy": null,
    "skip_explicit": false,
    "log_format": null,
    "redownload": false,
    "skip_album_art": false,
    "create_skip_file": false,
    "respect_skip_file": false,
    "web_use_output_dir": false,
    "port": 8800,
    "host": "localhost",
    "keep_alive": false,
    "enable_tls": false,
    "key_file": null,
    "cert_file": null,
    "ca_file": null,
    "allowed_origins": null,
    "keep_sessions": false
}
```

## Key Config Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `client_id` / `client_secret` | string | built-in public | Spotify API credentials |
| `audio_providers` | array | `["youtube-music"]` | Audio source priority list |
| `lyrics_providers` | array | `["genius","azlyrics","musixmatch"]` | Lyrics source priority list |
| `output` | string | `{artists} - {title}.{output-ext}` | Filename template |
| `format` | string | `mp3` | Output audio format |
| `bitrate` | string | `128k` | Output bitrate |
| `threads` | int | 4 | Parallel download threads |
| `overwrite` | string | `skip` | Duplicate handling strategy |
| `cookie_file` | string | null | Path to YouTube Music cookies |
| `proxy` | string | null | HTTP proxy URL |
| `generate_lrc` | bool | false | Generate .lrc lyric files |
| `port` | int | 8800 | Web UI port |

## Spotify API Credentials

spotDL ships with public credentials that work for most users. For heavy usage or private
playlists, create your own at https://developer.spotify.com/dashboard:

1. Create app → set redirect URI to `http://localhost:8080`
2. Copy Client ID and Client Secret
3. Add to config or use `--client-id` / `--client-secret` flags

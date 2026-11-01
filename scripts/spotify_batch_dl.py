#!/usr/bin/env python3
"""
Spotify Playlist Batch Downloader — Download tracks from a JSON file.

Takes a JSON file with track list (exported from Spotify via browser or API),
downloads each track via yt-dlp (YouTube search), writes ID3 tags, and
optionally uploads to Plex.

Usage:
    python scripts/spotify_batch_dl.py TRACKS_JSON [options]

Examples:
    # Download tracks from JSON file
    python scripts/spotify_batch_dl.py playlist.json

    # Download and upload to Plex
    python scripts/spotify_batch_dl.py playlist.json --upload-plex

    # Specify output folder and format
    python scripts/spotify_batch_dl.py playlist.json --output "D:\Music\Playlist" --format flac

JSON format:
    {
        "name": "Playlist Name",
        "tracks": [
            {"artist": "Artist Name", "title": "Song Title"},
            ...
        ]
    }
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add scripts dir to path so we can import melodymine modules
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from melodymine_common import (
    DEFAULT_OUTPUT,
    check_module,
    detect_proxy,
    find_ffmpeg,
    make_subprocess_env,
    pip_install,
    run_streaming,
    sanitize_filename,
    set_debug,
)

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import TALB, TIT2, TPE1, TRCK
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False


# pip packages required for full functionality
REQUIRED_PACKAGES = ["yt-dlp", "requests", "pysocks", "imageio-ffmpeg"]


def ensure_deps():
    """Ensure all dependencies are available. Returns (python, yt_dlp_ver, ffmpeg_path) or (None, None, None)."""
    # Use the Python running this script, not a different one
    py = sys.executable
    
    # Check if yt-dlp is installed, if not install it
    if not check_module(py, "yt_dlp"):
        print("  Auto-installing: yt-dlp")
        pip_install(py, ["yt-dlp", "requests", "pysocks"])
    
    # Check if imageio-ffmpeg is installed, if not install it
    if not check_module(py, "imageio_ffmpeg"):
        print("  Auto-installing: imageio-ffmpeg (bundled ffmpeg binary)")
        pip_install(py, ["imageio-ffmpeg"])
    
    ff = find_ffmpeg(py)
    return py, None, ff


def load_tracks_json(json_path):
    """Load track list from JSON file.

    Returns (playlist_name, tracks) or (None, None) on failure.
    """
    try:
        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)
        
        playlist_name = data.get("name", "Unknown Playlist")
        tracks = data.get("tracks", [])
        
        if not tracks:
            print(f"  [!] No tracks found in {json_path}")
            return None, None
        
        # Validate track format
        for i, track in enumerate(tracks):
            if not isinstance(track, dict):
                print(f"  [!] Track {i+1} is not a dict")
                return None, None
            if "artist" not in track or "title" not in track:
                print(f"  [!] Track {i+1} missing 'artist' or 'title'")
                return None, None
        
        return playlist_name, tracks
    except Exception as e:
        print(f"  [!] Failed to load {json_path}: {e}")
        return None, None


def download_track(artist, title, output_dir, fmt="mp3", bitrate="320K",
                   proxy=None, cookies_from_browser=None, python_exe=None, ffmpeg_exe=None):
    """Download a single track via yt-dlp YouTube search.

    Returns the path to the downloaded file, or None on failure.
    """
    if not python_exe:
        python_exe, _, _ = ensure_deps()
    if not python_exe:
        print("  [!] No Python with yt-dlp found. Run 'setup' first.")
        return None

    if not ffmpeg_exe:
        ffmpeg_exe = find_ffmpeg(python_exe)
    if not ffmpeg_exe:
        print("  [!] ffmpeg not found.")
        return None

    query = f"ytsearch1:{artist} - {title}"

    cmd = [
        python_exe, "-m", "yt_dlp",
        "-f", "bestaudio/best",
        "-x",
        "--audio-format", fmt,
        "--audio-quality", bitrate if fmt == "mp3" else "0",
        "--embed-metadata",
        "--embed-thumbnail",
        "-o", str(output_dir / "%(title)s.%(ext)s"),
        "--no-warnings",
        "--newline",
    ]

    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    if ffmpeg_exe:
        cmd.extend(["--ffmpeg-location", ffmpeg_exe])

    cmd.append(query)

    env = make_subprocess_env()

    # Snapshot files before download
    before = set(output_dir.glob("*.mp3")) | set(output_dir.glob("*.flac")) | \
             set(output_dir.glob("*.m4a")) | set(output_dir.glob("*.opus"))

    rc = run_streaming(cmd, env=env)
    if rc != 0:
        return None

    # Find the new file
    after = set(output_dir.glob("*.mp3")) | set(output_dir.glob("*.flac")) | \
            set(output_dir.glob("*.m4a")) | set(output_dir.glob("*.opus"))
    new_files = after - before

    if new_files:
        return list(new_files)[0]
    return None


def write_id3_tags(filepath, artist, title, album, track_num):
    """Write ID3 tags to an audio file using mutagen."""
    if not MUTAGEN_AVAILABLE:
        print(f"  [!] mutagen not available, skipping tags for {filepath.name}")
        return False

    try:
        audio = MutagenFile(filepath)
        if audio is None:
            print(f"  [!] Could not open {filepath.name} for tagging")
            return False

        if audio.tags is None:
            audio.add_tags()

        audio.tags.add(TIT2(encoding=3, text=[title]))
        audio.tags.add(TPE1(encoding=3, text=[artist]))
        audio.tags.add(TALB(encoding=3, text=[album]))
        audio.tags.add(TRCK(encoding=3, text=[str(track_num)]))

        audio.save()
        return True
    except Exception as e:
        print(f"  [!] Failed to write tags to {filepath.name}: {e}")
        return False


def upload_to_plex(local_dir, plex_host="112.112.10.34", plex_port=4422,
                   plex_user="root", plex_key="~/.ssh/melodymine_plex",
                   plex_dir="/home/media/music/Thintsing精选2"):
    """Upload a local directory to Plex server via scp."""
    print(f"\n[UPLOAD] Copying {local_dir} to Plex...")

    cmd = [
        "scp",
        "-i", os.path.expanduser(plex_key),
        "-P", str(plex_port),
        "-r",
        str(local_dir),
        f"{plex_user}@{plex_host}:{plex_dir}/",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [!] Upload failed: {result.stderr}")
        return False

    print(f"  [OK] Uploaded to {plex_host}:{plex_dir}/{local_dir.name}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Download Spotify playlist tracks from a JSON file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("json_file", help="JSON file with track list")
    parser.add_argument("--output", "-o", help="Output directory (default: auto)")
    parser.add_argument("--format", "-f", default="mp3", choices=["mp3", "flac", "m4a", "opus"],
                        help="Audio format (default: mp3)")
    parser.add_argument("--bitrate", default="320K", help="Audio bitrate (default: 320K)")
    parser.add_argument("--proxy", help="Proxy URL (e.g. socks5://host:port)")
    parser.add_argument("--cookies-from-browser", choices=["chrome", "edge", "firefox", "opera", "brave"],
                        help="Extract cookies from browser for yt-dlp")
    parser.add_argument("--upload-plex", action="store_true",
                        help="Upload to Plex server after download")
    parser.add_argument("--plex-host", default="112.112.10.34", help="Plex server host")
    parser.add_argument("--plex-port", type=int, default=4422, help="Plex server SSH port")
    parser.add_argument("--plex-dir", default="/home/media/music/Thintsing精选2",
                        help="Plex target directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be downloaded without downloading")
    parser.add_argument("--concurrent", "-j", type=int, default=4,
                        help="Number of parallel downloads (default: 4)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        set_debug(True)

    # Auto-detect proxy if not specified
    proxy = args.proxy
    if not proxy:
        detected = detect_proxy()
        if detected:
            print(f"[PROXY] Auto-detected: {detected}")
            proxy = detected

    # Load track list
    print(f"[LOAD] Reading {args.json_file}...")
    playlist_name, tracks = load_tracks_json(args.json_file)
    if not tracks:
        print("ERROR: Failed to load track list")
        sys.exit(1)

    print(f"  Playlist: {playlist_name}")
    print(f"  Tracks: {len(tracks)}")
    print()

    # Determine output directory
    if args.output:
        output_dir = Path(args.output)
    else:
        # Sanitize playlist name for filesystem
        safe_name = sanitize_filename(playlist_name)
        output_dir = Path(DEFAULT_OUTPUT) / safe_name

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[OUTPUT] {output_dir}")
    print()

    if args.dry_run:
        print("[DRY RUN] Would download:")
        for i, track in enumerate(tracks, 1):
            print(f"  {i:2d}. {track['artist']} - {track['title']}")
        print(f"\nTotal: {len(tracks)} tracks")
        sys.exit(0)

    # Download tracks (concurrently if --concurrent > 1)
    python_exe, _, ffmpeg_exe = ensure_deps()
    success_count = 0
    
    def download_single_track(track_idx, track_data):
        """Download and tag a single track. Returns (track_idx, success, filepath, tagged)."""
        artist = track_data["artist"]
        title = track_data["title"]
        
        filepath = download_track(
            artist, title, output_dir,
            fmt=args.format, bitrate=args.bitrate,
            proxy=proxy,
            cookies_from_browser=args.cookies_from_browser,
            python_exe=python_exe,
            ffmpeg_exe=ffmpeg_exe,
        )
        
        if filepath:
            tagged = write_id3_tags(filepath, artist, title, playlist_name, track_idx)
            return (track_idx, True, filepath, tagged)
        else:
            return (track_idx, False, None, False)
    
    if args.concurrent > 1:
        # Parallel downloads
        print(f"[DOWNLOAD] Starting {args.concurrent} parallel downloads...")
        print()
        
        with ThreadPoolExecutor(max_workers=args.concurrent) as executor:
            future_to_idx = {
                executor.submit(download_single_track, i, track): i
                for i, track in enumerate(tracks, 1)
            }
            
            for future in as_completed(future_to_idx):
                track_idx, success, filepath, tagged = future.result()
                track = tracks[track_idx - 1]
                artist = track["artist"]
                title = track["title"]
                
                if success:
                    if tagged:
                        print(f"[{track_idx}/{len(tracks)}] [OK] {artist} - {title}")
                        print(f"         Tagged: {filepath.name}")
                    else:
                        print(f"[{track_idx}/{len(tracks)}] [OK] {artist} - {title}")
                        print(f"         (tagging failed): {filepath.name}")
                    success_count += 1
                else:
                    print(f"[{track_idx}/{len(tracks)}] [FAIL] {artist} - {title}")
                print()
    else:
        # Sequential downloads
        for i, track in enumerate(tracks, 1):
            artist = track["artist"]
            title = track["title"]
    
            print(f"[{i}/{len(tracks)}] {artist} - {title}")
    
            track_idx, success, filepath, tagged = download_single_track(i, track)
    
            if success:
                if tagged:
                    print(f"  [OK] Downloaded and tagged: {filepath.name}")
                else:
                    print(f"  [OK] Downloaded (tagging failed): {filepath.name}")
                success_count += 1
            else:
                print("  [FAIL] Download failed")
    
            print()

    print("=" * 60)
    print(f"[DONE] {success_count}/{len(tracks)} tracks downloaded to {output_dir}")

    # Upload to Plex if requested
    if args.upload_plex and success_count > 0:
        upload_to_plex(
            output_dir,
            plex_host=args.plex_host,
            plex_port=args.plex_port,
            plex_dir=args.plex_dir,
        )


if __name__ == "__main__":
    main()

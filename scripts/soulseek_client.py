"""
Soulseek search and download client for MelodyMine.

Requires: aioslsk>=1.6
Credentials: read from SLSK_USERNAME / SLSK_PASSWORD env vars by default,
             or passed explicitly as function arguments.

Usage:
    import soulseek_client
    results = soulseek_client.search("Air Supply flac")
    soulseek_client.download("username", "file_path", "output_dir")
"""

import asyncio
import os
import sys
import time

from aioslsk.client import SoulSeekClient
from aioslsk.settings import Settings, CredentialsSettings, NetworkSettings


def _get_creds(username=None, password=None):
    username = username or os.environ.get("SLSK_USERNAME") or ""
    password = password or os.environ.get("SLSK_PASSWORD") or ""
    if not username or not password:
        print("  [!] Soulseek credentials not set. Set SLSK_USERNAME and SLSK_PASSWORD env vars.")
        return None, None
    return username, password


async def _async_search(query, username, password, wait=15):
    """Async Soulseek search. Returns list of (username, FileData) tuples."""
    settings = Settings(
        credentials=CredentialsSettings(username=username, password=password),
        network=NetworkSettings(enable_upnp=False, listen_port=0),
    )
    client = SoulSeekClient(settings)
    await client.start()
    await client.login()

    req = await client.searches.search(query)

    # Wait for results
    for i in range(wait):
        await asyncio.sleep(1)
        if len(req.results) > 0 and len(req.results) % 20 == 0:
            pass  # silently accumulating

    results = list(req.results)
    await client.stop()
    return results


def search(query, username=None, password=None, wait=15, max_results=50):
    """
    Search Soulseek network for audio files.

    Returns list of dicts::
        [
            {
                "username": "musiclover",
                "filename": "Air Supply - Making Love Out of Nothing at All.flac",
                "filesize": 60000000,
                "extension": "flac",
                "shared_items_count": 1,
            },
            ...
        ]

    The returned list is sorted by filesize descending (largest first).
    """
    username, password = _get_creds(username, password)
    if not username:
        return []

    results = asyncio.run(_async_search(query, username, password, wait))

    # Flatten: each SearchResult has multiple shared_items
    flat = []
    seen = set()
    for r in results:
        for item in r.shared_items:
            key = (r.username, item.filename)
            if key in seen:
                continue
            seen.add(key)
            flat.append({
                "username": r.username,
                "filename": item.filename,
                "filesize": item.filesize,
                "extension": item.extension,
                "shared_items_count": len(r.shared_items),
                "has_free_slots": r.has_free_slots,
                "avg_speed": r.avg_speed,
                "queue_size": r.queue_size,
            })

    # Sort by filesize descending (higher quality likely = larger)
    flat.sort(key=lambda x: -x["filesize"])

    if max_results and max_results > 0:
        flat = flat[:max_results]

    return flat


async def _async_download(username, password, target_user, remote_path, output_dir):
    """Async download a single file from a Soulseek user."""
    settings = Settings(
        credentials=CredentialsSettings(username=username, password=password),
        network=NetworkSettings(enable_upnp=False, listen_port=0),
    )
    client = SoulSeekClient(settings)
    await client.start()
    await client.login()

    # Find the filename for display
    filename = remote_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    out_path = os.path.join(output_dir, filename)

    print(f"  Downloading from {target_user}: {filename}")
    print(f"  -> {out_path}")

    try:
        # Request file transfer from user
        start = time.time()
        download = await client.transfers.transfer_file(
            target_user, remote_path, out_path
        )
        elapsed = time.time() - start
        # Wait for transfer to complete
        await download.wait_complete()
        print(f"  Downloaded {os.path.getsize(out_path) / 1024 / 1024:.1f}MB in {elapsed:.0f}s")
        success = True
    except Exception as e:
        print(f"  [!] Download failed: {e}")
        success = False

    await client.stop()
    return success, out_path if success else None


def download(target_user, remote_path, output_dir, username=None, password=None, timeout=120):
    """
    Download a file from a Soulseek user.

    Args:
        target_user: Soulseek username of the sharer
        remote_path: Full remote file path as returned by search()
        output_dir: Local directory to save the file
        username/password: Soulseek credentials (or use env vars)

    Returns:
        (True, local_filepath) on success, (False, None) on failure
    """
    username, password = _get_creds(username, password)
    if not username:
        return False, None

    os.makedirs(output_dir, exist_ok=True)

    try:
        success, path = asyncio.run(
            _async_download(username, password, target_user, remote_path, output_dir)
        )
        return success, path
    except Exception as e:
        print(f"  [!] Soulseek download error: {e}")
        return False, None


if __name__ == "__main__":
    # CLI mode for quick testing
    if len(sys.argv) < 2:
        print("Usage:")
        print("  search:  python soulseek_client.py search <query>")
        print("  env:     SLSK_USERNAME=xxx SLSK_PASSWORD=xxx")
        sys.exit(1)

    action = sys.argv[1]
    if action == "search":
        query = " ".join(sys.argv[2:])
        results = search(query)
        print(f"\nFound {len(results)} results:")
        for r in results[:30]:
            name = r["filename"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            print(f"  {r['username']:20s} | {r['filesize']/1024/1024:5.1f}MB | {name[:50]}")
    else:
        print(f"Unknown action: {action}")
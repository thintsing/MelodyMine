"""
Soulseek search and download client for MelodyMine.

Requires: aioslsk>=1.6
Credentials: read from SLSK_USERNAME / SLSK_PASSWORD env vars by default,
             or passed explicitly as function arguments.

Usage:
    import soulseek_client
    results = soulseek_client.search("Air Supply flac")
    soulseek_client.download("username", "remote_file_path", "output_dir")
"""

import asyncio
import os
import sys
import time

from aioslsk.client import SoulSeekClient
from aioslsk.settings import Settings, CredentialsSettings, NetworkSettings, SharesSettings, ListeningSettings
from aioslsk.transfer.model import Transfer as SlskTransfer
from aioslsk.transfer.state import TransferState


def _patch_open_connection(proxy_url):
    """Monkey-patch asyncio.open_connection to route through SOCKS5/HTTP proxy.

    Uses PySocks to create a proxied socket, then passes it to
    asyncio.open_connection(sock=...) so all aioslsk traffic (server
    login + peer connections) goes through the proxy.

    Returns a cleanup callable to restore the original.
    """
    if not proxy_url:
        return lambda: None

    from urllib.parse import urlparse
    parsed = urlparse(proxy_url)
    scheme = parsed.scheme.lower()
    proxy_host = parsed.hostname or "127.0.0.1"
    proxy_port = parsed.port or 7897

    import socks as _socks
    import asyncio as _asyncio

    _orig_open_connection = _asyncio.open_connection

    # Determine PySocks proxy type
    _proxy_type = None
    if scheme in ("socks5", "socks5h"):
        _proxy_type = _socks.SOCKS5
    elif scheme == "socks4":
        _proxy_type = _socks.SOCKS4
    elif scheme == "http":
        _proxy_type = _socks.HTTP
    else:
        print(f"  [!] Unknown proxy scheme: {scheme}, ignoring")
        return lambda: None

    async def _proxied_open_connection(host=None, port=None, **kwargs):
        """Create a proxied socket and pass it to asyncio.open_connection."""
        kwargs.pop("sock", None)

        # Create a SOCKS socket and connect through the proxy (can block,
        # so run in executor to avoid blocking the asyncio event loop)
        proxied_sock = _socks.socksocket()
        proxied_sock.set_proxy(_proxy_type, addr=proxy_host, port=proxy_port)
        proxied_sock.settimeout(30)
        loop = _asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: proxied_sock.connect((host, port)))
        except Exception as exc:
            proxied_sock.close()
            raise ConnectionError(f"Proxy connect to {host}:{port} failed: {exc}")

        kwargs["sock"] = proxied_sock
        return await _orig_open_connection(host=None, port=None, **kwargs)

    _asyncio.open_connection = _proxied_open_connection

    def _restore():
        _asyncio.open_connection = _orig_open_connection

    return _restore


class _ProxyScope:
    """Context manager that wraps asyncio.open_connection for SOCKS5 proxying."""
    def __init__(self, proxy_url=""):
        self._restore = None
        self._url = proxy_url

    def __enter__(self):
        if not self._url:
            return self
        self._restore = _patch_open_connection(self._url)
        print(f"  Proxy active: {self._url}")
        return self

    def __exit__(self, *args):
        if self._restore:
            self._restore()


class _NoopTransferCache:
    """Minimal TransferCache implementation (no persistence)."""
    def read(self) -> list[SlskTransfer]:
        return []
    def write(self, transfers: list[SlskTransfer]):
        pass


def _get_creds(username=None, password=None):
    username = username or os.environ.get("SLSK_USERNAME") or ""
    password = password or os.environ.get("SLSK_PASSWORD") or ""
    if not username or not password:
        print("  [!] Soulseek credentials not set. Set SLSK_USERNAME and SLSK_PASSWORD env vars.")
        return None, None
    return username, password


def _state_val(state_obj):
    """Get the VALUE enum from a TransferState object for comparisons."""
    return getattr(state_obj, 'VALUE', TransferState.UNSET)


def _safe(s):
    """Strip non-printable Unicode control chars that crash Windows GBK terminals."""
    return "".join(c for c in s if c.isprintable() or c == " ")


def _ext_guard(item):
    """Get file extension from a FileData item, falling back to filename parsing."""
    ext = getattr(item, "extension", None)
    if ext:
        return ext
    fn = getattr(item, "filename", "")
    if "." in fn:
        return fn.rsplit(".", 1)[-1].lower()
    return ""


async def _async_search(query, username, password, wait=15):
    """Async Soulseek search. Returns list of (username, FileData) tuples."""
    settings = Settings(
        credentials=CredentialsSettings(username=username, password=password),
        network=NetworkSettings(
            listening=ListeningSettings(port=0, obfuscated_port=0, error_mode='any'),
            upnp={'enable': False},
        ),
    )
    client = SoulSeekClient(settings)
    await client.start()
    await client.login()

    req = await client.searches.search(query)

    for i in range(wait):
        await asyncio.sleep(1)
        if len(req.results) > 0 and len(req.results) % 20 == 0:
            pass  # silently accumulating

    results = list(req.results)
    await client.stop()
    return results


def search(query, username=None, password=None, wait=15, max_results=50, proxy=""):
    """
    Search Soulseek network for audio files.

    Args:
        query: Search string
        username/password: Soulseek credentials (or use env vars)
        wait: Seconds to wait for results
        max_results: Max files to return
        proxy: Proxy URL (e.g. "socks5://127.0.0.1:7897")

    Returns list of dicts::
        [
            {
                "username": "musiclover",
                "filename": "Air Supply - Making Love Out of Nothing at All.flac",
                "filesize": 60000000,
                "extension": "flac",
                "shared_items_count": 1,
                "has_free_slots": True,
                "avg_speed": 100.0,
                "queue_size": 0,
            },
            ...
        ]

    The returned list is sorted by filesize descending (largest first).
    """
    username, password = _get_creds(username, password)
    if not username:
        return []

    with _ProxyScope(proxy):
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
                "extension": _ext_guard(item),
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


async def _async_download(username, password, target_user, remote_path, output_dir, timeout_secs=120):
    """Async download a single file from a Soulseek user."""
    os.makedirs(output_dir, exist_ok=True)

    settings = Settings(
        credentials=CredentialsSettings(username=username, password=password),
        network=NetworkSettings(
            listening=ListeningSettings(port=0, obfuscated_port=0, error_mode='any'),
            upnp={'enable': False},
        ),
        shares=SharesSettings(download=output_dir),
    )
    client = SoulSeekClient(settings)
    await client.start()
    await client.login()

    # Set up transfer manager
    transfer_mgr = client.create_transfer_manager(_NoopTransferCache())
    await transfer_mgr.start()

    # Find the filename for display
    filename = remote_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    print(f"  Downloading from {_safe(target_user)}: {_safe(filename)}")

    try:
        transfer = await transfer_mgr.download(target_user, remote_path)

        # Wait for completion
        start = time.time()
        success = False
        while time.time() - start < timeout_secs:
            await asyncio.sleep(1)

            if transfer.is_transfered():
                success = True
                elapsed = time.time() - start
                print(f"  Completed in {elapsed:.0f}s")
                break

            if _state_val(transfer.state) == TransferState.FAILED:
                reason = transfer.fail_reason or "unknown"
                print(f"  [!] Transfer failed: {reason}")
                break

            if _state_val(transfer.state) == TransferState.ABORTED:
                reason = transfer.abort_reason or "aborted"
                print(f"  [!] Transfer aborted: {reason}")
                break

        if not success:
            if time.time() - start >= timeout_secs:
                print(f"  [!] Timeout after {timeout_secs}s")
            return False, None

        local_path = transfer.local_path
        if local_path and os.path.isfile(local_path):
            size_mb = os.path.getsize(local_path) / (1024 * 1024)
            print(f"  Downloaded: {size_mb:.1f} MB")
            return True, local_path
        else:
            print(f"  [!] File not found at local path: {local_path}")
            return False, None

    except Exception as e:
        print(f"  [!] Download error: {e}")
        return False, None
    finally:
        await transfer_mgr.stop()
        await client.stop()


def download(target_user, remote_path, output_dir, username=None, password=None, timeout=120, proxy=""):
    """
    Download a file from a Soulseek user.

    Args:
        target_user: Soulseek username of the sharer
        remote_path: Full remote file path as returned by search()
        output_dir: Local directory to save the file
        username/password: Soulseek credentials (or use env vars)
        proxy: Proxy URL (e.g. "socks5://127.0.0.1:7897")

    Returns:
        (True, local_filepath) on success, (False, None) on failure
    """
    username, password = _get_creds(username, password)
    if not username:
        return False, None

    os.makedirs(output_dir, exist_ok=True)

    try:
        with _ProxyScope(proxy):
            success, path = asyncio.run(
                _async_download(username, password, target_user, remote_path, output_dir, timeout)
            )
        return success, path
    except Exception as e:
        print(f"  [!] Soulseek download error: {e}")
        return False, None


def download_best(candidates, output_dir, username=None, password=None, max_retries=3, proxy=""):
    """
    Try multiple Soulseek candidates in order until one succeeds.

    ``candidates`` is a list of dicts with keys ``username`` and ``filename``,
    as returned by ``search()``.  Each candidate is tried in sequence;
    exponential backoff (1s, 2s, 4s) is applied between retries of the same
    candidate.  Returns ``(True, local_path)`` on success or
    ``(False, None)`` if all candidates fail.

    Timeout scales by file size:
      - < 20 MB: 120s
      - 20-50 MB: 240s
      - > 50 MB: 360s
    """
    import time as _time
    username, password = _get_creds(username, password)
    if not username:
        return False, None

    os.makedirs(output_dir, exist_ok=True)

    for idx, cand in enumerate(candidates):
        target_user = cand["username"]
        remote_path = cand["filename"]
        filesize = cand.get("filesize", 0)
        name = remote_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

        # Scale timeout by file size
        if filesize > 50 * 1024 * 1024:
            to = 360
        elif filesize > 20 * 1024 * 1024:
            to = 240
        else:
            to = 120

        for attempt in range(max_retries):
            print(f"  [{idx + 1}/{len(candidates)}] Trying {_safe(target_user)}: {_safe(name)} "
                  f"(attempt {attempt + 1}/{max_retries})")
            ok, path = download(
                target_user, remote_path, output_dir,
                username=username, password=password, timeout=to,
                proxy=proxy)
            if ok and path:
                return True, path
            if attempt < max_retries - 1:
                wait = 1 + attempt * 2  # 1s, 3s, 5s
                print(f"    [-] Failed, retrying in {wait}s...")
                _time.sleep(wait)

    print(f"  [!] All {len(candidates)} candidates exhausted.")
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
            print(f"  {_safe(r['username']):20s} | {r['filesize']/1024/1024:5.1f}MB | {_safe(name[:50])}")
    else:
        print(f"Unknown action: {action}")
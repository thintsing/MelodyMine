"""
Soulseek search + download client for MelodyMine.

Key features:
  • Persistent session — client stays logged in across searches/downloads
  • Proxy support for all connections (server + peer) via SOCKS5/HTTP
  • Auto-reconnect with keepalive tuning
  • Multi-candidate retry with FLAC→MP3 fallback

Credentials: SLSK_USERNAME / SLSK_PASSWORD env vars.
Proxy:      Auto-detected from environment or Clash default port.
"""

import asyncio
import os
import sys
import time

# Proxy auto-detection is now unified in melodymine_common.
from melodymine_common import detect_proxy as _detect_proxy, debug_log


def _build_proxied_socket(dest_host, dest_port, proxy_url, timeout=30):
    """Create a proxied socket (SOCKS5 or HTTP CONNECT) connected to destination."""
    from urllib.parse import urlparse
    parsed = urlparse(proxy_url)
    scheme = parsed.scheme.lower()
    proxy_host = parsed.hostname or "127.0.0.1"
    proxy_port = parsed.port or 7897

    if scheme in ("socks5", "socks5h"):
        import socks as _socks
        s = _socks.socksocket()
        pt = _socks.SOCKS5
        if scheme == "socks5h":
            s.set_proxy(pt, addr=proxy_host, port=proxy_port, rdns=True)
        else:
            s.set_proxy(pt, addr=proxy_host, port=proxy_port, rdns=False)
        s.settimeout(timeout)
        s.connect((dest_host, dest_port))
        return s

    elif scheme == "http":
        # HTTP CONNECT tunnel
        import socket as _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((proxy_host, proxy_port))
        req = (
            f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\n"
            f"Host: {dest_host}:{dest_port}\r\n"
            f"User-Agent: MelodyMine/1.0\r\n\r\n"
        )
        s.sendall(req.encode("ascii", errors="replace"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(4096)
            if not chunk:
                raise ConnectionError("HTTP CONNECT failed: connection closed")
            resp += chunk
        status_line = resp.split(b"\r\n")[0].decode("ascii", errors="replace")
        if "200" not in status_line:
            raise ConnectionError(f"HTTP CONNECT failed: {status_line.strip()}")
        s.settimeout(None)
        return s

    else:
        raise ValueError(f"Unsupported proxy scheme: {scheme}")


# ── Credentials ────────────────────────────────────────────────────

def _get_creds(username=None, password=None):
    u = username or os.environ.get("SLSK_USERNAME") or ""
    p = password or os.environ.get("SLSK_PASSWORD") or ""
    if not u or not p:
        print("  [!] Soulseek credentials not set. Set SLSK_USERNAME and SLSK_PASSWORD env vars.")
        return None, None
    return u, p


def _safe(s):
    return "".join(c for c in (s or "") if c.isprintable() or c == " ")


def _ext_guard(item):
    ext = getattr(item, "extension", None)
    if ext:
        return ext
    fn = getattr(item, "filename", "")
    if "." in fn:
        return fn.rsplit(".", 1)[-1].lower()
    return ""


# ── Persistent session manager ────────────────────────────────────

class _SoulseekSession:
    """A persistent aioslsk session that stays connected across calls.

    Usage:
        session = _SoulseekSession("user", "pass", proxy_url)
        async with session:
            results = await session.search("query")
            ok = await session.download("user", "path", "outdir")
    """

    def __init__(self, username, password, proxy=""):
        self._username = username
        self._password = password
        self._proxy = proxy
        self.client = None
        self._restore_open_conn = None

    async def __aenter__(self):
        from aioslsk.client import SoulSeekClient
        from aioslsk.settings import (Settings, CredentialsSettings, NetworkSettings,
                                       SharesSettings, ServerSettings,
                                       ReconnectSettings, ListeningSettings,
                                       ListeningConnectionErrorMode,
                                       UpnpSettings)

        settings = Settings(
            credentials=CredentialsSettings(username=self._username, password=self._password),
            network=NetworkSettings(
                server=ServerSettings(
                    reconnect=ReconnectSettings(auto=True, timeout=10),
                ),
                listening=ListeningSettings(
                    port=0,  # OS-assigned port avoids conflicts between sessions
                    obfuscated_port=0,
                    error_mode=ListeningConnectionErrorMode.ALL,
                ),
                upnp=UpnpSettings(enabled=True, check_interval=30, search_timeout=5),
            ),
            shares=SharesSettings(download=''),
        )
        self.client = SoulSeekClient(settings)

        # ── Monkey-patch: tolerate listening port failure ──
        from aioslsk.exceptions import ListeningConnectionFailedError
        from aioslsk.network.connection import ConnectionState, CloseReason
        from aioslsk.exceptions import ConnectionFailedError as ConnFailed

        async def _patched_init():
            """Run original init, but don't crash on listening port failure."""
            from aioslsk.network import upnp as _upnp
            self.client.network._upnp = _upnp.UPNP()
            try:
                await self.client.network.connect_listening_ports()
            except ListeningConnectionFailedError:
                pass
            await self.client.network.connect_server()
        self.client.network.initialize = _patched_init

        # ── Monkey-patch 2: proxy ALL connections (like SoulseekQt) ──
        if self._proxy:
            print(f"  Proxy active: {self._proxy}")
            import asyncio as _asyncio

            # 2a: Server connection via proxy
            _orig_server_conn = type(self.client.network).connect_server
            async def _proxied_connect_server():
                """Connect to Soulseek server via SOCKS5 proxy."""
                conn = self.client.network.server_connection
                await conn.set_state(ConnectionState.CONNECTING)
                try:
                    sock = _build_proxied_socket(
                        conn.hostname, conn.port,
                        self._proxy, timeout=30)
                    reader, writer = await _asyncio.open_connection(sock=sock)
                    conn._reader = reader
                    conn._writer = writer
                    await conn.set_state(ConnectionState.CONNECTED)
                except (Exception, _asyncio.TimeoutError) as exc:
                    await conn.disconnect(CloseReason.CONNECT_FAILED)
                    raise ConnFailed(f"{conn.hostname}:{conn.port} : failed to connect") from exc
            self.client.network.connect_server = _proxied_connect_server

            # 2b: Proxy ALL peer connections (distributed, peer control, etc.)
            _orig_open_conn = _asyncio.open_connection
            async def _proxied_open_conn(host=None, port=None, *, sock=None, **kwargs):
                if sock is not None:
                    # Already has a proxied socket (server connection)
                    return await _orig_open_conn(sock=sock, **kwargs)
                # Proxy this peer connection
                proxy_sock = _build_proxied_socket(host, port, self._proxy, timeout=30)
                return await _orig_open_conn(sock=proxy_sock)

            def _restore():
                _asyncio.open_connection = _orig_open_conn

            _asyncio.open_connection = _proxied_open_conn
            self._restore_open_conn = _restore

        try:
            await self.client.start()
            await self.client.login()
        except Exception:
            # Ensure monkey-patches are restored even if start/login fails
            if self._restore_open_conn:
                self._restore_open_conn()
                self._restore_open_conn = None
            raise
        return self

    async def __aexit__(self, *args):
        if self._restore_open_conn:
            self._restore_open_conn()
            self._restore_open_conn = None
        if self.client:
            await self.client.stop()
            self.client = None

    async def search(self, query, wait=15, max_results=50):
        """Search Soulseek. Returns flattened results list."""
        req = await self.client.searches.search(query)
        for i in range(wait):
            await asyncio.sleep(1)

        results = list(req.results)
        flat = []
        seen = set()
        for r in results:
            for item in (r.shared_items or []):
                key = (r.username, item.filename)
                if key in seen:
                    continue
                seen.add(key)
                flat.append({
                    "username": r.username,
                    "filename": item.filename,
                    "filesize": item.filesize,
                    "extension": _ext_guard(item),
                    "shared_items_count": len(r.shared_items or []),
                    "has_free_slots": r.has_free_slots,
                    "avg_speed": r.avg_speed,
                    "queue_size": r.queue_size,
                })

        flat.sort(key=lambda x: -x["filesize"])
        if max_results > 0:
            flat = flat[:max_results]
        return flat

    async def download(self, target_user, remote_path, output_dir, timeout=0):
        """Download a file using client's built-in transfer manager.

        Args:
            timeout: Max seconds to wait. 0 = wait indefinitely (default).
                     If filesize is known from search, timeout is auto-calculated.
        """
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        filename = remote_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        print(f"  Downloading from {_safe(target_user)}: {_safe(filename)}")

        if self.client.settings.shares.download != output_dir:
            self.client.settings.shares.download = output_dir

        from aioslsk.transfer.state import TransferState

        try:
            transfer = await self.client.transfers.download(target_user, remote_path)
            print(f"  Transfer created: {transfer}", flush=True)

            start = time.time()
            last_size = 0
            stall_time = 0
            # If no explicit timeout, allow 30 min
            actual_timeout = timeout if timeout > 0 else 1800

            while time.time() - start < actual_timeout:
                await asyncio.sleep(2)

                st = getattr(transfer.state, "VALUE", TransferState.UNSET)

                if st == TransferState.COMPLETE or transfer.is_transfered():
                    print(f"  Completed in {time.time() - start:.0f}s", flush=True)
                    break

                if st == TransferState.FAILED:
                    reason = transfer.fail_reason or "unknown"
                    print(f"  [!] Transfer failed: {reason}", flush=True)
                    return False, None

                if st == TransferState.ABORTED:
                    reason = transfer.abort_reason or "aborted"
                    print(f"  [!] Transfer aborted: {reason}", flush=True)
                    return False, None

                # Check if file is growing (stall detection)
                lp = transfer.local_path
                if lp and os.path.isfile(lp):
                    cur_size = os.path.getsize(lp)
                    if cur_size == last_size:
                        stall_time += 2
                        if stall_time > 60:  # stalled for 60s
                            print(f"  [!] Transfer stalled ({cur_size/1024/1024:.1f}MB), aborting", flush=True)
                            return False, None
                    else:
                        stall_time = 0
                        last_size = cur_size

                    elapsed = time.time() - start
                    if int(elapsed) % 15 == 0:
                        speed = cur_size / 1024 / 1024 / elapsed if elapsed > 0 else 0
                        print(f"  {cur_size/1024/1024:.1f}MB / ? ({speed:.1f} MB/s, {elapsed:.0f}s)", flush=True)

            if time.time() - start >= actual_timeout:
                print(f"  [!] Timeout after {actual_timeout}s, state={getattr(transfer.state, 'VALUE', '?').name}", flush=True)
                return False, None

            lp = transfer.local_path
            if lp and os.path.isfile(lp):
                sz = os.path.getsize(lp) / (1024 * 1024)
                print(f"  Saved: {sz:.1f} MB -> {lp}", flush=True)
                return True, lp

            print(f"  [!] File not found at {lp}", flush=True)
            return False, None

        except Exception as e:
            print(f"  [!] Download error: {e}", flush=True)
            import traceback
            debug_log(f"soulseek download error: {e}\n{traceback.format_exc()}")
            return False, None


# ── Multi-query strategy ─────────────────────────────────────

# Words that often don't help Soulseek searches (articles, filler)
_STOP_WORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
               "and", "or", "is", "it", "feat", "ft", "featuring", "vs",
               "remix", "edit", "version", "official", "audio", "video",
               "music", "lyric", "lyrics", "hq", "hd", "4k", "1080p"}

def _generate_queries(query):
    """Generate alternative search queries when the original returns nothing.

    Strategy (proven effective from real tests):
    - For Chinese queries: try pinyin, artist-only, title-only
    - For English queries: try reversed order, title-only, artist-only
    - Always try with 'flac' and 'mp3' suffix
    """
    q = query.strip()
    queries = [q]

    # Detect if contains Chinese characters
    has_cjk = any('\u4e00' <= c <= '\u9fff' for c in q)

    words = q.split()

    if has_cjk:
        # Chinese song: also try English/pinyin queries
        # Split by spaces or just keep original
        queries.append(q + " flac")
        queries.append(q + " mp3")
        # Try removing stop words
        filtered = [w for w in words if w.lower() not in _STOP_WORDS]
        if filtered and filtered != words:
            queries.append(" ".join(filtered))
    else:
        # English/international song
        # Try reversed order for multi-word queries
        if len(words) > 1:
            queries.append(" ".join(reversed(words)))
            queries[-1] = queries[-1].lower()

        # Add format hints
        queries.append(q + " flac")
        queries.append(q + " mp3")

        # Try individual words (artist or title alone)
        for w in words:
            if w.lower() not in _STOP_WORDS and len(w) > 2:
                queries.append(w)

    # Remove duplicates while preserving order
    seen = set()
    deduped = []
    for qq in queries:
        key = qq.strip().lower()
        if key not in seen:
            seen.add(key)
            deduped.append(qq.strip())

    return deduped


# ── Public API (compatible with old soulseek_client) ───────────────

def search(query, username=None, password=None, wait=15, max_results=50, proxy="",
           auto_multi=True):
    """Search Soulseek.  Auto-detects Clash proxy if proxy not specified.

    If ``auto_multi`` is True (default) and initial query returns 0 results,
    the search automatically tries alternative queries via ``_generate_queries()``.
    """
    u, p = _get_creds(username, password)
    if not u:
        return []

    actual_proxy = proxy or _detect_proxy()

    async def _run(q):
        async with _SoulseekSession(u, p, actual_proxy) as sess:
            return await sess.search(q, wait, max_results)

    # First pass: original query
    results = asyncio.run(_run(query))

    if results or not auto_multi:
        return results

    # Multi-query fallback: try alternative queries
    alt_queries = _generate_queries(query)
    tried = []
    for alt_q in alt_queries:
        if alt_q.lower() == query.strip().lower():
            continue
        tried.append(alt_q)
        print(f"  [+] Original query returned 0. Trying: {alt_q[:60]}")
        results = asyncio.run(_run(alt_q))
        if results:
            print(f"  [+] Found {len(results)} results with alternative query!")
            return results

    return []


def download(target_user, remote_path, output_dir, username=None, password=None, timeout=120, proxy=""):
    u, p = _get_creds(username, password)
    if not u:
        return False, None

    actual_proxy = proxy or _detect_proxy()
    if not actual_proxy:
        print(f"  No proxy configured (VPS is outside China, direct connection).")

    async def _run():
        async with _SoulseekSession(u, p, actual_proxy) as sess:
            return await sess.download(target_user, remote_path, output_dir, timeout)

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"  [!] Soulseek download error: {e}")
        return False, None


def search_and_download(query, output_dir, username=None, password=None, wait=15, timeout=120, proxy=""):
    """Search then immediately download the first working result in ONE session.

    Supports multi-query fallback: if initial query returns 0 results,
    tries alternative queries automatically.
    """
    u, p = _get_creds(username, password)
    if not u:
        return False, None

    actual_proxy = proxy or _detect_proxy()

    os.makedirs(output_dir, exist_ok=True)

    async def _run(q):
        async with _SoulseekSession(u, p, actual_proxy) as sess:
            results = await sess.search(q, wait)
            print(f"  Search for '{q[:60]}' - {len(results)} results")

            candidates = [r for r in results if r.get("extension") in ("flac", "mp3", "wav", "alac", "ape", "wv")]
            candidates.sort(key=lambda x: (0 if x["extension"] == "flac" else 1, x["filesize"]))

            if not candidates:
                return None

            for r in candidates[:5]:
                name = r["filename"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
                print(f"  Trying: {_safe(r['username'])} | {name[:50]}")
                ok, path = await sess.download(r["username"], r["filename"], output_dir, timeout)
                if ok:
                    return (True, path)
            return (False, None)

    # Try original query first
    try:
        result = asyncio.run(_run(query))
        if result is None:
            # Multi-query fallback
            alt_queries = _generate_queries(query)
            for alt_q in alt_queries:
                if alt_q.lower() == query.strip().lower():
                    continue
                print(f"  [+] Original query empty. Trying: {alt_q[:60]}")
                result = asyncio.run(_run(alt_q))
                if result:
                    return result
                if result is not None:
                    return result
            return False, None
        return result
    except Exception as e:
        print(f"  [!] search_and_download error: {e}")
        return False, None


def download_best(candidates, output_dir, username=None, password=None, max_retries=3, proxy=""):
    u, p = _get_creds(username, password)
    if not u:
        return False, None

    actual_proxy = proxy or _detect_proxy()
    if not actual_proxy:
        print(f"  No proxy configured (VPS is outside China, direct connection).")

    os.makedirs(output_dir, exist_ok=True)

    for idx, cand in enumerate(candidates):
        tu = cand["username"]
        rp = cand["filename"]
        fs = cand.get("filesize", 0)

        to = 360 if fs > 50 * 1024 * 1024 else (240 if fs > 20 * 1024 * 1024 else 120)

        for attempt in range(max_retries):
            name = rp.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            print(f"  [{idx + 1}/{len(candidates)}] Trying {_safe(tu)}: {_safe(name)} "
                  f"(attempt {attempt + 1}/{max_retries})")
            ok, path = download(tu, rp, output_dir, u, p, to, actual_proxy)
            if ok and path:
                return True, path
            if attempt < max_retries - 1:
                w = 1 + attempt * 2
                print(f"    [-] Failed, retrying in {w}s...")
                time.sleep(w)

    print(f"  [!] All {len(candidates)} candidates exhausted.")
    return False, None


# ── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  search:  python soulseek_client.py search <query>")
        print("  env:     SLSK_USERNAME=xxx SLSK_PASSWORD=xxx")
        sys.exit(1)

    action = sys.argv[1]
    if action == "search":
        query = " ".join(sys.argv[2:])
        proxy = _detect_proxy()
        results = search(query, proxy=proxy)
        print(f"\nFound {len(results)} results:")
        for r in results[:30]:
            name = r["filename"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            print(f"  {_safe(r['username']):20s} | {r['filesize']/1024/1024:5.1f}MB | {_safe(name[:50])}")
    else:
        print(f"Unknown action: {action}")
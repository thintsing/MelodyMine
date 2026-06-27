"""
Soulseek search + download client for MelodyMine — v2.

Key improvements over v1 (soulseek_client.py):
  • Persistent session — client stays logged in across searches/downloads
  • Proxy support ONLY for server connection (peer connections go direct)
  • Auto-reconnect with keepalive tuning
  • Detailed connection diagnostics

Credentials: SLSK_USERNAME / SLSK_PASSWORD env vars.
Proxy:      Clash default (socks5://127.0.0.1:7897) or auto-detect.
"""

import asyncio
import os
import sys
import time
import json
from urllib.parse import urlparse

# ── Proxy helpers ──────────────────────────────────────────────────

_SOCKS5_DEFAULT = "socks5://127.0.0.1:7897"


def _detect_proxy():
    """Auto-detect running proxy.  Returns URL string or empty string."""
    # Read Clash mixed-port from config
    cfg = os.path.expanduser(
        "~/AppData/Roaming/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml"
    )
    port = 7897
    if os.path.isfile(cfg):
        import yaml
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data:
                port = data.get("mixed-port", port)
        except Exception:
            pass
    # Check if Clash is actually listening
    import socket as _sock
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", port))
        s.close()
        return f"socks5://127.0.0.1:{port}"
    except Exception:
        return ""


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

    async def __aenter__(self):
        from aioslsk.client import SoulSeekClient
        from aioslsk.settings import (Settings, CredentialsSettings, NetworkSettings,
                                       SharesSettings, ServerSettings,
                                       ReconnectSettings, ListeningSettings,
                                       ListeningConnectionErrorMode)

        settings = Settings(
            credentials=CredentialsSettings(username=self._username, password=self._password),
            network=NetworkSettings(
                server=ServerSettings(
                    reconnect=ReconnectSettings(auto=True, timeout=10),
                ),
                listening=ListeningSettings(
                    port=60001,
                    obfuscated_port=0,
                    error_mode=ListeningConnectionErrorMode.ALL,
                ),
                upnp={'enable': False},
            ),
            shares=SharesSettings(download=''),
        )
        self.client = SoulSeekClient(settings)

        # ── Monkey-patch 1: tolerate listening port failure ──
        from aioslsk.exceptions import ListeningConnectionFailedError
        from aioslsk.network.connection import ConnectionState, CloseReason
        from aioslsk.exceptions import ConnectionFailedError as ConnFailed

        _orig_net_init = type(self.client.network).initialize
        async def _patched_init():
            try:
                await self.client.network.connect_listening_ports()
            except ListeningConnectionFailedError:
                pass
            await self.client.network.connect_server()
        self.client.network.initialize = _patched_init

        # ── Monkey-patch 2: proxy only the server connection ─
        if self._proxy:
            print(f"  Proxy active: {self._proxy}")
            _orig_server_conn = type(self.client.network).connect_server

            async def _proxied_connect_server():
                """Connect to Soulseek server via SOCKS5 proxy."""
                import asyncio as _asyncio
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

        await self.client.start()
        await self.client.login()
        return self

    async def __aexit__(self, *args):
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
            traceback.print_exc()
            return False, None


# ── Public API (compatible with old soulseek_client) ───────────────

def search(query, username=None, password=None, wait=15, max_results=50, proxy=""):
    """Search Soulseek.  Auto-detects Clash proxy if proxy not specified."""
    u, p = _get_creds(username, password)
    if not u:
        return []

    actual_proxy = proxy or _detect_proxy()
    if not actual_proxy:
        actual_proxy = _SOCKS5_DEFAULT
        print(f"  Using default proxy: {actual_proxy}")

    async def _run():
        async with _SoulseekSession(u, p, actual_proxy) as sess:
            return await sess.search(query, wait, max_results)

    return asyncio.run(_run())


def download(target_user, remote_path, output_dir, username=None, password=None, timeout=120, proxy=""):
    u, p = _get_creds(username, password)
    if not u:
        return False, None

    actual_proxy = proxy or _detect_proxy()
    if not actual_proxy:
        actual_proxy = _SOCKS5_DEFAULT

    async def _run():
        async with _SoulseekSession(u, p, actual_proxy) as sess:
            return await sess.download(target_user, remote_path, output_dir, timeout)

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"  [!] Soulseek download error: {e}")
        return False, None


def search_and_download(query, output_dir, username=None, password=None, wait=15, timeout=120, proxy=""):
    """Search then immediately download the first working result in ONE session."""
    u, p = _get_creds(username, password)
    if not u:
        return False, None

    actual_proxy = proxy or _detect_proxy()
    if not actual_proxy:
        actual_proxy = _SOCKS5_DEFAULT

    os.makedirs(output_dir, exist_ok=True)

    async def _run():
        async with _SoulseekSession(u, p, actual_proxy) as sess:
            # Search
            results = await sess.search(query, wait)
            print(f"  Search returned {len(results)} results")

            # Pick candidates: prefer FLAC over MP3, prefer smaller files
            candidates = [r for r in results if r.get("extension") in ("flac", "mp3", "wav", "alac", "ape", "wv")]
            candidates.sort(key=lambda x: (0 if x["extension"] == "flac" else 1, x["filesize"]))

            if not candidates:
                print("  [!] No audio candidates found")
                return False, None

            for r in candidates[:5]:
                name = r["filename"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
                print(f"  Trying: {_safe(r['username'])} | {name[:50]}")
                ok, path = await sess.download(r["username"], r["filename"], output_dir, timeout)
                if ok:
                    return True, path
            return False, None

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"  [!] search_and_download error: {e}")
        return False, None


def download_best(candidates, output_dir, username=None, password=None, max_retries=3, proxy=""):
    u, p = _get_creds(username, password)
    if not u:
        return False, None

    actual_proxy = proxy or _detect_proxy()
    if not actual_proxy:
        actual_proxy = _SOCKS5_DEFAULT

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
        print("  search:  python soulseek_client_v2.py search <query>")
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
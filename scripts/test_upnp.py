"""Test Soulseek with UPnP enabled — check port mapping."""
import sys, os, logging
sys.path.insert(0, r'C:\Users\Thintsing\AppData\Roaming\JoyClaw\workspace\agents\daily-office\skills\melodymine\scripts')

# Enable UPnP logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('aioslsk.network.network').setLevel(logging.DEBUG)
logging.getLogger('aioslsk.network.upnp').setLevel(logging.DEBUG)

import soulseek_client_v2 as slsk
import time, asyncio

u = os.environ.get('SLSK_USERNAME', 'thintsing1')
p = os.environ.get('SLSK_PASSWORD', 'qing9999')
proxy = slsk._detect_proxy()

print(f"User: {u}", flush=True)
print(f"Proxy: {proxy or 'direct'}", flush=True)
print(f"UPnP: enabled (default)", flush=True)

async def test():
    async with slsk._SoulseekSession(u, p, proxy) as sess:
        # Check listening ports
        ports = sess.client.network.get_listening_ports()
        print(f"\nListening ports: {ports}", flush=True)
        
        # Check UPnP status
        upnp = getattr(sess.client.network, '_upnp', None)
        print(f"UPnP instance: {upnp}", flush=True)
        
        # Search
        t0 = time.time()
        print(f"\nSearching...", flush=True)
        results = await sess.search("Dire Straits Sultans of Swing", wait=15)
        print(f"Got {len(results)} results in {time.time()-t0:.0f}s", flush=True)
        
        # Show a candidate
        for r in results[:3]:
            name = r["filename"].rsplit("\\",1)[-1].rsplit("/",1)[-1]
            sz = r["filesize"]/1024/1024
            print(f"  {r['username'][:18]} | {sz:.0f}MB | {name[:50]}", flush=True)
        
        # Try download a small mp3
        candidates = [r for r in results 
                      if r.get("extension")=="mp3" 
                      and r.get("has_free_slots")
                      and r["filesize"] < 20*1024*1024]
        if candidates:
            c = candidates[0]
            print(f"\nDownloading from {c['username']}: {c['filename'][:60]}", flush=True)
            ok, path = await sess.download(c["username"], c["filename"], r"C:\Users\Thintsing\Downloads\soulseek_test", timeout=300)
            print(f"Result: ok={ok} path={path}", flush=True)

asyncio.run(test())
print("DONE", flush=True)
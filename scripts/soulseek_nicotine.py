"""
Soulseek search + download using Nicotine+ headless (one-shot subprocess).

Each search/download launches a fresh Nicotine+ instance, does its work,
and exits.  Simpler and more reliable than persistent daemon.

Credentials: SLSK_USERNAME / SLSK_PASSWORD env vars.
"""

import json
import os
import subprocess
import sys
import time


_ONE_SHOT_SCRIPT = r"""
import json, os, sys, time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pynicotine.config as cfg
cfg.data_folder_path = os.path.join(os.path.expanduser("~"), ".melodymine", "nicotine")
cfg.config_file_path = os.path.join(cfg.data_folder_path, "config")
cfg.load_config()

import pynicotine.events as _evt
from pynicotine import core
from pynicotine.transfers import Transfer, TransferStatus

skip = {"signal_handler"}
all_comps = {
    "error_handler", "portmapper", "network_thread", "shares", "users",
    "notifications", "network_filter", "now_playing", "statistics",
    "search", "downloads", "uploads", "interests", "userbrowse",
    "userinfo", "buddies", "chatrooms", "privatechat", "pluginhandler",
}
core.init_components(enabled_components=all_comps - skip)
core.start()
core.connect()

for _ in range(300):
    _evt.events.process_thread_events()
    if core.users and core.users.login_status == 1:
        break
    time.sleep(0.1)
else:
    print("LOGIN_TIMEOUT")
    core.quit()
    quit(1)

action = json.loads(sys.argv[1])

if action.get("action") == "search":
    text = action["query"]
    wait = action.get("wait", 15)
    max_results = action.get("max_results", 50)

    core.search.do_global_search(text)
    si = core.search.add_search(text, mode="global")
    token = si.token

    deadline = time.time() + wait
    while time.time() < deadline:
        _evt.events.process_thread_events()
        time.sleep(0.05)

    results = []
    seen = set()
    if token in core.search.searches:
        sr = core.search.searches[token]
        for user, files in sr.results.items():
            for item in files:
                fn = getattr(item, "filename", "") or ""
                sz = getattr(item, "filesize", 0) or 0
                ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                key = (user, fn)
                if key not in seen:
                    seen.add(key)
                    results.append({"username": user, "filename": fn, "filesize": sz, "extension": ext})

    results.sort(key=lambda r: -r["filesize"])
    print("SEARCH_RESULTS")
    json.dump(results[:max_results], sys.stdout)

elif action.get("action") == "download":
    user = action["username"]
    path = action["filename"]
    timeout = action.get("timeout", 120)

    t = Transfer(username=user, virtual_path=path)
    core.downloads._enqueue_transfer(t)

    deadline = time.time() + timeout
    done_path = None
    while time.time() < deadline:
        _evt.events.process_thread_events()
        for tr in list(core.downloads.transfers.values()):
            if tr.username == user and tr.virtual_path == path:
                if tr.status == TransferStatus.FINISHED:
                    local = core.downloads.get_complete_download_file_path(user, path, tr.size)
                    if local and os.path.isfile(local):
                        done_path = local
                    break
                elif tr.status in (TransferStatus.ABORTED, TransferStatus.FILTERED):
                    break
        if done_path:
            break
        time.sleep(0.5)
    else:
        print("DL_TIMEOUT")
        core.quit()
        quit(1)

    if done_path:
        print("DL_DONE")
        json.dump({"path": done_path}, sys.stdout)
    else:
        print("DL_FAIL")

core.quit()
"""


# ── Public API ─────────────────────────────────────────────────────

def _safe(s):
    return "".join(c for c in (s or "") if c.isprintable() or c == " ")


def _run_oneshot(action_dict, timeout=180):
    """Run Nicotine+ one-shot subprocess."""
    payload = json.dumps(action_dict)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _ONE_SHOT_SCRIPT, payload],
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print("  [!] Nicotine+ subprocess timed out")
        return None

    if proc.returncode != 0 and "LOGIN_TIMEOUT" in proc.stdout:
        print("  [!] Nicotine+ login timed out")
        return None

    return proc.stdout


def search(query, username=None, password=None, wait=15, max_results=50, proxy=""):
    """Search Soulseek via Nicotine+ one-shot."""
    stdout = _run_oneshot({
        "action": "search", "query": query,
        "wait": wait, "max_results": max_results,
    }, timeout=wait + 30)
    if stdout is None:
        return []

    lines = stdout.strip().split("\n")
    for i, line in enumerate(lines):
        if line == "SEARCH_RESULTS":
            try:
                return json.loads(lines[i + 1])
            except (IndexError, json.JSONDecodeError):
                return []
    return []


def download(target_user, remote_path, output_dir, username=None, password=None, timeout=120, proxy=""):
    """Download a file via Nicotine+ one-shot."""
    name = remote_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    print("  Downloading {}: {} ({}s timeout)".format(_safe(target_user), _safe(name), timeout))

    stdout = _run_oneshot({
        "action": "download", "username": target_user,
        "filename": remote_path, "timeout": timeout,
    }, timeout=timeout + 30)

    if stdout is None:
        return False, None

    lines = stdout.strip().split("\n")
    for i, line in enumerate(lines):
        if line == "DL_DONE":
            try:
                data = json.loads(lines[i + 1])
                src = data["path"]
                dest = os.path.join(output_dir, os.path.basename(src))
                if src != dest:
                    import shutil
                    os.makedirs(output_dir, exist_ok=True)
                    shutil.move(src, dest)
                sz = os.path.getsize(dest) / (1024 * 1024)
                print("  Downloaded: {:.1f} MB -> {}".format(sz, dest))
                return True, dest
            except (IndexError, KeyError, json.JSONDecodeError):
                return False, None
        if line == "DL_FAIL":
            print("  [!] Download failed")
            return False, None
        if line == "DL_TIMEOUT":
            print("  [!] Download timed out in Nicotine+")
            return False, None

    return False, None


def download_best(candidates, output_dir, username=None, password=None, max_retries=3, proxy=""):
    """Try candidates in order."""
    for idx, cand in enumerate(candidates):
        target_user = cand["username"]
        remote_path = cand["filename"]
        filesize = cand.get("filesize", 0)

        if filesize > 50 * 1024 * 1024:
            to = 360
        elif filesize > 20 * 1024 * 1024:
            to = 240
        else:
            to = 120

        for attempt in range(max_retries):
            print("  [{}/{}] Trying {} (attempt {}/{})".format(
                idx + 1, len(candidates), _safe(target_user), attempt + 1, max_retries))
            ok, path = download(target_user, remote_path, output_dir, timeout=to)
            if ok and path:
                return True, path
            if attempt < max_retries - 1:
                w = 1 + attempt * 2
                print("    [-] Failed, retry in {}s...".format(w))
                time.sleep(w)

    print("  [!] All {} candidates exhausted.".format(len(candidates)))
    return False, None


# ── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    if action == "search":
        results = search(" ".join(sys.argv[2:]))
        print("\nFound {} results:".format(len(results)))
        for r in results[:30]:
            name = r.get("filename", "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            sz = r.get("filesize", 0) / 1024 / 1024
            print("  {:20s} | {:5.1f}MB | {}".format(
                _safe(r.get("username", "?")), sz, _safe(name[:55])))
    else:
        print("Usage:\n  python soulseek_nicotine.py search <query>")
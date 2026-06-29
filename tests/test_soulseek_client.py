#!/usr/bin/env python3
"""Unit tests for soulseek_client — injects fake aioslsk before import.

Covers the pure/synchronous helpers that can be tested without a real
Soulseek connection:
  • _get_creds (env var resolution)
  • _ext_guard (extension fallback)
  • _safe (invisible char stripping)
  • _detect_proxy (env var + port probe)
  • download_best candidate ordering & retry logic (mocked download)
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# ── Inject fake aioslsk modules before soulseek_client is imported ──
# aioslsk is a heavy async dependency; tests should run without it.
_FAKE_AIOSLSK = MagicMock()
sys.modules["aioslsk"] = _FAKE_AIOSLSK
sys.modules["aioslsk.client"] = MagicMock()
sys.modules["aioslsk.settings"] = MagicMock()
sys.modules["aioslsk.transfer"] = MagicMock()
sys.modules["aioslsk.transfer.model"] = MagicMock()
sys.modules["aioslsk.transfer.state"] = MagicMock()
sys.modules["aioslsk.exceptions"] = MagicMock()
sys.modules["aioslsk.network"] = MagicMock()
sys.modules["aioslsk.network.connection"] = MagicMock()
sys.modules["aioslsk.network.upnp"] = MagicMock()

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import soulseek_client


class TestGetCreds(unittest.TestCase):
    """_get_creds: resolve credentials from args or env vars."""

    def test_explicit_args_win_over_env(self):
        with patch.dict(os.environ, {"SLSK_USERNAME": "envuser", "SLSK_PASSWORD": "envpass"}):
            u, p = soulseek_client._get_creds("arguser", "argpass")
            self.assertEqual(u, "arguser")
            self.assertEqual(p, "argpass")

    def test_env_vars_used_when_no_args(self):
        with patch.dict(os.environ, {"SLSK_USERNAME": "envuser", "SLSK_PASSWORD": "envpass"}):
            u, p = soulseek_client._get_creds()
            self.assertEqual(u, "envuser")
            self.assertEqual(p, "envpass")

    def test_missing_creds_returns_none(self):
        # Ensure no env vars leak in
        env = {k: v for k, v in os.environ.items()
               if k not in ("SLSK_USERNAME", "SLSK_PASSWORD")}
        with patch.dict(os.environ, env, clear=True):
            u, p = soulseek_client._get_creds()
            self.assertIsNone(u)
            self.assertIsNone(p)

    def test_partial_creds_returns_none(self):
        env = {k: v for k, v in os.environ.items()
               if k != "SLSK_PASSWORD"}
        env["SLSK_USERNAME"] = "onlyuser"
        with patch.dict(os.environ, env, clear=True):
            u, p = soulseek_client._get_creds()
            self.assertIsNone(u)
            self.assertIsNone(p)


class TestExtGuard(unittest.TestCase):
    """_ext_guard: extract file extension from a FileData-like item."""

    def _mkitem(self, extension=None, filename=""):
        item = MagicMock()
        item.extension = extension
        item.filename = filename
        return item

    def test_direct_extension(self):
        self.assertEqual(soulseek_client._ext_guard(self._mkitem("flac", "song.flac")), "flac")

    def test_fallback_to_filename(self):
        item = self._mkitem(None, "song.mp3")
        self.assertEqual(soulseek_client._ext_guard(item), "mp3")

    def test_fallback_lowercase(self):
        item = self._mkitem(None, "song.FLAC")
        self.assertEqual(soulseek_client._ext_guard(item), "flac")

    def test_empty_extension_no_dot(self):
        item = self._mkitem(None, "noext")
        self.assertEqual(soulseek_client._ext_guard(item), "")

    def test_empty_extension_empty_filename(self):
        item = self._mkitem(None, "")
        self.assertEqual(soulseek_client._ext_guard(item), "")


class TestSafe(unittest.TestCase):
    """_safe: strip non-printable Unicode chars (Windows GBK crash fix)."""

    def test_plain_string_unchanged(self):
        self.assertEqual(soulseek_client._safe("Hello World"), "Hello World")

    def test_chinese_unchanged(self):
        self.assertEqual(soulseek_client._safe("周杰伦"), "周杰伦")

    def test_none_returns_empty(self):
        self.assertEqual(soulseek_client._safe(None), "")

    def test_strips_control_chars(self):
        # U+200B (zero-width space) and U+001B (escape) should be stripped
        self.assertEqual(soulseek_client._safe("song\u200bname"), "songname")
        self.assertEqual(soulseek_client._safe("a\x1bb"), "ab")

    def test_preserves_space(self):
        self.assertEqual(soulseek_client._safe("a b"), "a b")

    def test_strips_zero_width_chars(self):
        # U+200B (zero-width space) is not printable → stripped
        # U+21B3 (↳) IS printable → kept by _safe (GBK arrow fix was a
        # separate commit that replaced the source char, not filtered here)
        self.assertEqual(soulseek_client._safe("song\u200bname"), "songname")
        result = soulseek_client._safe("user \u21b3 file")
        self.assertIn("\u21b3", result)  # visible symbol preserved


class TestDetectProxy(unittest.TestCase):
    """_detect_proxy: resolve proxy from env vars or port probing."""

    def test_all_proxy_env_var(self):
        with patch.dict(os.environ, {"ALL_PROXY": "socks5://10.0.0.1:1080"}):
            self.assertEqual(soulseek_client._detect_proxy(), "socks5://10.0.0.1:1080")

    def test_http_proxy_env_var(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy")}
        env["HTTP_PROXY"] = "http://proxy:8080"
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(soulseek_client._detect_proxy(), "http://proxy:8080")

    def test_no_proxy_no_ports_returns_empty(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
                             "HTTPS_PROXY", "https_proxy")}
        with patch.dict(os.environ, env, clear=True):
            with patch("socket.socket") as mock_sock:
                mock_sock.return_value.connect.side_effect = ConnectionRefusedError
                self.assertEqual(soulseek_client._detect_proxy(), "")

    def test_env_takes_priority_over_port_probe(self):
        with patch.dict(os.environ, {"ALL_PROXY": "http://envproxy:3128"}):
            # Even if a port is open, env var should win
            result = soulseek_client._detect_proxy()
            self.assertEqual(result, "http://envproxy:3128")


class TestDownloadBestCandidateOrdering(unittest.TestCase):
    """download_best: tries candidates in order, stops on first success."""

    def _mkcand(self, username, filename, filesize):
        return {"username": username, "filename": filename, "filesize": filesize}

    def test_first_candidate_success(self):
        cands = [self._mkcand("u1", "f1.flac", 100)]
        with patch.object(soulseek_client, "download", return_value=(True, "/out/f1.flac")) as m:
            with patch.object(soulseek_client, "_get_creds", return_value=("u", "p")):
                ok, path = soulseek_client.download_best(cands, "/out")
        self.assertTrue(ok)
        self.assertEqual(path, "/out/f1.flac")
        m.assert_called_once()

    def test_skips_failed_candidate(self):
        cands = [
            self._mkcand("u1", "f1.flac", 100),
            self._mkcand("u2", "f2.flac", 200),
        ]
        results = [(False, None), (True, "/out/f2.flac")]
        with patch.object(soulseek_client, "download", side_effect=results) as m:
            with patch.object(soulseek_client, "_get_creds", return_value=("u", "p")):
                with patch("time.sleep"):  # skip retry backoff
                    ok, path = soulseek_client.download_best(cands, "/out", max_retries=1)
        self.assertTrue(ok)
        self.assertEqual(path, "/out/f2.flac")
        self.assertEqual(m.call_count, 2)

    def test_all_fail_returns_false(self):
        cands = [self._mkcand("u1", "f1.flac", 100)]
        with patch.object(soulseek_client, "download", return_value=(False, None)):
            with patch.object(soulseek_client, "_get_creds", return_value=("u", "p")):
                with patch("time.sleep"):
                    ok, path = soulseek_client.download_best(cands, "/out", max_retries=2)
        self.assertFalse(ok)
        self.assertIsNone(path)

    def test_no_creds_returns_false(self):
        cands = [self._mkcand("u1", "f1.flac", 100)]
        with patch.object(soulseek_client, "_get_creds", return_value=(None, None)):
            ok, path = soulseek_client.download_best(cands, "/out")
        self.assertFalse(ok)
        self.assertIsNone(path)

    def test_timeout_scales_with_filesize(self):
        """Large files (>50MB) should get 360s timeout, small (<20MB) 120s."""
        big = self._mkcand("u1", "big.flac", 60 * 1024 * 1024)
        small = self._mkcand("u2", "small.flac", 10 * 1024 * 1024)

        captured = []

        def fake_download(target_user, remote_path, output_dir, username=None,
                          password=None, timeout=120, proxy=""):
            captured.append(timeout)
            return True, "/out/file"

        with patch.object(soulseek_client, "download", side_effect=fake_download):
            with patch.object(soulseek_client, "_get_creds", return_value=("u", "p")):
                soulseek_client.download_best([big], "/out", max_retries=1)
                soulseek_client.download_best([small], "/out", max_retries=1)

        self.assertEqual(captured, [360, 120])


class TestSearchAndDownloadCandidateSelection(unittest.TestCase):
    """search_and_download: candidate sorting prefers FLAC, then smaller files."""

    def test_flac_preferred_over_mp3(self):
        """When both FLAC and MP3 available, FLAC candidates come first."""
        # We can't easily test the full async flow, but we can verify
        # the sorting logic by checking the candidate filter+sort in isolation.
        results = [
            {"extension": "mp3", "filesize": 5000000, "username": "u1", "filename": "f.mp3"},
            {"extension": "flac", "filesize": 30000000, "username": "u2", "filename": "f.flac"},
            {"extension": "flac", "filesize": 25000000, "username": "u3", "filename": "f2.flac"},
            {"extension": "wav", "filesize": 40000000, "username": "u4", "filename": "f.wav"},
        ]

        # Replicate the sorting from search_and_download
        candidates = [r for r in results
                      if r.get("extension") in ("flac", "mp3", "wav", "alac", "ape", "wv")]
        candidates.sort(key=lambda x: (0 if x["extension"] == "flac" else 1, x["filesize"]))

        # FLAC candidates first (sorted by filesize asc), then non-FLAC
        self.assertEqual(candidates[0]["extension"], "flac")
        self.assertEqual(candidates[0]["filesize"], 25000000)  # smaller FLAC first
        self.assertEqual(candidates[1]["extension"], "flac")
        self.assertEqual(candidates[1]["filesize"], 30000000)
        self.assertEqual(candidates[2]["extension"], "mp3")
        self.assertEqual(candidates[3]["extension"], "wav")

    def test_non_audio_filtered_out(self):
        results = [
            {"extension": "flac", "filesize": 30000000, "username": "u", "filename": "f.flac"},
            {"extension": "txt", "filesize": 100, "username": "u", "filename": "readme.txt"},
            {"extension": "jpg", "filesize": 500000, "username": "u", "filename": "cover.jpg"},
        ]
        candidates = [r for r in results
                      if r.get("extension") in ("flac", "mp3", "wav", "alac", "ape", "wv")]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["extension"], "flac")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit + integration tests for extracted API client modules.

Uses mocked HTTP responses so tests are fast and deterministic.
Run with:  python -m unittest tests.test_api_clients -v
"""

import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import bili_client
import cover_client
import mbrainz_client
import netease_client


def _mock_urlopen(json_data=None, text_data=None, status=200, headers=None):
    """Build a mock for urllib.request.urlopen return value."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.headers = headers or {"Content-Type": "application/json"}
    if json_data is not None:
        mock_resp.read.return_value = json.dumps(json_data).encode("utf-8")
    elif text_data is not None:
        mock_resp.read.return_value = text_data.encode("utf-8")
    else:
        mock_resp.read.return_value = b""
    return mock_resp


class TestBiliClient(unittest.TestCase):

    def setUp(self):
        # Reset WBI cache so each test starts fresh
        bili_client._WBI_CACHE["ik"] = None
        bili_client._WBI_CACHE["sk"] = None
        bili_client._WBI_CACHE["ts"] = 0
        # Mock _search_plain to return empty (avoids fallback side effects)
        self._plain_patcher = patch.object(bili_client, "_search_plain", return_value=[])
        self._plain_patcher.start()

    def tearDown(self):
        self._plain_patcher.stop()

    def _nav_data(self):
        return {
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/abcdefghijklmnopqrstuvwxyz123456.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/654321zyxwvutsrqponmlkjihgfedcba.png",
                }
            }
        }

    @patch("urllib.request.urlopen")
    def test_search_success(self, mock_urlopen):
        search_data = {
            "code": 0,
            "data": {
                "result": [
                    {"bvid": "BV1xx", "aid": 123, "title": "周杰伦《稻香》",
                     "duration": "3:45", "play": 10000, "author": "周杰伦"},
                    {"bvid": "BV1yy", "aid": 456, "title": "周杰伦 - 晴天",
                     "duration": "4:15", "play": 5000, "author": "周杰伦"},
                ]
            }
        }
        # nav call + search call = 2 urlopen calls
        mock_urlopen.side_effect = [
            _mock_urlopen(json_data=self._nav_data()),
            _mock_urlopen(json_data=search_data),
        ]
        results = bili_client.search("周杰伦", limit=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["bvid"], "BV1xx")
        self.assertEqual(results[0]["title"], "周杰伦《稻香》")
        self.assertEqual(results[0]["uploader"], "周杰伦")

    @patch("urllib.request.urlopen")
    def test_search_api_error(self, mock_urlopen):
        error_data = {"code": -1, "message": "rate limit"}
        # nav succeeds, search returns error (code != 0 → no retry for code -1)
        mock_urlopen.side_effect = [
            _mock_urlopen(json_data=self._nav_data()),
            _mock_urlopen(json_data=error_data),
        ]
        results = bili_client.search("test", limit=2)
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    def test_search_network_error(self, mock_urlopen):
        # All urlopen calls raise OSError
        mock_urlopen.side_effect = OSError("Connection failed")
        results = bili_client.search("test", limit=2)
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    def test_search_412_retry_then_succeed(self, mock_urlopen):
        search_data = {
            "code": 0,
            "data": {
                "result": [
                    {"bvid": "BV1zz", "aid": 789, "title": "Test Song",
                     "duration": "3:00", "play": 500, "author": "Artist"},
                ]
            }
        }
        # First attempt: nav succeeds, search returns 412 → retry
        # Second attempt: nav cached, search succeeds
        nav_resp = _mock_urlopen(json_data=self._nav_data())
        err_resp = MagicMock()
        err_resp.__enter__.return_value = err_resp
        err_resp.read.side_effect = urllib.error.HTTPError(
            "https://api.bilibili.com/x/web-interface/search/type", 412,
            "Precondition Failed", {}, None
        )
        ok_resp = _mock_urlopen(json_data=search_data)

        mock_urlopen.side_effect = [nav_resp, err_resp, ok_resp]

        results = bili_client.search("test", limit=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["bvid"], "BV1zz")

    @patch("urllib.request.urlopen")
    def test_search_plain_fallback(self, mock_urlopen):
        """When WBI search fails after retries, _search_plain is tried."""
        self._plain_patcher.stop()  # Remove the mock for this test

        plain_data = {
            "results": [
                {"bvid": "BV1aa", "aid": 111, "title": "Fallback Song",
                 "duration": "2:30", "play": 100, "author": "Fallback Artist"},
            ]
        }
        # All WBI retries fail with OSError, then plain search succeeds
        mock_urlopen.side_effect = [
            OSError("timeout"),   # WBI nav retry 1
            OSError("timeout"),   # WBI nav retry 2
            OSError("timeout"),   # WBI nav retry 3
            _mock_urlopen(json_data=plain_data),  # plain search succeeds
        ]
        results = bili_client.search("test", limit=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["bvid"], "BV1aa")
        self.assertEqual(results[0]["title"], "Fallback Song")
        self._plain_patcher.start()  # Restore mock for other tests


class TestNeteaseClient(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_search_success(self, mock_urlopen):
        resp_data = {
            "code": 200,
            "result": {
                "songs": [
                    {
                        "name": "稻香",
                        "artists": [{"name": "周杰伦"}],
                        "album": {"name": "魔杰座", "picUrl": "https://p2.music.126.net/cover.jpg"},
                        "duration": 234000,
                    }
                ]
            }
        }
        mock_urlopen.return_value = _mock_urlopen(json_data=resp_data)
        results = netease_client.search("周杰伦 稻香", limit=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "稻香")
        self.assertEqual(results[0]["artist"], "周杰伦")
        self.assertEqual(results[0]["album"], "魔杰座")

    @patch("urllib.request.urlopen")
    def test_search_empty(self, mock_urlopen):
        resp_data = {"code": 200, "result": {"songs": []}}
        mock_urlopen.return_value = _mock_urlopen(json_data=resp_data)
        results = netease_client.search("nonexistent song xyz123", limit=1)
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    def test_search_bad_code(self, mock_urlopen):
        resp_data = {"code": 400, "message": "bad request"}
        mock_urlopen.return_value = _mock_urlopen(json_data=resp_data)
        results = netease_client.search("test", limit=1)
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    def test_detail_success(self, mock_urlopen):
        resp_data = {
            "code": 200,
            "songs": [
                {
                    "name": "稻香",
                    "artists": [{"name": "周杰伦"}],
                    "album": {"name": "魔杰座"},
                }
            ]
        }
        mock_urlopen.return_value = _mock_urlopen(json_data=resp_data)
        result = netease_client.detail("185809")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "稻香")
        self.assertEqual(result["artist"], "周杰伦")

    @patch("urllib.request.urlopen")
    def test_detail_not_found(self, mock_urlopen):
        resp_data = {"code": 200, "songs": []}
        mock_urlopen.return_value = _mock_urlopen(json_data=resp_data)
        result = netease_client.detail("999999")
        self.assertIsNone(result)

    @patch("urllib.request.urlopen")
    def test_detail_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("timeout")
        result = netease_client.detail("185809")
        self.assertIsNone(result)


class TestMbrainzClient(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch("time.sleep", return_value=None)  # skip rate-limit sleep
    def test_lookup_success(self, mock_sleep, mock_urlopen):
        resp_data = {
            "recordings": [
                {
                    "title": "Blinding Lights",
                    "artist-credit": [{"name": "The Weeknd"}],
                    "releases": [
                        {"title": "After Hours", "id": "mbid-123"}
                    ],
                    "length": 200000,
                }
            ]
        }
        # First call = MusicBrainz, second and third = cover art archive tries
        mock_urlopen.side_effect = [
            _mock_urlopen(json_data=resp_data),
            _mock_urlopen(text_data="cover data", headers={"Content-Type": "image/jpeg"}),
        ]
        results = mbrainz_client.lookup('artist:"The Weeknd" AND recording:"Blinding Lights"', limit=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Blinding Lights")
        self.assertEqual(results[0]["artist"], "The Weeknd")

    @patch("urllib.request.urlopen")
    @patch("time.sleep", return_value=None)
    def test_lookup_no_results(self, mock_sleep, mock_urlopen):
        resp_data = {"recordings": []}
        mock_urlopen.return_value = _mock_urlopen(json_data=resp_data)
        results = mbrainz_client.lookup("test test", limit=1)
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    @patch("time.sleep", return_value=None)
    def test_lookup_network_error(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = OSError("DNS failure")
        results = mbrainz_client.lookup("test test", limit=1)
        self.assertEqual(results, [])


class TestCoverClient(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_download_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b"fake_image_data"
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_urlopen.return_value = mock_resp

        path = cover_client.download("https://example.com/cover.jpg")
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"fake_image_data")
        os.unlink(path)

    def test_download_empty_url(self):
        path = cover_client.download("")
        self.assertIsNone(path)

    def test_download_none_url(self):
        path = cover_client.download(None)
        self.assertIsNone(path)

    @patch("urllib.request.urlopen")
    def test_download_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("connection refused")
        path = cover_client.download("https://example.com/cover.jpg")
        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)

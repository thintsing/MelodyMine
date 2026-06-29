#!/usr/bin/env python3
"""Unit tests for ytmusic_client — injects fake ytmusicapi before import."""

import json
import sys
import unittest
from unittest.mock import patch, MagicMock

# Inject a fake ytmusicapi module before ytmusic_client is imported,
# so tests work without the real package installed.
_fake_ytmusicapi = MagicMock()
_fake_ytm_cls = MagicMock()
_fake_ytmusicapi.YTMusic = _fake_ytm_cls
sys.modules["ytmusicapi"] = _fake_ytmusicapi

_SCRIPTS = "scripts"
sys.path.insert(0, _SCRIPTS)
import ytmusic_client


class TestYtmusicSearch(unittest.TestCase):

    def setUp(self):
        self.mock_ytm = MagicMock()
        _fake_ytm_cls.return_value = self.mock_ytm

    def test_search_songs_success(self):
        self.mock_ytm.search.return_value = [
            {"videoId": "abc123", "title": "Test Song",
             "artists": [{"name": "Artist A"}], "album": {"name": "Album X"}, "duration": 200},
        ]
        results = ytmusic_client.search("test song", limit=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["videoId"], "abc123")
        self.assertEqual(results[0]["title"], "Test Song")
        self.assertEqual(results[0]["artist"], "Artist A")
        self.assertEqual(results[0]["album"], "Album X")
        self.assertEqual(results[0]["duration"], 200)
        self.assertIn("abc123", results[0]["url"])

    def test_search_songs_empty_falls_back_to_videos(self):
        video_result = {"videoId": "vid999", "title": "Video Song",
                        "artists": [{"name": "V Creator"}], "album": {}, "duration": None}
        self.mock_ytm.search.side_effect = [[], [video_result]]
        results = ytmusic_client.search("chinese song", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["videoId"], "vid999")
        self.assertEqual(self.mock_ytm.search.call_count, 2)
        first_call = self.mock_ytm.search.call_args_list[0]
        second_call = self.mock_ytm.search.call_args_list[1]
        self.assertEqual(first_call.kwargs.get("filter"), "songs")
        self.assertEqual(second_call.kwargs.get("filter"), "videos")

    def test_search_both_empty(self):
        self.mock_ytm.search.return_value = []
        results = ytmusic_client.search("nonexistent", limit=3)
        self.assertEqual(results, [])

    def test_search_exception_returns_empty(self):
        self.mock_ytm.search.side_effect = Exception("Network error")
        results = ytmusic_client.search("query", limit=3)
        self.assertEqual(results, [])

    def test_search_no_video_id_skipped(self):
        self.mock_ytm.search.return_value = [
            {"title": "No ID Song", "artists": [], "album": {}, "duration": None},
            {"videoId": "valid123", "title": "Valid Song", "artists": [{"name": "A"}], "album": {}, "duration": 100},
        ]
        results = ytmusic_client.search("test", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["videoId"], "valid123")

    def test_search_multiple_artists(self):
        self.mock_ytm.search.return_value = [
            {"videoId": "x", "title": "Collab",
             "artists": [{"name": "A"}, {"name": "B"}], "album": {}, "duration": 180},
        ]
        results = ytmusic_client.search("collab", limit=1)
        self.assertEqual(results[0]["artist"], "A, B")

    @patch("builtins.__import__", side_effect=ImportError("no module named 'ytmusicapi'"))
    def test_search_import_error_returns_empty(self, mock_import):
        results = ytmusic_client.search("test", limit=3)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Unit tests for ytmusic_client."""

import json
import sys
import unittest
from unittest.mock import patch, MagicMock

_SCRIPTS = "scripts"
sys.path.insert(0, _SCRIPTS)

import ytmusic_client


class TestYtmusicSearch(unittest.TestCase):

    @patch("ytmusicapi.YTMusic")
    def test_search_songs_success(self, mock_ytm_cls):
        mock_ytm = MagicMock()
        mock_ytm_cls.return_value = mock_ytm
        mock_ytm.search.return_value = [
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

    @patch("ytmusicapi.YTMusic")
    def test_search_songs_empty_falls_back_to_videos(self, mock_ytm_cls):
        mock_ytm = MagicMock()
        mock_ytm_cls.return_value = mock_ytm

        # songs returns empty, videos returns results
        video_result = {"videoId": "vid999", "title": "Video Song",
                        "artists": [{"name": "V Creator"}], "album": {}, "duration": None}
        mock_ytm.search.side_effect = [[], [video_result]]

        results = ytmusic_client.search("chinese song", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["videoId"], "vid999")
        self.assertEqual(mock_ytm.search.call_count, 2)
        first_call = mock_ytm.search.call_args_list[0]
        second_call = mock_ytm.search.call_args_list[1]
        self.assertEqual(first_call.kwargs.get("filter"), "songs")
        self.assertEqual(second_call.kwargs.get("filter"), "videos")

    @patch("ytmusicapi.YTMusic")
    def test_search_both_empty(self, mock_ytm_cls):
        mock_ytm = MagicMock()
        mock_ytm_cls.return_value = mock_ytm
        mock_ytm.search.return_value = []

        results = ytmusic_client.search("nonexistent", limit=3)
        self.assertEqual(results, [])

    @patch("ytmusicapi.YTMusic")
    def test_search_exception_returns_empty(self, mock_ytm_cls):
        mock_ytm = MagicMock()
        mock_ytm_cls.return_value = mock_ytm
        mock_ytm.search.side_effect = Exception("Network error")

        results = ytmusic_client.search("query", limit=3)
        self.assertEqual(results, [])

    @patch("ytmusicapi.YTMusic")
    def test_search_no_video_id_skipped(self, mock_ytm_cls):
        mock_ytm = MagicMock()
        mock_ytm_cls.return_value = mock_ytm
        mock_ytm.search.return_value = [
            {"title": "No ID Song", "artists": [], "album": {}, "duration": None},
            {"videoId": "valid123", "title": "Valid Song", "artists": [{"name": "A"}], "album": {}, "duration": 100},
        ]

        results = ytmusic_client.search("test", limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["videoId"], "valid123")

    @patch("ytmusicapi.YTMusic")
    def test_search_multiple_artists(self, mock_ytm_cls):
        mock_ytm = MagicMock()
        mock_ytm_cls.return_value = mock_ytm
        mock_ytm.search.return_value = [
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

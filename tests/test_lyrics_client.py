#!/usr/bin/env python3
"""Unit tests for lyrics_client module.

Uses mocked HTTP responses so tests are fast and deterministic.
Run with:  python -m unittest tests.test_lyrics_client -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import lyrics_client


def _mock_urlopen(json_data=None, status=200):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.headers = {"Content-Type": "application/json"}
    if json_data is not None:
        mock_resp.read.return_value = json.dumps(json_data).encode("utf-8")
    else:
        mock_resp.read.return_value = b""
    return mock_resp


class TestLyricsSearch(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_search_returns_results(self, mock_open):
        api_response = [
            {
                "trackName": "稻香",
                "artistName": "周杰伦",
                "albumName": "魔杰座",
                "duration": 223,
                "instrumental": False,
                "syncedLyrics": "[00:10.00]歌词内容",
                "plainLyrics": "歌词内容",
            }
        ]
        mock_open.return_value = _mock_urlopen(api_response)

        results = lyrics_client.search("周杰伦 稻香")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "稻香")
        self.assertEqual(results[0]["artist"], "周杰伦")
        self.assertEqual(results[0]["synced_lyrics"], "[00:10.00]歌词内容")
        self.assertEqual(results[0]["plain_lyrics"], "歌词内容")

    @patch("urllib.request.urlopen")
    def test_search_filters_instrumental(self, mock_open):
        api_response = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 200,
                "instrumental": True,
                "syncedLyrics": None,
                "plainLyrics": None,
            }
        ]
        mock_open.return_value = _mock_urlopen(api_response)

        results = lyrics_client.search("Artist Song")
        self.assertEqual(len(results), 0)

    @patch("urllib.request.urlopen")
    def test_search_filters_empty_lyrics(self, mock_open):
        api_response = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 200,
                "instrumental": False,
                "syncedLyrics": None,
                "plainLyrics": None,
            }
        ]
        mock_open.return_value = _mock_urlopen(api_response)

        results = lyrics_client.search("Artist Song")
        self.assertEqual(len(results), 0)

    @patch("urllib.request.urlopen")
    def test_search_respects_limit(self, mock_open):
        api_response = [
            {
                "trackName": f"Song{i}",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 200,
                "instrumental": False,
                "syncedLyrics": f"Lyrics {i}",
                "plainLyrics": f"Lyrics {i}",
            }
            for i in range(10)
        ]
        mock_open.return_value = _mock_urlopen(api_response)

        results = lyrics_client.search("Artist", limit=3)
        self.assertEqual(len(results), 3)

    def test_search_empty_query(self):
        self.assertEqual(lyrics_client.search(""), [])
        self.assertEqual(lyrics_client.search(None), [])

    @patch("urllib.request.urlopen")
    def test_search_network_error(self, mock_open):
        mock_open.side_effect = Exception("network error")
        results = lyrics_client.search("test query")
        self.assertEqual(results, [])


class TestGetLyrics(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_direct_lookup_success(self, mock_open):
        api_response = {
            "trackName": "稻香",
            "artistName": "周杰伦",
            "albumName": "魔杰座",
            "duration": 223,
            "syncedLyrics": "[00:10.00]对这个世界如果你有许多的抱怨",
            "plainLyrics": "对这个世界如果你有许多的抱怨",
        }
        mock_open.return_value = _mock_urlopen(api_response)

        result = lyrics_client.get_lyrics("周杰伦", "稻香", album="魔杰座")
        self.assertIsNotNone(result)
        self.assertIn("synced_lyrics", result)
        self.assertIn("plain_lyrics", result)
        self.assertTrue(result["synced_lyrics"].startswith("[00:10.00]"))

    @patch("urllib.request.urlopen")
    def test_direct_lookup_falls_back_to_search(self, mock_open):
        direct_response = {
            "trackName": "Song",
            "artistName": "Artist",
            "syncedLyrics": None,
            "plainLyrics": None,
        }
        search_response = [
            {
                "trackName": "Song",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 200,
                "instrumental": False,
                "syncedLyrics": "[00:05.00]Lyrics",
                "plainLyrics": "Lyrics",
            }
        ]
        mock_open.side_effect = [
            _mock_urlopen(direct_response),
            _mock_urlopen(search_response),
        ]

        result = lyrics_client.get_lyrics("Artist", "Song")
        self.assertIsNotNone(result)
        self.assertEqual(result["synced_lyrics"], "[00:05.00]Lyrics")

    def test_get_lyrics_no_title(self):
        self.assertIsNone(lyrics_client.get_lyrics("Artist", ""))
        self.assertIsNone(lyrics_client.get_lyrics("Artist", None))

    @patch("urllib.request.urlopen")
    def test_get_lyrics_all_fail(self, mock_open):
        mock_open.side_effect = Exception("network error")
        result = lyrics_client.get_lyrics("Artist", "Song")
        self.assertIsNone(result)


class TestSaveLrc(unittest.TestCase):

    def test_save_synced_lyrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "song.mp3")
            open(audio_path, "w").close()

            synced = "[00:10.00]Line 1\n[00:15.00]Line 2"
            lrc_path = lyrics_client.save_lrc(audio_path, synced)

            self.assertIsNotNone(lrc_path)
            self.assertTrue(lrc_path.endswith(".lrc"))
            self.assertTrue(os.path.isfile(lrc_path))

            with open(lrc_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, synced)

    def test_save_plain_lyrics_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "song.mp3")
            open(audio_path, "w").close()

            plain = "Line 1\nLine 2\nLine 3"
            lrc_path = lyrics_client.save_lrc(audio_path, "", plain_lyrics=plain)

            self.assertIsNotNone(lrc_path)
            with open(lrc_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, plain)

    def test_save_prefers_synced_over_plain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "song.mp3")
            open(audio_path, "w").close()

            synced = "[00:10.00]Synced line"
            plain = "Plain line"
            lrc_path = lyrics_client.save_lrc(audio_path, synced, plain_lyrics=plain)

            with open(lrc_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, synced)

    def test_save_no_lyrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "song.mp3")
            open(audio_path, "w").close()

            result = lyrics_client.save_lrc(audio_path, "", plain_lyrics="")
            self.assertIsNone(result)

    def test_save_no_filepath(self):
        result = lyrics_client.save_lrc(None, "lyrics")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

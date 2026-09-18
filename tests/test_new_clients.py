#!/usr/bin/env python3
"""Unit tests for kuwo_client, audius_client, and kugou_client modules.

Uses mocked HTTP responses so tests are fast and deterministic.
Run with:  python -m unittest tests.test_new_clients -v
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import audius_client
import kugou_client
import kuwo_client


def _mock_urlopen(json_data=None, raw_bytes=None, status=200):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.headers = {"Content-Type": "application/json"}
    if raw_bytes is not None:
        mock_resp.read.return_value = raw_bytes
    elif json_data is not None:
        mock_resp.read.return_value = json.dumps(json_data).encode("utf-8")
    else:
        mock_resp.read.return_value = b""
    return mock_resp


# ─── Kuwo ────────────────────────────────────────────────────────────────

class TestKuwoSearch(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_search_returns_results(self, mock_open):
        api_response = {
            "abslist": [
                {
                    "MUSICRID": "MUSIC_12345",
                    "SONGNAME": "稻香",
                    "ARTIST": "周杰伦",
                    "ALBUM": "魔杰座",
                    "DURATION": "223",
                    "hts_MVPIC": "https://img.kuwo.cn/pic.jpg",
                }
            ]
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = kuwo_client.search("周杰伦 稻香")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "稻香")
        self.assertEqual(results[0]["artist"], "周杰伦")
        self.assertEqual(results[0]["music_id"], "12345")
        self.assertEqual(results[0]["duration"], 223)

    @patch("urllib.request.urlopen")
    def test_search_alternative_field_names(self, mock_open):
        api_response = {
            "abslist": [
                {
                    "musicrid": "MUSIC_99999",
                    "name": "Song",
                    "artist": "Artist",
                    "album": "Album",
                    "duration": "180",
                }
            ]
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = kuwo_client.search("test")
        self.assertEqual(results[0]["music_id"], "99999")
        self.assertEqual(results[0]["title"], "Song")

    @patch("urllib.request.urlopen")
    def test_search_skips_missing_rid(self, mock_open):
        api_response = {
            "abslist": [
                {"MUSICRID": "", "SONGNAME": "No ID"},
                {"MUSICRID": "MUSIC_111", "SONGNAME": "Valid"},
            ]
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = kuwo_client.search("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Valid")

    def test_search_empty_query(self):
        self.assertEqual(kuwo_client.search(""), [])
        self.assertEqual(kuwo_client.search(None), [])

    @patch("urllib.request.urlopen")
    def test_search_network_error(self, mock_open):
        mock_open.side_effect = Exception("network error")
        self.assertEqual(kuwo_client.search("test"), [])


class TestKuwoDownloadUrl(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_fallback_success(self, mock_open):
        api_response = {"data": {"url": "https://cdn.kuwo.cn/song.flac"}}
        mock_open.return_value = _mock_urlopen(api_response)

        url = kuwo_client.get_download_url("12345", quality="lossless")
        self.assertEqual(url, "https://cdn.kuwo.cn/song.flac")

    @patch("urllib.request.urlopen")
    def test_all_fallbacks_fail(self, mock_open):
        mock_open.side_effect = Exception("network error")
        url = kuwo_client.get_download_url("12345")
        self.assertIsNone(url)

    def test_missing_id_returns_none(self):
        self.assertIsNone(kuwo_client.get_download_url(""))
        self.assertIsNone(kuwo_client.get_download_url(None))


# ─── Audius ──────────────────────────────────────────────────────────────

class TestAudiusSearch(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_search_returns_results(self, mock_open):
        api_response = {
            "data": [
                {
                    "id": "track_abc123",
                    "title": "Sunrise",
                    "duration": 240,
                    "artwork": {"1000x1000": "https://art.example.com/1000.jpg"},
                    "user": {"name": "DJ Test"},
                }
            ]
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = audius_client.search("sunrise")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Sunrise")
        self.assertEqual(results[0]["artist"], "DJ Test")
        self.assertEqual(results[0]["track_id"], "track_abc123")
        self.assertEqual(results[0]["duration"], 240)
        self.assertEqual(results[0]["artwork_url"], "https://art.example.com/1000.jpg")

    @patch("urllib.request.urlopen")
    def test_search_artwork_fallback(self, mock_open):
        api_response = {
            "data": [
                {
                    "id": "track_xyz",
                    "title": "Song",
                    "duration": 180,
                    "artwork": {"150x150": "https://art.example.com/150.jpg"},
                    "user": {"name": "Artist"},
                }
            ]
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = audius_client.search("test")
        self.assertEqual(results[0]["artwork_url"], "https://art.example.com/150.jpg")

    @patch("urllib.request.urlopen")
    def test_search_skips_missing_id(self, mock_open):
        api_response = {
            "data": [
                {"id": "", "title": "No ID"},
                {"id": "track_ok", "title": "Valid", "duration": 100, "user": {"name": "A"}},
            ]
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = audius_client.search("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["track_id"], "track_ok")

    def test_search_empty_query(self):
        self.assertEqual(audius_client.search(""), [])
        self.assertEqual(audius_client.search(None), [])

    @patch("urllib.request.urlopen")
    def test_search_network_error(self, mock_open):
        mock_open.side_effect = Exception("network error")
        self.assertEqual(audius_client.search("test"), [])


class TestAudiusStreamUrl(unittest.TestCase):

    def test_stream_url_format(self):
        url = audius_client.get_stream_url("track_abc123")
        self.assertIn("track_abc123/stream", url)
        self.assertIn("app_name=", url)

    def test_missing_id_returns_none(self):
        self.assertIsNone(audius_client.get_stream_url(""))
        self.assertIsNone(audius_client.get_stream_url(None))


# ─── Kugou ───────────────────────────────────────────────────────────────

class TestKugouSearch(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_search_returns_results(self, mock_open):
        api_response = {
            "data": {
                "lists": [
                    {
                        "hash": "ABCDEF1234567890",
                        "songname": "稻香",
                        "singername": "周杰伦",
                        "album_name": "魔杰座",
                        "duration": 223,
                        "cover_url": "https://img.kugou.cn/pic.jpg",
                    }
                ]
            }
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = kugou_client.search("周杰伦 稻香")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "稻香")
        self.assertEqual(results[0]["artist"], "周杰伦")
        self.assertEqual(results[0]["hash"], "ABCDEF1234567890")
        self.assertEqual(results[0]["duration"], 223)

    @patch("urllib.request.urlopen")
    def test_search_singers_array(self, mock_open):
        api_response = {
            "data": {
                "lists": [
                    {
                        "hash": "HASH001",
                        "SongName": "Duet",
                        "Singers": [{"name": "Alice"}, {"name": "Bob"}],
                        "AlbumName": "Album",
                        "Duration": 200,
                    }
                ]
            }
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = kugou_client.search("Duet")
        self.assertEqual(results[0]["artist"], "Alice, Bob")

    @patch("urllib.request.urlopen")
    def test_search_timelen_to_duration(self, mock_open):
        api_response = {
            "data": {
                "lists": [
                    {
                        "hash": "HASH002",
                        "songname": "Song",
                        "singername": "Artist",
                        "timelen": 180000,
                    }
                ]
            }
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = kugou_client.search("test")
        self.assertEqual(results[0]["duration"], 180)

    @patch("urllib.request.urlopen")
    def test_search_skips_missing_hash(self, mock_open):
        api_response = {
            "data": {
                "lists": [
                    {"hash": "", "songname": "No Hash"},
                    {"hash": "VALIDHASH", "songname": "Valid"},
                ]
            }
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = kugou_client.search("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["hash"], "VALIDHASH")

    def test_search_empty_query(self):
        self.assertEqual(kugou_client.search(""), [])
        self.assertEqual(kugou_client.search(None), [])

    @patch("urllib.request.urlopen")
    def test_search_network_error(self, mock_open):
        mock_open.side_effect = Exception("network error")
        self.assertEqual(kugou_client.search("test"), [])


class TestKugouDownloadUrl(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_fallback_success(self, mock_open):
        api_response = {"data": {"url": "https://cdn.kugou.cn/song.flac"}}
        mock_open.return_value = _mock_urlopen(api_response)

        url = kugou_client.get_download_url("HASH001", quality="lossless")
        self.assertEqual(url, "https://cdn.kugou.cn/song.flac")

    @patch("urllib.request.urlopen")
    def test_tracker_fallback(self, mock_open):
        tracker_response = {"url": "https://tracker.kugou.cn/song.mp3"}
        mock_open.side_effect = [
            Exception("haitang fail"),
            Exception("cocodownloader fail"),
            _mock_urlopen(tracker_response),
        ]

        url = kugou_client.get_download_url("HASH001")
        self.assertEqual(url, "https://tracker.kugou.cn/song.mp3")

    @patch("urllib.request.urlopen")
    def test_all_methods_fail(self, mock_open):
        mock_open.side_effect = Exception("network error")
        url = kugou_client.get_download_url("HASH001")
        self.assertIsNone(url)

    def test_missing_hash_returns_none(self):
        self.assertIsNone(kugou_client.get_download_url(""))
        self.assertIsNone(kugou_client.get_download_url(None))


if __name__ == "__main__":
    unittest.main()

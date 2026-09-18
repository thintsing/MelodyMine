#!/usr/bin/env python3
"""Unit tests for migu_client module.

Uses mocked HTTP responses so tests are fast and deterministic.
Run with:  python -m unittest tests.test_migu_client -v
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import migu_client


def _mock_urlopen(data, status=200):
    """Build a mock for urllib.request.urlopen return value.

    *data* can be bytes (returned as-is) or a JSON-serializable object.
    """
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.headers = {"Content-Type": "application/json"}
    if isinstance(data, bytes):
        mock_resp.read.return_value = data
    else:
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
    return mock_resp


def _encrypt(payload_bytes):
    """Encrypt bytes with Migu's XOR-shift cipher (inverse of _decrypt)."""
    seed = 0x42
    enc = bytes((b - seed + migu_client._XOR_KEY[i % 32]) & 0xFF
                for i, b in enumerate(payload_bytes))
    return migu_client._MAGIC + bytes([seed]) + enc


class TestDecrypt(unittest.TestCase):

    def test_roundtrip(self):
        original = b'{"data":{"url":"https://example.com/song.mp3"}}'
        encrypted = _encrypt(original)
        self.assertEqual(migu_client._decrypt(encrypted), original)

    def test_non_encrypted_returns_none(self):
        plain = b'{"data":{}}'
        self.assertIsNone(migu_client._decrypt(plain))

    def test_too_short_returns_none(self):
        self.assertIsNone(migu_client._decrypt(b"\xab\xcd"))


class TestSearch(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_search_returns_results(self, mock_open):
        api_response = {
            "songResultData": {
                "result": [
                    {
                        "contentId": "CID001",
                        "copyrightId": "CR001",
                        "name": "稻香",
                        "singers": [{"name": "周杰伦"}],
                        "album": {"albumName": "魔杰座", "picUrl": "https://img.example.com/pic.jpg"},
                        "length": 223,
                        "rateFormats": [{"resourceType": "E"}],
                    }
                ]
            }
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = migu_client.search("周杰伦 稻香")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "稻香")
        self.assertEqual(results[0]["artist"], "周杰伦")
        self.assertEqual(results[0]["album"], "魔杰座")
        self.assertEqual(results[0]["content_id"], "CID001")
        self.assertEqual(results[0]["copyright_id"], "CR001")
        self.assertTrue(results[0]["has_flac"])

    @patch("urllib.request.urlopen")
    def test_search_multiple_singers(self, mock_open):
        api_response = {
            "songResultData": {
                "result": [
                    {
                        "contentId": "CID002",
                        "copyrightId": "CR002",
                        "name": "Duet",
                        "singers": [{"name": "Alice"}, {"name": "Bob"}],
                        "album": {"albumName": "Album", "picUrl": ""},
                        "length": 200,
                        "rateFormats": [],
                    }
                ]
            }
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = migu_client.search("Duet")
        self.assertEqual(results[0]["artist"], "Alice, Bob")
        self.assertFalse(results[0]["has_flac"])

    @patch("urllib.request.urlopen")
    def test_search_skips_missing_ids(self, mock_open):
        api_response = {
            "songResultData": {
                "result": [
                    {
                        "contentId": "",
                        "copyrightId": "CR001",
                        "name": "No Content ID",
                        "singers": [{"name": "X"}],
                        "album": {},
                        "length": 100,
                        "rateFormats": [],
                    },
                    {
                        "contentId": "CID003",
                        "copyrightId": "CR003",
                        "name": "Valid",
                        "singers": [{"name": "Y"}],
                        "album": {},
                        "length": 150,
                        "rateFormats": [],
                    },
                ]
            }
        }
        mock_open.return_value = _mock_urlopen(api_response)

        results = migu_client.search("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Valid")

    def test_search_empty_query(self):
        self.assertEqual(migu_client.search(""), [])
        self.assertEqual(migu_client.search(None), [])

    @patch("urllib.request.urlopen")
    def test_search_network_error(self, mock_open):
        mock_open.side_effect = Exception("network error")
        self.assertEqual(migu_client.search("test"), [])

    @patch("urllib.request.urlopen")
    def test_search_empty_song_result_data(self, mock_open):
        mock_open.return_value = _mock_urlopen({"songResultData": None})
        self.assertEqual(migu_client.search("test"), [])


class TestGetDownloadUrl(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_primary_url_success(self, mock_open):
        api_response = {"data": {"url": "https://cdn.example.com/song.flac"}}
        mock_open.return_value = _mock_urlopen(api_response)

        url = migu_client.get_download_url("CID001", "CR001", tone_flag="SQ")
        self.assertEqual(url, "https://cdn.example.com/song.flac")

    @patch("urllib.request.urlopen")
    def test_fallback_when_no_url(self, mock_open):
        api_response = {"data": {"url": ""}}
        mock_open.return_value = _mock_urlopen(api_response)

        url = migu_client.get_download_url("CID001", "CR001", tone_flag="HQ")
        self.assertIn("contentId=CID001", url)
        self.assertIn("copyrightId=CR001", url)
        self.assertIn("toneFlag=HQ", url)

    @patch("urllib.request.urlopen")
    def test_fallback_on_network_error(self, mock_open):
        mock_open.side_effect = Exception("network error")

        url = migu_client.get_download_url("CID001", "CR001")
        self.assertIn("contentId=CID001", url)
        self.assertIn("listenSong.do", url)

    def test_missing_ids_returns_none(self):
        self.assertIsNone(migu_client.get_download_url("", "CR001"))
        self.assertIsNone(migu_client.get_download_url("CID001", ""))
        self.assertIsNone(migu_client.get_download_url(None, None))

    @patch("urllib.request.urlopen")
    def test_invalid_tone_flag_defaults_to_hq(self, mock_open):
        api_response = {"data": {"url": "https://cdn.example.com/song.mp3"}}
        mock_open.return_value = _mock_urlopen(api_response)

        url = migu_client.get_download_url("CID001", "CR001", tone_flag="INVALID")
        self.assertEqual(url, "https://cdn.example.com/song.mp3")

    @patch("urllib.request.urlopen")
    def test_encrypted_listen_response(self, mock_open):
        api_response = {"data": {"url": "https://cdn.example.com/encrypted_song.flac"}}
        raw = json.dumps(api_response).encode("utf-8")
        encrypted = _encrypt(raw)
        mock_open.return_value = _mock_urlopen(encrypted)

        url = migu_client.get_download_url("CID001", "CR001", tone_flag="ZQ")
        self.assertEqual(url, "https://cdn.example.com/encrypted_song.flac")


if __name__ == "__main__":
    unittest.main()

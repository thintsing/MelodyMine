#!/usr/bin/env python3
"""Unit tests for MelodyMine pure functions.

Run with:  python -m unittest tests.test_helpers -v
       or:  python tests/test_helpers.py

Uses only the standard library (unittest) — no pytest dependency.
Covers the pure functions most likely to break during refactors:
parse_search_query, parse_bili_title, _clean_artist, _norm_cn,
auto_select_platform, is_spotify_url, sanitize_filename, is_chinese.
"""

import os
import sys
import unittest

# Make the scripts directory importable regardless of CWD.
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

from melodymine_common import (  # noqa: E402
    auto_select_platform,
    extract_netease_song_id,
    is_bandcamp_url,
    is_chinese,
    is_direct_download_url,
    is_netease_url,
    is_soundcloud_url,
    is_spotify_url,
    is_youtube_url,
    sanitize_filename,
)
from music_helper import (  # noqa: E402
    _clean_artist,
    _norm_cn,
    parse_bili_title,
    parse_search_query,
)


class TestParseSearchQuery(unittest.TestCase):
    """parse_search_query: split 'artist title' → (artist, title)."""

    def test_chinese_two_tokens(self):
        self.assertEqual(parse_search_query("周杰伦 稻香"), ("周杰伦", "稻香"))

    def test_english_multi_token(self):
        # Leading article "The" is grouped with the next token as the artist.
        self.assertEqual(
            parse_search_query("The Weeknd Blinding Lights"),
            ("The Weeknd", "Blinding Lights"),
        )

    def test_english_article_a(self):
        # "A" + next token becomes the artist.
        self.assertEqual(
            parse_search_query("A Test Song"),
            ("A Test", "Song"),
        )

    def test_english_article_an(self):
        self.assertEqual(
            parse_search_query("An End Song"),
            ("An End", "Song"),
        )

    def test_english_no_article_first_token(self):
        # No article: first token stays the artist.
        self.assertEqual(
            parse_search_query("Adele Hello"),
            ("Adele", "Hello"),
        )

    def test_single_token_returns_none_artist(self):
        artist, title = parse_search_query("稻香")
        self.assertIsNone(artist)
        self.assertEqual(title, "稻香")

    def test_empty_string(self):
        artist, title = parse_search_query("")
        self.assertIsNone(artist)
        self.assertEqual(title, "")

    def test_extra_whitespace_collapsed(self):
        artist, title = parse_search_query("  周杰伦   稻香  ")
        self.assertEqual(artist, "周杰伦")
        self.assertEqual(title, "稻香")


class TestParseBiliTitle(unittest.TestCase):

    def test_angle_brackets_pattern(self):
        artist, title = parse_bili_title("周杰伦《稻香》完整版")
        self.assertEqual(artist, "周杰伦")
        self.assertEqual(title, "稻香")

    def test_dash_pattern(self):
        artist, title = parse_bili_title("周杰伦 - 稻香 MV")
        self.assertEqual(artist, "周杰伦")
        self.assertEqual(title, "稻香")

    def test_bracket_pattern(self):
        artist, title = parse_bili_title("【周杰伦】稻香 官方MV")
        self.assertEqual(artist, "周杰伦")
        self.assertEqual(title, "稻香")

    def test_noise_stripped_from_title(self):
        artist, title = parse_bili_title("周杰伦《稻香》高清无损音质")
        self.assertEqual(artist, "周杰伦")
        self.assertEqual(title, "稻香")

    def test_year_stripped(self):
        artist, title = parse_bili_title("周杰伦《稻香》2024")
        self.assertEqual(artist, "周杰伦")
        self.assertEqual(title, "稻香")

    def test_no_match_returns_none(self):
        artist, title = parse_bili_title("just some random title")
        self.assertIsNone(artist)
        self.assertIsNone(title)


class TestCleanArtist(unittest.TestCase):

    def test_strips_trailing_dash(self):
        self.assertEqual(_clean_artist("周杰伦-"), "周杰伦")

    def test_takes_first_comma_artist(self):
        self.assertEqual(_clean_artist("周杰伦,蔡依林"), "周杰伦")

    def test_takes_first_chinese_comma_artist(self):
        self.assertEqual(_clean_artist("周杰伦，蔡依林"), "周杰伦")

    def test_empty_input(self):
        self.assertEqual(_clean_artist(""), "")
        self.assertEqual(_clean_artist(None), "")

    def test_strips_trailing_period(self):
        self.assertEqual(_clean_artist("Artist."), "Artist")


class TestNormCn(unittest.TestCase):

    def test_traditional_to_simplified(self):
        # 倫→伦 is in the map
        self.assertEqual(_norm_cn("\u5468\u6770\u502b"), "\u5468\u6770\u4f26")  # 周杰倫→周杰伦
        # 學→学 is in the map; 張/友 are NOT
        self.assertEqual(_norm_cn("\u5f35\u5b78\u53cb"), "\u5f35\u5b66\u53cb")  # 張學友→张学友
        # 劉/德/華 are all NOT in the map → unchanged
        self.assertEqual(_norm_cn("\u5289\u5fb7\u83ef"), "\u5289\u5fb7\u83ef")  # 劉德華 unchanged

    def test_already_simplified_unchanged(self):
        self.assertEqual(_norm_cn("\u5468\u6770\u4f26"), "\u5468\u6770\u4f26")  # 周杰伦

    def test_empty_string(self):
        self.assertEqual(_norm_cn(""), "")
        self.assertEqual(_norm_cn(None), None)

    def test_mixed_text(self):
        # Traditional artist with simplified query should match after norm
        self.assertEqual(_norm_cn("\u5468\u6770\u502b - \u7a3b\u9999"), "\u5468\u6770\u4f26 - \u7a3b\u9999")


class TestAutoSelectPlatform(unittest.TestCase):

    def test_chinese_selects_bilibili(self):
        self.assertEqual(auto_select_platform("周杰伦 稻香"), "bilibili")
        self.assertEqual(auto_select_platform("稻香"), "bilibili")

    def test_english_selects_youtube(self):
        self.assertEqual(auto_select_platform("The Weeknd Blinding Lights"), "youtube")
        self.assertEqual(auto_select_platform("test"), "youtube")

    def test_mixed_selects_bilibili(self):
        # Any Chinese char triggers bilibili
        self.assertEqual(auto_select_platform("周杰伦 Greatest Hits"), "bilibili")


class TestIsSpotifyUrl(unittest.TestCase):

    def test_track_url(self):
        self.assertTrue(is_spotify_url("https://open.spotify.com/track/abc123"))

    def test_album_url(self):
        self.assertTrue(is_spotify_url("https://open.spotify.com/album/abc123"))

    def test_playlist_url(self):
        self.assertTrue(is_spotify_url("https://open.spotify.com/playlist/abc123"))

    def test_short_link(self):
        self.assertTrue(is_spotify_url("https://spotify.link/track/abc123"))

    def test_non_spotify_url(self):
        self.assertFalse(is_spotify_url("https://www.youtube.com/watch?v=abc"))
        self.assertFalse(is_spotify_url("https://music.163.com/song?id=123"))

    def test_plain_text(self):
        self.assertFalse(is_spotify_url("周杰伦 稻香"))


class TestIsNeteaseUrl(unittest.TestCase):

    def test_song_url(self):
        self.assertTrue(is_netease_url("https://music.163.com/song?id=185809"))

    def test_song_url_with_extra_params(self):
        self.assertTrue(is_netease_url("https://music.163.com/song?id=185809&userid=123"))

    def test_mobile_url(self):
        self.assertTrue(is_netease_url("https://y.music.126.com/n/song?ids=12345"))

    def test_non_netease_url(self):
        self.assertFalse(is_netease_url("https://open.spotify.com/track/abc"))
        self.assertFalse(is_netease_url("https://www.youtube.com/watch?v=abc"))

    def test_plain_text(self):
        self.assertFalse(is_netease_url("周杰伦 稻香"))


class TestExtractNeteaseSongId(unittest.TestCase):

    def test_extract_from_standard_url(self):
        self.assertEqual(extract_netease_song_id("https://music.163.com/song?id=185809"), "185809")

    def test_extract_with_extra_params(self):
        self.assertEqual(extract_netease_song_id("https://music.163.com/song?id=123&userid=456"), "123")

    def test_no_match(self):
        self.assertIsNone(extract_netease_song_id("https://www.youtube.com/watch?v=abc"))
        self.assertIsNone(extract_netease_song_id("not a url"))


class TestSanitizeFilename(unittest.TestCase):

    def test_strips_windows_forbidden(self):
        self.assertEqual(sanitize_filename('a<b>c:d"e/f\\g|h?i*j'), "abcdefghij")

    def test_collapses_whitespace(self):
        self.assertEqual(sanitize_filename("a   b\t c"), "a b c")

    def test_strips_edges(self):
        self.assertEqual(sanitize_filename("  hello  "), "hello")

    def test_empty(self):
        self.assertEqual(sanitize_filename(""), "")


class TestIsYoutubeUrl(unittest.TestCase):

    def test_watch_url(self):
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_short_url(self):
        self.assertTrue(is_youtube_url("https://youtu.be/dQw4w9WgXcQ"))

    def test_mobile_url(self):
        self.assertTrue(is_youtube_url("https://m.youtube.com/watch?v=abc123"))

    def test_non_youtube(self):
        self.assertFalse(is_youtube_url("https://soundcloud.com/artist/song"))
        self.assertFalse(is_youtube_url("not a url"))


class TestIsSoundcloudUrl(unittest.TestCase):

    def test_track_url(self):
        self.assertTrue(is_soundcloud_url("https://soundcloud.com/artist/song-title"))

    def test_www_prefix(self):
        self.assertTrue(is_soundcloud_url("https://www.soundcloud.com/artist/song"))

    def test_non_soundcloud(self):
        self.assertFalse(is_soundcloud_url("https://www.youtube.com/watch?v=abc"))


class TestIsBandcampUrl(unittest.TestCase):

    def test_track_url(self):
        self.assertTrue(is_bandcamp_url("https://artist.bandcamp.com/track/song-name"))

    def test_non_bandcamp(self):
        self.assertFalse(is_bandcamp_url("https://soundcloud.com/artist/song"))


class TestIsDirectDownloadUrl(unittest.TestCase):

    def test_youtube_is_direct(self):
        self.assertTrue(is_direct_download_url("https://youtu.be/abc123"))

    def test_soundcloud_is_direct(self):
        self.assertTrue(is_direct_download_url("https://soundcloud.com/a/b"))

    def test_bandcamp_is_direct(self):
        self.assertTrue(is_direct_download_url("https://a.bandcamp.com/track/b"))

    def test_spotify_is_not_direct(self):
        self.assertFalse(is_direct_download_url("https://open.spotify.com/track/abc"))

    def test_netease_is_not_direct(self):
        self.assertFalse(is_direct_download_url("https://music.163.com/song?id=123"))


class TestIsChinese(unittest.TestCase):

    def test_pure_chinese(self):
        self.assertTrue(is_chinese("周杰伦"))
        self.assertTrue(is_chinese("稻香"))

    def test_mixed_chinese_english(self):
        self.assertTrue(is_chinese("周杰伦 Blinding Lights"))

    def test_pure_english(self):
        self.assertFalse(is_chinese("The Weeknd"))
        self.assertFalse(is_chinese("test 123"))

    def test_empty(self):
        self.assertFalse(is_chinese(""))

    def test_punctuation_only(self):
        self.assertFalse(is_chinese("--- ..."))


if __name__ == "__main__":
    unittest.main(verbosity=2)

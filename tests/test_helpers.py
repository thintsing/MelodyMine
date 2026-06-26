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
import tempfile
import time
import unittest

# Make the scripts directory importable regardless of CWD.
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

from melodymine_common import (  # noqa: E402
    auto_select_platform,
    derive_query_from_filename,
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
    _auto_fmt_from_codec,
    _best_metadata_candidate,
    _clean_artist,
    _is_accompaniment,
    _list_audio_files,
    _norm_cn,
    _resolve_auto_fmt,
    _score_metadata_candidate,
    find_downloaded_file,
    parse_bili_title,
    parse_search_query,
    rank_bili_results,
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


class TestIsAccompaniment(unittest.TestCase):

    def test_chinese_accompaniment(self):
        self.assertTrue(_is_accompaniment("稻香 伴奏"))
        self.assertTrue(_is_accompaniment("稻香 纯音乐版"))
        self.assertTrue(_is_accompaniment("稻香 卡拉OK"))

    def test_english_accompaniment(self):
        self.assertTrue(_is_accompaniment("Dao Xiang Karaoke"))
        self.assertTrue(_is_accompaniment("Blinding Lights Instrumental"))
        self.assertTrue(_is_accompaniment("Song backing track"))
        self.assertTrue(_is_accompaniment("off vocal version"))

    def test_vocal_song(self):
        self.assertFalse(_is_accompaniment("周杰伦《稻香》完整版"))
        self.assertFalse(_is_accompaniment("The Weeknd - Blinding Lights Official MV"))

    def test_empty(self):
        self.assertFalse(_is_accompaniment(""))
        self.assertFalse(_is_accompaniment(None))


class TestRankBiliResults(unittest.TestCase):

    def _mk(self, title, plays=0):
        return {"bvid": "x", "aid": 1, "title": title, "duration": "3:00", "play": plays, "uploader": "u"}

    def test_vocal_ranked_before_accompaniment(self):
        results = [
            self._mk("稻香 伴奏"),
            self._mk("周杰伦《稻香》完整版"),
        ]
        ranked = rank_bili_results(results)
        self.assertEqual(ranked[0]["title"], "周杰伦《稻香》完整版")
        self.assertEqual(ranked[1]["title"], "稻香 伴奏")

    def test_all_vocal_unchanged_order(self):
        results = [self._mk("歌A"), self._mk("歌B")]
        self.assertEqual([r["title"] for r in rank_bili_results(results)], ["歌A", "歌B"])

    def test_all_accompaniment_unchanged_order(self):
        results = [self._mk("歌A 伴奏"), self._mk("歌B 纯音乐")]
        self.assertEqual([r["title"] for r in rank_bili_results(results)], ["歌A 伴奏", "歌B 纯音乐"])

    def test_does_not_mutate_input(self):
        results = [self._mk("伴奏"), self._mk("原曲")]
        original = list(results)
        rank_bili_results(results)
        self.assertEqual([r["title"] for r in results], [r["title"] for r in original])

    def test_empty(self):
        self.assertEqual(rank_bili_results([]), [])


class TestAutoFmtFromCodec(unittest.TestCase):
    """_auto_fmt_from_codec: lossless codec → flac, lossy → mp3 320K."""

    def test_flac_is_lossless(self):
        fmt, bitrate, _ = _auto_fmt_from_codec("flac")
        self.assertEqual(fmt, "flac")
        self.assertIsNone(bitrate)

    def test_alac_is_lossless(self):
        fmt, bitrate, _ = _auto_fmt_from_codec("alac")
        self.assertEqual(fmt, "flac")
        self.assertIsNone(bitrate)

    def test_pcm_is_lossless(self):
        fmt, bitrate, _ = _auto_fmt_from_codec("pcm_s16le")
        self.assertEqual(fmt, "flac")

    def test_aac_is_lossy(self):
        fmt, bitrate, _ = _auto_fmt_from_codec("mp4a.40.2")
        self.assertEqual(fmt, "mp3")
        self.assertEqual(bitrate, "320K")

    def test_opus_is_lossy(self):
        fmt, bitrate, _ = _auto_fmt_from_codec("opus")
        self.assertEqual(fmt, "mp3")
        self.assertEqual(bitrate, "320K")

    def test_unknown_codec_is_lossy(self):
        fmt, bitrate, _ = _auto_fmt_from_codec("someunknown")
        self.assertEqual(fmt, "mp3")
        self.assertEqual(bitrate, "320K")

    def test_empty_codec_is_lossy(self):
        fmt, bitrate, _ = _auto_fmt_from_codec("")
        self.assertEqual(fmt, "mp3")
        self.assertEqual(bitrate, "320K")

    def test_none_codec_is_lossy(self):
        fmt, bitrate, _ = _auto_fmt_from_codec(None)
        self.assertEqual(fmt, "mp3")
        self.assertEqual(bitrate, "320K")


class TestResolveAutoFmt(unittest.TestCase):
    """_resolve_auto_fmt: user bitrate override wins over auto-chosen."""

    def test_user_bitrate_overrides_lossless(self):
        # flac source, but user requests a bitrate → keep flac fmt, use user br
        fmt, bitrate, _ = _resolve_auto_fmt("flac", "1411K")
        self.assertEqual(fmt, "flac")
        self.assertEqual(bitrate, "1411K")

    def test_user_bitrate_overrides_lossy(self):
        fmt, bitrate, _ = _resolve_auto_fmt("opus", "128K")
        self.assertEqual(fmt, "mp3")
        self.assertEqual(bitrate, "128K")

    def test_no_user_bitrate_uses_auto_lossy(self):
        fmt, bitrate, _ = _resolve_auto_fmt("opus", None)
        self.assertEqual(fmt, "mp3")
        self.assertEqual(bitrate, "320K")

    def test_no_user_bitrate_uses_auto_lossless(self):
        fmt, bitrate, _ = _resolve_auto_fmt("flac", None)
        self.assertEqual(fmt, "flac")
        self.assertIsNone(bitrate)


class TestFindDownloadedFile(unittest.TestCase):
    """find_downloaded_file: snapshot-based detection avoids the yt-dlp mtime bug.

    yt-dlp sets each file's mtime to the source upload date, so a pre-existing
    file can have a newer mtime than the just-downloaded one. Passing ``before``
    (a snapshot taken before the download) must exclude pre-existing files so
    metadata is never written to the wrong file.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _touch(self, name, mtime=None):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(b"x")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_before_snapshot_excludes_pre_existing(self):
        # Pre-existing file with a FUTURE mtime (simulates yt-dlp upload-date).
        future = time.time() + 10 * 365 * 24 * 3600
        old = self._touch("old_upload_2025.flac", mtime=future)
        before = _list_audio_files(self.dir)
        # Download creates a new file whose mtime yt-dlp sets to an old date.
        past = time.time() - 365 * 24 * 3600
        new = self._touch("new_download.flac", mtime=past)
        self.assertEqual(find_downloaded_file(self.dir, before=before), new)
        self.assertNotEqual(find_downloaded_file(self.dir, before=before), old)

    def test_no_before_returns_newest_ctime(self):
        a = self._touch("a.mp3")
        time.sleep(0.01)
        b = self._touch("b.mp3")
        # Without a snapshot, the most recently created file wins.
        self.assertEqual(find_downloaded_file(self.dir), b)

    def test_before_with_no_new_files_returns_none(self):
        old = self._touch("old.mp3")
        before = _list_audio_files(self.dir)
        self.assertIsNone(find_downloaded_file(self.dir, before=before))

    def test_ignores_non_audio_files(self):
        before = _list_audio_files(self.dir)
        self._touch("notes.txt")
        self._touch("cover.jpg")
        self.assertIsNone(find_downloaded_file(self.dir, before=before))

    def test_nonexistent_dir_returns_none(self):
        self.assertIsNone(find_downloaded_file("/no/such/dir/xyz"))

    def test_empty_dir_returns_none(self):
        self.assertIsNone(find_downloaded_file(self.dir))


class TestDeriveQueryFromFilename(unittest.TestCase):
    """derive_query_from_filename: shared filename→query logic for meta commands."""

    def test_dash_separator_replaced(self):
        self.assertEqual(derive_query_from_filename("/music/Artist - Title.mp3"), "Artist Title")

    def test_cjk_dash_separator_replaced(self):
        # Full-width / em dash variants are treated as separators.
        self.assertEqual(derive_query_from_filename("周杰伦－稻香.flac"), "周杰伦 稻香")
        self.assertEqual(derive_query_from_filename("周杰伦—稻香.flac"), "周杰伦 稻香")

    def test_parenthetical_annotation_removed(self):
        self.assertEqual(derive_query_from_filename("Song (Live).mp3"), "Song")

    def test_bracket_annotation_removed(self):
        self.assertEqual(derive_query_from_filename("Song 【MV】.flac"), "Song")
        self.assertEqual(derive_query_from_filename("Song [Remaster].mp3"), "Song")

    def test_strips_directory(self):
        self.assertEqual(derive_query_from_filename("a/b/c.mp3"), "c")

    def test_plain_name(self):
        self.assertEqual(derive_query_from_filename("song.mp3"), "song")

    def test_extension_stripped(self):
        self.assertEqual(derive_query_from_filename("track.flac"), "track")


class TestScoreMetadataCandidate(unittest.TestCase):
    """_score_metadata_candidate: scores a metadata result against artist/title."""

    def _mk(self, artist="周杰伦", title="稻香", album="", cover="", pic_url=""):
        r = {"artist": artist, "title": title}
        if album:
            r["album"] = album
        if cover:
            r["cover"] = cover
        if pic_url:
            r["pic_url"] = pic_url
        return r

    # ── Exact match ──
    def test_exact_match_full_score(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦", "稻香"), "周杰伦", "稻香",
        )
        self.assertEqual(score, 25)  # 20 (artist exact) + 5 (title exact)

    def test_exact_match_english(self):
        score = _score_metadata_candidate(
            self._mk("The Weeknd", "Blinding Lights"), "The Weeknd", "Blinding Lights",
        )
        self.assertEqual(score, 25)

    # ── Partial matches ──
    def test_artist_contains(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦 & 蔡依林", "稻香"), "周杰伦", "稻香",
        )
        # artist contains: +8; title exact: +5
        self.assertEqual(score, 13)

    def test_title_contains(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦", "稻香 (Live)"), "周杰伦", "稻香",
        )
        # artist exact: +20; title partial: +2
        self.assertEqual(score, 22)

    def test_no_match(self):
        score = _score_metadata_candidate(
            self._mk("林俊杰", "江南"), "周杰伦", "稻香",
        )
        self.assertEqual(score, 0)

    # ── Collaboration aware (NetEase) ──
    def test_collab_exact_artist_reduced(self):
        # Comma-joined: exact artist match scores only 5 (not 20).
        score = _score_metadata_candidate(
            self._mk("周杰伦, 蔡依林", "稻香"), "周杰伦", "稻香",
            collaboration_aware=True,
        )
        self.assertEqual(score, 10)  # 5 (artist) + 5 (title)

    def test_collab_contains_raw_artist(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦, 蔡依林", "稻香"), "周杰伦", "稻香",
            collaboration_aware=True,
        )
        self.assertEqual(score, 10)

    def test_collab_artist_not_found(self):
        score = _score_metadata_candidate(
            self._mk("林俊杰, 蔡依林", "稻香"), "周杰伦", "稻香",
            collaboration_aware=True,
        )
        self.assertEqual(score, 5)  # only title exact

    # ── Bonus fields (iTunes) ──
    def test_bonus_cover_and_album(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦", "稻香", album="魔杰座", cover="https://example.com/c.jpg"),
            "周杰伦", "稻香", bonus_fields=True,
        )
        self.assertEqual(score, 30)  # 20 + 5 + 3 (cover) + 2 (album)

    def test_bonus_no_extras(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦", "稻香"), "周杰伦", "稻香", bonus_fields=True,
        )
        self.assertEqual(score, 25)

    # ── Edge cases ──
    def test_empty_fields(self):
        # Empty strings match via Python's "in" operator ("'' in any_string" is
        # always True), so an empty result against non-empty query still scores
        # a tiny match via the title-prefix branch (+2).
        score = _score_metadata_candidate(
            self._mk("", ""), "周杰伦", "稻香",
        )
        self.assertEqual(score, 2)

    def test_none_title_handled(self):
        r = {"artist": "周杰伦", "title": None}
        score = _score_metadata_candidate(r, "周杰伦", "稻香")
        # Artist exact: 20; title (None→""): "" in "稻香" is True → +2
        self.assertEqual(score, 22)


class TestBestMetadataCandidate(unittest.TestCase):
    """_best_metadata_candidate: picks the highest-scoring result."""

    def test_picks_highest(self):
        results = [
            {"artist": "林俊杰", "title": "江南", "album": ""},
            {"artist": "周杰伦", "title": "稻香", "album": "魔杰座"},
            {"artist": "周杰伦", "title": "稻香 (Live)", "album": ""},
        ]
        best_score, best_data = _best_metadata_candidate(results, "周杰伦", "稻香")
        self.assertEqual(best_data["artist"], "周杰伦")
        self.assertEqual(best_data["title"], "稻香")
        self.assertEqual(best_data["album"], "魔杰座")
        self.assertEqual(best_score, 25)

    def test_empty_returns_negative_one(self):
        score, data = _best_metadata_candidate([], "周杰伦", "稻香")
        self.assertEqual(score, -1)
        self.assertIsNone(data)

    def test_forwards_kwargs(self):
        results = [
            {"artist": "周杰伦, 蔡依林", "title": "稻香"},
            {"artist": "周杰伦", "title": "稻香", "album": "魔杰座"},
        ]
        # Without collab: the comma-separated artist would win via "contains" (+8)
        # because _clean_artist takes "周杰伦" from the split.
        score, data = _best_metadata_candidate(results, "周杰伦", "稻香",
                                                collaboration_aware=True)
        # collab_aware: first result gets 5+5=10, second gets 20+5=25
        self.assertEqual(data["artist"], "周杰伦")
        self.assertGreater(score, 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Unit tests for MelodyMine pure functions.

Run with:  python -m unittest tests.test_helpers -v
       or:  python tests/test_helpers.py

Uses only the standard library (unittest) — no pytest dependency.
Covers the pure functions most likely to break during refactors:
parse_search_query, parse_bili_title, _clean_artist, norm_cn,
auto_select_platform, is_spotify_url, sanitize_filename, is_chinese.
"""

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# Make the scripts directory importable regardless of CWD.
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import metadata  # noqa: E402  (for patching find_ffmpeg / subprocess.run)
import music_helper  # noqa: E402  (for patching _PLATFORM_HANDLERS)
from melodymine_common import (  # noqa: E402
    auto_select_platform,
    build_spotdl_proxy_args,
    check_version_compat,
    derive_query_from_filename,
    enable_utf8_stdio,
    extract_bilibili_bvid,
    extract_netease_song_id,
    is_accompaniment,
    is_bandcamp_url,
    is_bilibili_url,
    is_chinese,
    is_derivative,
    is_direct_download_url,
    is_netease_url,
    is_socks_proxy,
    is_soundcloud_url,
    is_spotify_url,
    is_youtube_url,
    make_subprocess_env,
    norm_cn,
    proxy_to_env,
    sanitize_filename,
    strip_version_tag,
    text_sim,
)
from metadata import (  # noqa: E402
    _best_metadata_candidate,
    _clean_artist,
    _score_metadata_candidate,
    find_downloaded_file,
    parse_bili_title,
    parse_search_query,
    rank_bili_results,
    rank_search_results,
)
from metadata import (
    list_audio_files as _list_audio_files,
)
from music_helper import (  # noqa: E402
    _auto_fmt_from_codec,
    _download_plan,
    _plain_http,
    _resolve_auto_fmt,
    _sniff_audio_ext,
    cmd_download,
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
        self.assertEqual(norm_cn("\u5468\u6770\u502b"), "\u5468\u6770\u4f26")  # 周杰倫→周杰伦
        # 學→学 is in the map; 張/友 are NOT
        self.assertEqual(norm_cn("\u5f35\u5b78\u53cb"), "\u5f35\u5b66\u53cb")  # 張學友→张学友
        # 劉/德/華 are all NOT in the map → unchanged
        self.assertEqual(norm_cn("\u5289\u5fb7\u83ef"), "\u5289\u5fb7\u83ef")  # 劉德華 unchanged

    def test_already_simplified_unchanged(self):
        self.assertEqual(norm_cn("\u5468\u6770\u4f26"), "\u5468\u6770\u4f26")  # 周杰伦

    def test_empty_string(self):
        self.assertEqual(norm_cn(""), "")
        self.assertEqual(norm_cn(None), None)

    def test_mixed_text(self):
        # Traditional artist with simplified query should match after norm
        self.assertEqual(norm_cn("\u5468\u6770\u502b - \u7a3b\u9999"), "\u5468\u6770\u4f26 - \u7a3b\u9999")


class TestTextSim(unittest.TestCase):
    """text_sim: script/punctuation-insensitive similarity used by the rankers."""

    def test_traditional_simplified_pair_scores_high(self):
        # 原來的我 vs 原来的我 — only 來 differs by script, so this must be ~1.0.
        self.assertGreaterEqual(text_sim("\u539f\u4f86\u7684\u6211", "\u539f\u6765\u7684\u6211"), 0.99)

    def test_punctuation_and_case_ignored(self):
        self.assertAlmostEqual(text_sim("Hello, World!", "hello world"), 1.0)

    def test_different_titles_score_low(self):
        self.assertLess(text_sim("\u7a97\u5916", "\u7a3b\u9999"), 0.5)  # 窗外 vs 稻香

    def test_empty_inputs(self):
        self.assertEqual(text_sim("", ""), 1.0)
        self.assertEqual(text_sim(None, "x"), 0.0)


class TestRankSearchResults(unittest.TestCase):
    """rank_search_results: originals first, accompaniment/cover/live demoted."""

    @staticmethod
    def _item(title, artist="Artist"):
        return {"title": title, "artist": artist, "music_id": "1"}

    def test_accompaniment_demoted_below_vocal(self):
        results = [self._item("\u9ed8 (\u4f34\u594f)"), self._item("\u9ed8")]  # 默 (伴奏), 默
        self.assertEqual(rank_search_results(results, "\u5f20\u6770 \u9ed8")[0]["title"], "\u9ed8")

    def test_cover_and_live_demoted(self):
        results = [
            self._item("\u9ed8 (Live)"),
            self._item("\u9ed8 (\u7ffb\u5531)"),  # 默 (翻唱)
            self._item("\u9ed8"),
        ]
        ranked = rank_search_results(results, "\u5f20\u6770 \u9ed8")
        self.assertEqual(ranked[0]["title"], "\u9ed8")
        self.assertEqual({r["title"] for r in ranked[1:]}, {"\u9ed8 (Live)", "\u9ed8 (\u7ffb\u5531)"})

    def test_version_tag_on_right_song_still_matches(self):
        # A live cut of the right song must not be dropped, only ranked lower.
        results = [self._item("\u9ed8 (Live)")]
        self.assertEqual(len(rank_search_results(results, "\u5f20\u6770 \u9ed8")), 1)

    def test_no_query_keeps_all_results(self):
        results = [self._item("\u9ed8 (\u4f34\u594f)"), self._item("\u9ed8")]
        self.assertEqual(len(rank_search_results(results, None)), 2)

    def test_empty_results(self):
        self.assertEqual(rank_search_results([], "\u9ed8"), [])


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


class TestIsBilibiliUrl(unittest.TestCase):

    def test_video_url(self):
        self.assertTrue(is_bilibili_url("https://www.bilibili.com/video/BV1TfN2emEZh"))

    def test_playlist_url_with_bvid_param(self):
        self.assertTrue(is_bilibili_url(
            "https://www.bilibili.com/list/ml1266054064?oid=113973030556081&bvid=BV1TfN2emEZh"))

    def test_short_link(self):
        self.assertTrue(is_bilibili_url("https://b23.tv/abcDEF"))

    def test_mobile_url(self):
        self.assertTrue(is_bilibili_url("https://m.bilibili.com/video/BV1xx411c7mD"))

    def test_non_bilibili(self):
        self.assertFalse(is_bilibili_url("https://youtu.be/abc123"))
        self.assertFalse(is_bilibili_url("周杰伦 稻香"))


class TestExtractBilibiliBvid(unittest.TestCase):

    def test_from_video_path(self):
        self.assertEqual(extract_bilibili_bvid(
            "https://www.bilibili.com/video/BV1TfN2emEZh"), "BV1TfN2emEZh")

    def test_from_query_param(self):
        self.assertEqual(extract_bilibili_bvid(
            "https://www.bilibili.com/list/ml1266054064?oid=113973030556081&bvid=BV1TfN2emEZh"),
            "BV1TfN2emEZh")

    def test_short_link_has_no_bvid(self):
        self.assertIsNone(extract_bilibili_bvid("https://b23.tv/abcDEF"))

    def test_plain_query(self):
        self.assertIsNone(extract_bilibili_bvid("周杰伦 稻香"))

    def test_truncated_id_not_matched(self):
        self.assertIsNone(extract_bilibili_bvid("https://www.bilibili.com/video/BV1Tf"))


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

    def test_bilibili_is_not_direct(self):
        # Bilibili needs its own UA + API fallback chain, so it routes separately.
        self.assertFalse(is_direct_download_url("https://www.bilibili.com/video/BV1TfN2emEZh"))


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
        self.assertTrue(is_accompaniment("稻香 伴奏"))
        self.assertTrue(is_accompaniment("稻香 纯音乐版"))
        self.assertTrue(is_accompaniment("稻香 卡拉OK"))

    def test_english_accompaniment(self):
        self.assertTrue(is_accompaniment("Dao Xiang Karaoke"))
        self.assertTrue(is_accompaniment("Blinding Lights Instrumental"))
        self.assertTrue(is_accompaniment("Song backing track"))
        self.assertTrue(is_accompaniment("off vocal version"))

    def test_vocal_song(self):
        self.assertFalse(is_accompaniment("周杰伦《稻香》完整版"))
        self.assertFalse(is_accompaniment("The Weeknd - Blinding Lights Official MV"))

    def test_empty(self):
        self.assertFalse(is_accompaniment(""))
        self.assertFalse(is_accompaniment(None))


class TestIsDerivative(unittest.TestCase):
    """is_derivative: not the studio original."""

    def test_live_and_concert(self):
        self.assertTrue(is_derivative("默 (Live)"))
        self.assertTrue(is_derivative("默 (歌手2017现场版)"))
        self.assertTrue(is_derivative("2025未LIVE巡回演唱会金华站"))

    def test_cover(self):
        self.assertTrue(is_derivative("你不要担心 (翻唱)"))
        self.assertTrue(is_derivative("Song (Cover by Someone)"))

    def test_remix_and_edit(self):
        self.assertTrue(is_derivative("Song (DJ 慢摇版)"))
        self.assertTrue(is_derivative("Song (Sped Up)"))
        self.assertTrue(is_derivative("Song (Remix)"))

    def test_fragment(self):
        self.assertTrue(is_derivative("默 (57秒Live片段)"))
        self.assertTrue(is_derivative("默 (Live片段)"))

    def test_studio_original(self):
        self.assertFalse(is_derivative("稻香"))
        self.assertFalse(is_derivative("The Weeknd - Blinding Lights"))
        self.assertFalse(is_derivative(""))
        self.assertFalse(is_derivative(None))


class TestStripVersionTag(unittest.TestCase):
    """strip_version_tag: version annotations are not song identity."""

    def test_live_suffix(self):
        self.assertEqual(strip_version_tag("默 (Live)"), "默")

    def test_cjk_brackets(self):
        self.assertEqual(strip_version_tag("默（现场版）"), "默")
        self.assertEqual(strip_version_tag("默【Live】"), "默")

    def test_repeated_suffixes(self):
        self.assertEqual(strip_version_tag("默 (Live) (Remaster)"), "默")

    def test_no_suffix(self):
        self.assertEqual(strip_version_tag("稻香"), "稻香")

    def test_only_strips_trailing(self):
        self.assertEqual(strip_version_tag("(Live) 默"), "(Live) 默")

    def test_empty(self):
        self.assertEqual(strip_version_tag(""), "")
        self.assertEqual(strip_version_tag(None), "")


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
        self._touch("a.mp3")
        time.sleep(0.01)
        b = self._touch("b.mp3")
        # Without a snapshot, the most recently created file wins.
        self.assertEqual(find_downloaded_file(self.dir), b)

    def test_before_with_no_new_files_returns_none(self):
        self._touch("old.mp3")
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

    # ── Empty query guard (regression: "" in "anything" is True) ──
    def test_empty_artist_in_query_returns_zero(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦", "稻香"), "", "稻香",
        )
        self.assertEqual(score, 0)

    def test_empty_title_in_query_returns_zero(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦", "稻香"), "周杰伦", "",
        )
        self.assertEqual(score, 0)

    def test_both_empty_in_query_returns_zero(self):
        score = _score_metadata_candidate(
            self._mk("周杰伦", "稻香"), "", "",
        )
        self.assertEqual(score, 0)


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


# ═════════════════════════════════════════════════════════════════════════
#  melodymine_common pure-function tests (check_version_compat,
#  build_spotdl_proxy_args, proxy_to_env, is_socks_proxy,
#  make_subprocess_env)
# ═════════════════════════════════════════════════════════════════════════


class TestCheckVersionCompat(unittest.TestCase):
    """check_version_compat: version-to-matrix comparisons."""

    def test_exact_tested_version_ok(self):
        status, msg = check_version_compat("yt_dlp", "2026.06.09")
        self.assertEqual(status, "ok")
        self.assertEqual(msg, "")

    def test_above_min_but_untested_warns(self):
        status, msg = check_version_compat("yt_dlp", "2026.6.10")
        self.assertEqual(status, "warn")
        self.assertIn("tested", msg)

    def test_below_min_for_ytdlp(self):
        status, msg = check_version_compat("yt_dlp", "2024.1.1")
        self.assertEqual(status, "warn")  # severity is "warn" for yt-dlp
        self.assertIn("below minimum", msg)

    def test_spotdl_above_max_major_errors(self):
        status, msg = check_version_compat("spotdl", "5.0.0")
        self.assertEqual(status, "error")
        self.assertIn("above major", msg)

    def test_spotdl_below_min_errors(self):
        status, msg = check_version_compat("spotdl", "4.0.0")
        self.assertEqual(status, "error")
        self.assertIn("below minimum", msg)

    def test_spotdl_ok_version(self):
        status, msg = check_version_compat("spotdl", "4.5.0")
        self.assertEqual(status, "ok")
        self.assertEqual(msg, "")

    def test_unknown_module_ok(self):
        status, msg = check_version_compat("nonexistent", "1.0")
        self.assertEqual(status, "ok")
        self.assertEqual(msg, "")

    def test_none_version_ok(self):
        status, msg = check_version_compat("yt_dlp", None)
        self.assertEqual(status, "ok")
        self.assertEqual(msg, "")

    def test_prerelease_suffix(self):
        # "2026.12.01-alpha" should parse as (2026, 12, 1)
        status, _ = check_version_compat("yt_dlp", "2026.12.01-alpha")
        self.assertIn(status, ("ok", "warn"))
        self.assertNotEqual(status, "error")


class TestBuildSpotdlProxyArgs(unittest.TestCase):
    """build_spotdl_proxy_args: maps proxy to spotdl CLI tokens."""

    def test_no_proxy_returns_empty(self):
        self.assertEqual(build_spotdl_proxy_args(None), [])
        self.assertEqual(build_spotdl_proxy_args(""), [])

    def test_http_proxy_passed_directly(self):
        self.assertEqual(
            build_spotdl_proxy_args("http://127.0.0.1:8888"),
            ["--proxy", "http://127.0.0.1:8888"],
        )

    def test_socks5_wraps_in_ytdlp_args(self):
        self.assertEqual(
            build_spotdl_proxy_args("socks5://127.0.0.1:1080"),
            ["--yt-dlp-args", "--proxy socks5://127.0.0.1:1080"],
        )

    def test_socks5h_wraps_in_ytdlp_args(self):
        self.assertEqual(
            build_spotdl_proxy_args("socks5h://127.0.0.1:1080"),
            ["--yt-dlp-args", "--proxy socks5h://127.0.0.1:1080"],
        )


class TestProxyToEnv(unittest.TestCase):
    """proxy_to_env: maps proxy URL to env dict for requests."""

    def test_http_proxy(self):
        env = proxy_to_env("http://proxy:8080")
        self.assertEqual(env, {"HTTP_PROXY": "http://proxy:8080", "HTTPS_PROXY": "http://proxy:8080"})

    def test_socks5_proxy(self):
        env = proxy_to_env("socks5://proxy:1080")
        self.assertEqual(env, {"ALL_PROXY": "socks5://proxy:1080"})

    def test_https_proxy(self):
        env = proxy_to_env("https://proxy:443")
        self.assertEqual(list(env.keys()), ["HTTP_PROXY", "HTTPS_PROXY"])


class TestIsSocksProxy(unittest.TestCase):
    """is_socks_proxy: detects SOCKS proxy schemes."""

    def test_socks5(self):
        self.assertTrue(is_socks_proxy("socks5://host:port"))

    def test_socks5h(self):
        self.assertTrue(is_socks_proxy("socks5h://host:port"))

    def test_socks4(self):
        self.assertTrue(is_socks_proxy("socks4://host:port"))

    def test_http_is_not_socks(self):
        self.assertFalse(is_socks_proxy("http://host:port"))
        self.assertFalse(is_socks_proxy("https://host:port"))

    def test_empty_is_not_socks(self):
        self.assertFalse(is_socks_proxy(""))
        self.assertFalse(is_socks_proxy(None))


class TestMakeSubprocessEnv(unittest.TestCase):
    """make_subprocess_env: returns os.environ with PYTHONIOENCODING set."""

    def test_has_utf8_encoding(self):
        env = make_subprocess_env()
        self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")

    def test_does_not_mutate_original(self):
        original_encoding = os.environ.get("PYTHONIOENCODING")
        env = make_subprocess_env()
        env["PYTHONIOENCODING"] = "corrupted"
        # Original os.environ should be untouched.
        self.assertEqual(os.environ.get("PYTHONIOENCODING"), original_encoding)

    def test_includes_existing_keys(self):
        env = make_subprocess_env()
        self.assertIn("PATH", env)
        self.assertIn("SYSTEMROOT" if os.name == "nt" else "HOME", env)


class TestEnableUtf8Stdio(unittest.TestCase):
    """enable_utf8_stdio: a GBK console must not be able to crash a run."""

    def _with_gbk_streams(self):
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")
        sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")

    def test_switches_gbk_stream_to_utf8(self):
        saved_out, saved_err = sys.stdout, sys.stderr
        try:
            self._with_gbk_streams()
            enable_utf8_stdio()
            self.assertEqual(sys.stdout.encoding.lower(), "utf-8")
            self.assertEqual(sys.stdout.errors, "replace")
            self.assertEqual(sys.stderr.encoding.lower(), "utf-8")
            # Korean text is outside GBK — this used to raise mid-download.
            sys.stdout.write("你不要担心 (김범수)")
        finally:
            sys.stdout, sys.stderr = saved_out, saved_err

    def test_idempotent(self):
        saved = sys.stdout
        try:
            sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            enable_utf8_stdio()
            enable_utf8_stdio()
            self.assertEqual(sys.stdout.encoding.lower(), "utf-8")
        finally:
            sys.stdout = saved

    def test_tolerates_stream_without_reconfigure(self):
        class NoReconfigure:
            encoding = "ascii"
            errors = "strict"

        saved = sys.stdout
        try:
            sys.stdout = NoReconfigure()
            enable_utf8_stdio()
        finally:
            sys.stdout = saved


class TestDownloadPlanBilibiliUrl(unittest.TestCase):
    """_download_plan: a pasted Bilibili URL must target that exact video."""

    URL = ("https://www.bilibili.com/list/ml1266054064"
           "?oid=113973030556081&bvid=BV1TfN2emEZh")

    @staticmethod
    def _cmd(plan):
        return " ".join(str(part) for part in plan["command"])

    def test_platform_is_bilibili(self):
        plan = _download_plan(self.URL)
        self.assertEqual(plan["platform"], "bilibili")
        self.assertEqual(plan["engine"], "yt-dlp")

    def test_command_targets_bvid_not_a_search(self):
        cmd = self._cmd(_download_plan(self.URL))
        self.assertIn("https://www.bilibili.com/video/BV1TfN2emEZh", cmd)
        self.assertNotIn("ytsearch", cmd)

    def test_notes_explain_the_skipped_search(self):
        plan = _download_plan(self.URL)
        self.assertTrue(any("no search step" in n for n in plan["notes"]))

    def test_explicit_platform_flag_agrees(self):
        self.assertEqual(_download_plan(self.URL, platform="bilibili")["platform"], "bilibili")

    def test_short_link_passed_through_for_redirect(self):
        cmd = self._cmd(_download_plan("https://b23.tv/abcDEF"))
        self.assertIn("https://b23.tv/abcDEF", cmd)

    def test_plain_chinese_query_still_searches(self):
        plan = _download_plan("周杰伦 稻香")
        self.assertEqual(plan["platform"], "bilibili")
        self.assertIn("<bvid>", self._cmd(plan))

    def test_plain_english_query_still_searches(self):
        plan = _download_plan("The Weeknd Blinding Lights")
        self.assertEqual(plan["platform"], "youtube")
        self.assertIn("ytsearch:", self._cmd(plan))


class TestBilibiliUrlRouting(unittest.TestCase):
    """cmd_download: a pasted Bilibili link must skip search and Soulseek."""

    URL = ("https://www.bilibili.com/list/ml1266054064"
           "?oid=113973030556081&bvid=BV1TfN2emEZh")

    def _call(self, platform):
        mock_bili = MagicMock(return_value={"ok": True, "platform": "bilibili"})
        with tempfile.TemporaryDirectory() as tmp:
            with patch("music_helper.ensure_deps", return_value=("python", "1.0", None)), \
                 patch("music_helper._download_bilibili", mock_bili):
                cmd_download(self.URL, platform=platform, output=tmp)
        return mock_bili

    def test_auto_mode_passes_the_url_through(self):
        mock_bili = self._call("auto")
        self.assertTrue(mock_bili.called)
        self.assertEqual(mock_bili.call_args.kwargs.get("bili_url"), self.URL)

    def test_explicit_bilibili_platform_is_also_direct(self):
        self.assertEqual(self._call("bilibili").call_args.kwargs.get("bili_url"), self.URL)

    def test_unrelated_platform_flag_is_respected(self):
        # _PLATFORM_HANDLERS binds the functions at import time, so patch the
        # dict entry rather than the module attribute.
        mock_kuwo = MagicMock(return_value={"ok": True})
        handlers = dict(music_helper._PLATFORM_HANDLERS)
        handlers["kuwo"] = mock_kuwo
        with tempfile.TemporaryDirectory() as tmp:
            with patch("music_helper.ensure_deps", return_value=("python", "1.0", None)), \
                 patch("music_helper._download_bilibili") as mock_bili, \
                 patch("music_helper._PLATFORM_HANDLERS", handlers):
                cmd_download(self.URL, platform="kuwo", output=tmp)
        self.assertFalse(mock_bili.called)
        self.assertTrue(mock_kuwo.called)


class TestPlainHttp(unittest.TestCase):
    """_plain_http: Kugou's CDN cert does not cover the download host."""

    def test_downgrades_https(self):
        self.assertEqual(
            _plain_http("https://fs.kugou.com/a.flac?k=1"),
            "http://fs.kugou.com/a.flac?k=1",
        )

    def test_leaves_http_alone(self):
        self.assertEqual(_plain_http("http://fs.kugou.com/a.flac"), "http://fs.kugou.com/a.flac")

    def test_only_first_scheme_replaced(self):
        # A signed URL may carry another URL in its query string.
        self.assertEqual(
            _plain_http("https://a.com/?u=https://b.com"),
            "http://a.com/?u=https://b.com",
        )

    def test_none_passthrough(self):
        self.assertIsNone(_plain_http(None))


class TestSniffAudioExt(unittest.TestCase):
    """_sniff_audio_ext: the container cannot be inferred from the request."""

    def _write(self, data):
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".part")
        f.write(data)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_flac(self):
        self.assertEqual(_sniff_audio_ext(self._write(b"fLaC\x00\x00\x00")), "flac")

    def test_id3_mp3(self):
        self.assertEqual(_sniff_audio_ext(self._write(b"ID3\x04\x00\x00\x00")), "mp3")

    def test_frame_sync_mp3(self):
        self.assertEqual(_sniff_audio_ext(self._write(b"\xff\xfb\x90\x00")), "mp3")

    def test_ogg(self):
        self.assertEqual(_sniff_audio_ext(self._write(b"OggS\x00\x02")), "ogg")

    def test_m4a_ftyp_at_offset_four(self):
        self.assertEqual(_sniff_audio_ext(self._write(b"\x00\x00\x00\x20ftypM4A ")), "m4a")

    def test_unknown_bytes(self):
        self.assertIsNone(_sniff_audio_ext(self._write(b"<html>nope</html>")))

    def test_missing_file(self):
        self.assertIsNone(_sniff_audio_ext(os.path.join(tempfile.gettempdir(), "nope.part")))


class TestDownloadPlanKugou(unittest.TestCase):
    """_download_plan: --platform kugou uses the API path, not yt-dlp."""

    def test_engine_and_platform(self):
        plan = _download_plan("周杰伦 稻香", platform="kugou")
        self.assertEqual(plan["platform"], "kugou")
        self.assertEqual(plan["engine"], "kugou-api-direct")

    def test_command_names_the_client(self):
        self.assertIn("kugou_client.search", _download_plan("稻香", platform="kugou")["command"])


class TestDownloadKugou(unittest.TestCase):
    """_download_kugou failure paths (no network)."""

    @staticmethod
    def _call(results, url="http://fs.kugou.com/a.flac"):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("music_helper.kugou_client.search", return_value=results), \
                 patch("music_helper.kugou_client.get_download_url", return_value=url), \
                 patch("urllib.request.urlopen") as mock_open:
                mock_open.side_effect = Exception("network down")
                return music_helper._download_kugou(
                    "python", "稻香", tmp, "flac", None, None, 1, False,
                    True, None, [], None, None, False,
                )

    RESULT = {"title": "稻香", "artist": "周杰伦", "album": "魔杰座",
              "hash": "8909E1809908CD8E3BF6CF85D98B93F0", "duration": 223}

    def test_no_search_results(self):
        out = self._call([])
        self.assertFalse(out["ok"])
        self.assertEqual(out["platform"], "kugou")
        self.assertIn("no results", out["error"])

    def test_unresolvable_download_url(self):
        out = self._call([self.RESULT], url=None)
        self.assertFalse(out["ok"])
        self.assertIn("URL resolution failed", out["error"])

    def test_network_error_reported(self):
        out = self._call([self.RESULT])
        self.assertFalse(out["ok"])
        self.assertIn("network down", out["error"])


class TestDownloadAudius(unittest.TestCase):
    """_download_audius failure paths (no network), plus CLI registration."""

    @staticmethod
    def _call(results, url="https://api.audius.co/v1/tracks/abc/stream"):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("music_helper.audius_client.search", return_value=results), \
                 patch("music_helper.audius_client.get_stream_url", return_value=url), \
                 patch("urllib.request.urlopen") as mock_open:
                mock_open.side_effect = Exception("network down")
                return music_helper._download_audius(
                    "python", "strobe", tmp, "mp3", None, None, 1, False,
                    True, None, [], None, None, False,
                )

    RESULT = {"title": "Strobe", "artist": "deadmau5",
              "track_id": "7YmNr", "duration": 61}

    def test_no_search_results(self):
        out = self._call([])
        self.assertFalse(out["ok"])
        self.assertEqual(out["platform"], "audius")
        self.assertIn("no results", out["error"])

    def test_unresolvable_stream_url(self):
        out = self._call([self.RESULT], url=None)
        self.assertFalse(out["ok"])
        self.assertIn("URL resolution failed", out["error"])

    def test_network_error_reported(self):
        out = self._call([self.RESULT])
        self.assertFalse(out["ok"])
        self.assertIn("network down", out["error"])

    def test_registered_in_dispatch_table(self):
        # SKILL.md advertises --platform audius; argparse must actually accept it.
        self.assertIs(music_helper._PLATFORM_HANDLERS["audius"],
                      music_helper._download_audius)

    def test_dry_run_plan(self):
        plan = _download_plan("strobe", platform="audius")
        self.assertEqual(plan["platform"], "audius")
        self.assertEqual(plan["engine"], "audius-api-direct")
        self.assertIn("audius_client.search", plan["command"])

    def test_catalog_id_key(self):
        self.assertEqual(music_helper._CATALOG_ID_KEY["audius"], "track_id")

class TestReadAudioTags(unittest.TestCase):
    """read_audio_tags: parse `ffmpeg -f ffmetadata` output."""

    FFMETA = ";FFMETADATA1\nalbum=爱情宣言\ntitle=原来的我\nartist=齐秦\nencoder=Lavf61\n"

    def _run(self, stdout, returncode=0, ffmpeg="ffmpeg"):
        with patch("metadata.find_ffmpeg", return_value=ffmpeg), \
             patch("metadata.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=stdout, returncode=returncode)
            return metadata.read_audio_tags("song.mp3", python="py")

    def test_reads_artist_and_title(self):
        self.assertEqual(self._run(self.FFMETA), ("齐秦", "原来的我"))

    def test_skips_header_and_unknown_keys(self):
        self.assertEqual(self._run(";FFMETADATA1\ntitle=稻香\n"), (None, "稻香"))

    def test_first_value_wins_on_duplicate_keys(self):
        out = ";FFMETADATA1\nartist=齐秦\nartist=Someone Else\ntitle=原来的我\n"
        self.assertEqual(self._run(out)[0], "齐秦")

    def test_empty_value_is_none(self):
        self.assertEqual(self._run(";FFMETADATA1\nartist=\ntitle=\n"), (None, None))

    def test_no_ffmpeg(self):
        self.assertEqual(self._run(self.FFMETA, ffmpeg=None), (None, None))

    def test_nonzero_exit(self):
        self.assertEqual(self._run("", returncode=1), (None, None))

    def test_subprocess_exception_does_not_raise(self):
        with patch("metadata.find_ffmpeg", return_value="ffmpeg"), \
             patch("metadata.subprocess.run", side_effect=OSError("boom")):
            self.assertEqual(metadata.read_audio_tags("song.mp3"), (None, None))


class TestIterAudioFiles(unittest.TestCase):
    """_iter_audio_files: recursive, audio only, stable order."""

    def test_finds_nested_audio_and_ignores_lrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "Album")
            os.makedirs(sub)
            for name in (os.path.join(tmp, "b.flac"), os.path.join(tmp, "a.mp3"),
                         os.path.join(tmp, "a.lrc"), os.path.join(tmp, "cover.jpg"),
                         os.path.join(sub, "c.m4a")):
                with open(name, "wb") as f:
                    f.write(b"x")
            found = [os.path.basename(p) for p in music_helper._iter_audio_files(tmp)]
        self.assertEqual(found, ["a.mp3", "b.flac", "c.m4a"])

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list(music_helper._iter_audio_files(tmp)), [])


class TestLyricsTarget(unittest.TestCase):
    """_lyrics_target: tags win, filename is the fallback."""

    def test_tags_used_as_is(self):
        self.assertEqual(
            music_helper._lyrics_target("齐秦", "原来的我", "01 Untagged.mp3"),
            ("齐秦", "原来的我"),
        )

    def test_filename_fills_missing_title(self):
        self.assertEqual(
            music_helper._lyrics_target(None, None, "王杰 - 一场游戏一场梦.mp3"),
            ("王杰", "一场游戏一场梦"),
        )

    def test_artist_only_still_falls_back(self):
        artist, title = music_helper._lyrics_target("王杰", None, "王杰 - 一场游戏一场梦.mp3")
        self.assertEqual(title, "一场游戏一场梦")

    def test_unusable_filename(self):
        self.assertEqual(music_helper._lyrics_target(None, None, "01.mp3"), (None, None))


class TestProbeDuration(unittest.TestCase):
    """_probe_duration: parse ffmpeg's stderr header."""

    STDERR = ("Input #0, mp3, from 'song.mp3':\n  Duration: 00:05:09.58, "
              "start: 0.025, bitrate: 128 kb/s\n    Stream #0:0: Audio: mp3\n")

    def _run(self, stderr, ffmpeg="ffmpeg", exc=None):
        with patch("music_helper.subprocess.run") as mock_run:
            if exc:
                mock_run.side_effect = exc
            else:
                mock_run.return_value = MagicMock(stderr=stderr, returncode=1)
            return music_helper._probe_duration(ffmpeg, "song.mp3")

    def test_parses_duration(self):
        self.assertAlmostEqual(self._run(self.STDERR), 309.58, places=2)

    def test_hours_component(self):
        self.assertAlmostEqual(self._run("  Duration: 01:02:03.50\n"), 3723.5, places=2)

    def test_no_duration_line(self):
        self.assertIsNone(self._run("Input #0: garbage\n"))

    def test_no_ffmpeg(self):
        self.assertIsNone(self._run(self.STDERR, ffmpeg=None))

    def test_subprocess_failure(self):
        self.assertIsNone(self._run(self.STDERR, exc=OSError("boom")))


class TestPreviewClipError(unittest.TestCase):
    """_preview_clip_error: VIP tracks resolve to ~11s clips, not songs."""

    def _run(self, actual, expected=223):
        with patch("music_helper._probe_duration", return_value=actual):
            return music_helper._preview_clip_error("ffmpeg", "song.mp3", expected)

    def test_full_length_passes(self):
        self.assertIsNone(self._run(222.9))

    def test_clip_is_rejected(self):
        err = self._run(11.31)
        self.assertIn("preview clip", err)
        self.assertIn("11s of 223s", err)

    def test_half_length_is_the_threshold(self):
        self.assertIsNone(self._run(111.5))
        self.assertIsNotNone(self._run(111.4))

    def test_unknown_expected_duration_is_not_checked(self):
        with patch("music_helper._probe_duration") as mock_probe:
            self.assertIsNone(music_helper._preview_clip_error("ffmpeg", "s.mp3", 0))
        self.assertFalse(mock_probe.called)

    def test_unreadable_duration_passes(self):
        self.assertIsNone(self._run(None))


class TestCmdLyricsSync(unittest.TestCase):
    """cmd_lyrics_sync: writes only sibling .lrc files, never touches audio."""

    LYRICS = {"synced_lyrics": "[00:01.00]line", "plain_lyrics": "line"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.song = os.path.join(self.tmp, "王杰 - 一场游戏一场梦.mp3")
        with open(self.song, "wb") as f:
            f.write(b"audio-bytes")
        patches = [
            patch("music_helper.find_ffmpeg", return_value="ffmpeg"),
            patch("music_helper._read_audio_tags", return_value=("王杰", "一场游戏一场梦")),
            patch("music_helper.lyrics_client.get_lyrics", return_value=self.LYRICS),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _lrc(self):
        return os.path.splitext(self.song)[0] + ".lrc"

    def test_writes_matching_lrc_and_leaves_audio_alone(self):
        result = music_helper.cmd_lyrics_sync(self.tmp)
        self.assertEqual(result["written"], 1)
        self.assertTrue(os.path.isfile(self._lrc()))
        self.assertEqual(os.path.basename(self._lrc()), "王杰 - 一场游戏一场梦.lrc")
        with open(self.song, "rb") as f:
            self.assertEqual(f.read(), b"audio-bytes")

    def test_second_run_is_a_no_op(self):
        music_helper.cmd_lyrics_sync(self.tmp)
        result = music_helper.cmd_lyrics_sync(self.tmp)
        self.assertEqual(result["written"], 0)
        self.assertEqual(result["existing"], 1)

    def test_overwrite_refetches(self):
        music_helper.cmd_lyrics_sync(self.tmp)
        result = music_helper.cmd_lyrics_sync(self.tmp, overwrite=True)
        self.assertEqual(result["written"], 1)

    def test_dry_run_writes_nothing(self):
        result = music_helper.cmd_lyrics_sync(self.tmp, dry_run=True)
        self.assertEqual(result["written"], 1)
        self.assertFalse(os.path.exists(self._lrc()))

    def test_no_lyrics_found_is_reported(self):
        with patch("music_helper.lyrics_client.get_lyrics", return_value=None):
            result = music_helper.cmd_lyrics_sync(self.tmp)
        self.assertEqual(result["not_found"], 1)
        self.assertFalse(os.path.exists(self._lrc()))

    def test_untitled_file_is_skipped(self):
        with patch("music_helper._read_audio_tags", return_value=(None, None)), \
             patch("music_helper.derive_query_from_filename", return_value=""):
            result = music_helper.cmd_lyrics_sync(self.tmp)
        self.assertEqual(result["no_title"], 1)

    def test_missing_directory(self):
        result = music_helper.cmd_lyrics_sync(os.path.join(self.tmp, "nope"))
        self.assertFalse(result["ok"])
        self.assertIn("Not a directory", result["error"])

    def test_limit_caps_the_scan(self):
        for i in range(3):
            with open(os.path.join(self.tmp, f"extra{i}.flac"), "wb") as f:
                f.write(b"x")
        result = music_helper.cmd_lyrics_sync(self.tmp, limit=2)
        self.assertEqual(result["scanned"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

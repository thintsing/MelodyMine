#!/usr/bin/env python3
"""Unit tests for the Bilibili audiobook pipeline helpers.

The point of these tests is the one thing that is easy to break silently: the
downloader and the verifier derive file names independently, so if their naming
logic ever diverges every file shows up as MISSING and the transfer is refused.
Run with:  python -m unittest tests.test_bili_album -v
"""

import os
import sys
import unittest

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import bili_album_dl as dl
import bili_album_verify as vf
import douban_cover as db


class PartNaming(unittest.TestCase):
    def test_clean_strips_broadcast_date_prefix(self):
        for raw in ("20220621 第一章", "2022-07-20 第一章", "2022-07-20、第一章"):
            self.assertEqual(dl.clean_part(raw), "第一章", raw)
        self.assertEqual(dl.clean_part("第一章 认知革命"), "第一章 认知革命")

    def test_downloader_and_verifier_agree(self):
        cases = [
            ("20220621 第一章 水的故事", {"clean": True, "strip_seq": False, "strip_regex": ""}),
            ("001第三章：光的魔法", {"clean": False, "strip_seq": True, "strip_regex": ""}),
            ("完整版：第一部分：认知革命",
             {"clean": False, "strip_seq": False, "strip_regex": r"^完整版："}),
            ("无选项标题", {}),
        ]
        for part, options in cases:
            self.assertEqual(dl.part_title(part, options), vf.part_title(part, options), part)

    def test_strip_regex_and_seq_compose(self):
        options = {"clean": True, "strip_seq": True, "strip_regex": r"^\s*第.章："}
        self.assertEqual(dl.part_title("2022-07-20 007第三章：记忆过载", options), "记忆过载")

    def test_safe_replaces_illegal_characters(self):
        self.assertEqual(dl.safe('a<b>c:d"e|f?g*h\\i'), "a b c d e f g h i")
        self.assertEqual(dl.safe("  spaced. "), "spaced")
        self.assertEqual(len(dl.safe("x" * 300)), 120)


class TagReading(unittest.TestCase):
    def test_tag_get_returns_first_value(self):
        tags = {"trkn": [(3, 14)]}
        self.assertEqual(vf.tag_get(tags, "trkn"), (3, 14))
        self.assertIsNone(vf.tag_get(tags, "\xa9nam"))
        self.assertIsNone(vf.tag_get({}, "\xa9nam"))

    def test_tag_dec_passes_through_str(self):
        self.assertEqual(vf.tag_dec("樊登"), "樊登")
        self.assertEqual(vf.tag_dec(b"\xe5\x90\x93"), "\u5413")


class DoubanCoverParsing(unittest.TestCase):
    def _jpeg(self, width, height):
        sof = (b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
               + height.to_bytes(2, "big") + width.to_bytes(2, "big"))
        return b"\xff\xd8\xff\xe0\x00\x02\x00\x00" + sof + bytes(16)

    def test_jpeg_dims_reads_sof(self):
        self.assertEqual(db.jpeg_dims(self._jpeg(1080, 1554)), (1080, 1554))

    def test_jpeg_dims_rejects_non_jpeg(self):
        self.assertIsNone(db.jpeg_dims(b"<html>blocked</html>"))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit tests for the yt-dlp post-download guard in music_helper._ytdlp_download.

Regression coverage for a confirmed false-positive: yt-dlp can exit 0 without
downloading anything (e.g. YouTube bot-check silently skipping items,
"Downloading 0 items of 1"), and _ytdlp_download used to report success with
no file on disk. The guard now verifies a new audio file actually landed,
with an exception for yt-dlp's "has already been downloaded" skip message.

Run with:  python -m unittest tests.test_ytdlp_download_guard -v
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

# Make the scripts directory importable regardless of CWD.
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))

import music_helper  # noqa: E402


def _build_fake_run_streaming(rc=0, lines=(), write_file=None):
    """Build a fake run_streaming that never spawns a subprocess.

    ``lines`` are appended to lines_capture when provided; ``write_file``
    is created in the output dir parsed from the ``-o`` template in ``cmd``.
    """

    def _fake(cmd, env=None, lines_capture=None):
        if lines_capture is not None:
            for ln in lines:
                lines_capture.append(ln)
        if write_file:
            out_dir = os.path.dirname(cmd[cmd.index("-o") + 1])
            with open(os.path.join(out_dir, write_file), "wb") as f:
                f.write(b"fake audio")
        return rc

    return _fake


class TestYtdlpDownloadGuard(unittest.TestCase):
    """_ytdlp_download must not trust rc==0 alone — a file must land on disk."""

    def _call(self, output, fake):
        with mock.patch("music_helper.run_streaming", side_effect=fake), \
                mock.patch("music_helper.find_ffmpeg", return_value="ffmpeg"):
            return music_helper._ytdlp_download(
                "python", "ytsearch:test song", output, "mp3",
            )

    def test_rc_zero_no_new_file_returns_false(self):
        with tempfile.TemporaryDirectory() as output:
            result = self._call(output, _build_fake_run_streaming(rc=0))
        self.assertIs(False, result)

    def test_rc_zero_new_file_appears_returns_true(self):
        with tempfile.TemporaryDirectory() as output:
            result = self._call(
                output,
                _build_fake_run_streaming(rc=0, write_file="Some Song.mp3"),
            )
        self.assertIs(True, result)

    def test_nonzero_rc_returns_false(self):
        with tempfile.TemporaryDirectory() as output:
            result = self._call(output, _build_fake_run_streaming(rc=1))
        self.assertIs(False, result)

    def test_already_downloaded_heuristic_returns_true(self):
        with tempfile.TemporaryDirectory() as output:
            result = self._call(
                output,
                _build_fake_run_streaming(
                    rc=0,
                    lines=("[download] Some Song: has already been downloaded",),
                ),
            )
        self.assertIs(True, result)

    def test_rc_zero_no_new_file_emits_warning(self):
        with tempfile.TemporaryDirectory() as output:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = self._call(output, _build_fake_run_streaming(rc=0))
        self.assertIs(False, result)
        self.assertIn("no new audio file appeared", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)

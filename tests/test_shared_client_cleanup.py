"""Checks that failed Soularr transfers leave other slskd downloads alone."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import soularr


class SharedClientCleanupTests(unittest.TestCase):
    def test_failed_album_preserves_other_files_in_the_same_directory(self):
        with tempfile.TemporaryDirectory() as download_dir:
            album_dir = Path(download_dir) / "Album"
            album_dir.mkdir()
            other_file = album_dir / "other-client.flac"
            other_file.write_bytes(b"another download")

            transfers = Mock()
            client = SimpleNamespace(transfers=transfers)
            previous_dir = Path.cwd()
            try:
                with (
                    patch.object(soularr, "slskd", client),
                    patch.object(soularr, "slskd_download_dir", download_dir),
                ):
                    soularr.cancel_downloads(
                        [{"username": "peer", "id": "owned", "file_dir": "Artist\\Album"}]
                    )
                    self.assertEqual(Path.cwd(), previous_dir)
            finally:
                os.chdir(previous_dir)

            transfers.cancel_download.assert_called_once_with(username="peer", id="owned")
            self.assertEqual(other_file.read_bytes(), b"another download")


if __name__ == "__main__":
    unittest.main()

"""Regression tests for #205: don't process an album until slskd has moved its files out of incomplete/."""
import os
from unittest import mock

import pytest

import soularr

DIR = "Music\\The Who\\Who's Next"
NAME = "09 Won't Get Fooled Again.flac"


class FakeClock:
    """Instant time.sleep; runs `on_sleep` hooks so a test can make files appear 'later'."""

    def __init__(self):
        self.now = 1_000_000.0
        self.sleeps = 0
        self.hooks = {}

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 5_000:
            raise AssertionError("monitor loop did not terminate")
        self.now += seconds
        if self.sleeps in self.hooks:
            self.hooks[self.sleeps]()


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(soularr.time, "time", clock.time)
    monkeypatch.setattr(soularr.time, "sleep", clock.sleep)
    monkeypatch.setattr(soularr, "slskd", mock.MagicMock())
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "slskd_download_dir", str(tmp_path))
    monkeypatch.setattr(soularr, "stalled_timeout", 3600)
    monkeypatch.setattr(soularr, "remote_queue_timeout", 300)
    monkeypatch.setattr(soularr.logger, "disabled", True)
    soularr.slskd.transfers.get_download.return_value = {"state": "Completed, Succeeded"}
    soularr.lidarr.get_album.return_value = {"id": 42, "title": "Who's Next", "artist": {"artistName": "The Who"}}
    processed = []
    monkeypatch.setattr(soularr, "process_completed_album", lambda data, fg: processed.append(data["album_id"]))
    cwd = os.getcwd()
    yield tmp_path, clock, processed
    os.chdir(cwd)


def grab_list():
    return {
        42: {
            "files": [{"filename": f"{DIR}\\{NAME}", "id": "a", "file_dir": DIR, "username": "peer", "size": 10}],
            "filetype": "flac",
            "title": "Who's Next",
            "artist": "The Who",
            "year": "1971",
        }
    }


def place_file(root):
    folder = root / "Who's Next"
    folder.mkdir(exist_ok=True)
    (folder / NAME).write_bytes(b"flac")


def test_waits_until_slskd_has_moved_the_file(env):
    root, clock, processed = env
    clock.hooks[3] = lambda: place_file(root)  # slskd finishes the move ~15 s after reporting success

    soularr.monitor_downloads(grab_list(), [])

    assert processed == [42]
    assert clock.sleeps >= 3, "album was processed before the file existed"


def test_file_already_in_place_is_processed_immediately(env):
    root, clock, processed = env
    place_file(root)

    soularr.monitor_downloads(grab_list(), [])

    assert processed == [42]
    assert clock.sleeps == 0


def test_file_that_never_appears_times_out_instead_of_waiting_forever(env):
    root, clock, processed = env
    failed_grab = []

    soularr.monitor_downloads(grab_list(), failed_grab)

    assert processed == []
    assert len(failed_grab) == 1

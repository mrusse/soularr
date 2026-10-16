"""Regression tests: monitor_downloads and the Lidarr import poll must always terminate."""
import os
from unittest import mock

import pytest

import soularr


class FakeClock:
    """Replaces time.time/time.sleep so loops run instantly; fails the test if a loop never exits."""

    def __init__(self, max_sleeps=2_000):
        self.now = 1_000_000.0
        self.sleeps = 0
        self.max_sleeps = max_sleeps

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > self.max_sleeps:
            raise AssertionError("loop did not terminate (infinite wait)")
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(soularr.time, "time", c.time)
    monkeypatch.setattr(soularr.time, "sleep", c.sleep)
    return c


@pytest.fixture(autouse=True)
def quiet_logs(monkeypatch):
    # The code under test logs a full traceback on every failed poll; keep test runs fast.
    monkeypatch.setattr(soularr.logger, "disabled", True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    slskd_dir = tmp_path / "slskd"
    lidarr_dir = tmp_path / "lidarr"
    slskd_dir.mkdir()
    lidarr_dir.mkdir()
    monkeypatch.setattr(soularr, "slskd", mock.MagicMock())
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "slskd_download_dir", str(slskd_dir))
    monkeypatch.setattr(soularr, "lidarr_download_dir", str(lidarr_dir))
    monkeypatch.setattr(soularr, "stalled_timeout", 3600)
    monkeypatch.setattr(soularr, "remote_queue_timeout", 300)
    monkeypatch.setattr(soularr, "rename_download_folders", True)
    monkeypatch.setattr(soularr, "lidarr_disable_sync", False)
    monkeypatch.setattr(soularr, "failed_import_denylist", True)
    monkeypatch.setattr(soularr, "failed_import_denylist_file_path", str(tmp_path / "failed_imports.json"))
    cwd = os.getcwd()
    yield tmp_path
    os.chdir(cwd)


def make_grab_list():
    return {
        42: {
            "files": [
                {"filename": "Music\\Album\\01 - Track.flac", "id": "abc", "file_dir": "Music\\Album", "username": "peer", "size": 10},
            ],
            "filetype": "flac",
            "title": "Album",
            "artist": "Artist",
            "year": "2000",
        }
    }


def test_monitor_exits_when_slskd_status_fails_forever(clock, env):
    """A transfer removed from slskd 404s on every status call; the album must still hit stalled_timeout."""
    soularr.slskd.transfers.get_download.side_effect = Exception("404 Not Found")
    soularr.lidarr.get_album.return_value = {"id": 42, "title": "Album", "artist": {"artistName": "Artist"}}
    grab_list = make_grab_list()
    failed_grab = []

    soularr.monitor_downloads(grab_list, failed_grab)

    assert grab_list == {}
    assert len(failed_grab) == 1
    assert clock.now - 1_000_000.0 >= soularr.stalled_timeout


def make_completed_album(env):
    folder = env / "slskd" / "Album"
    folder.mkdir()
    (folder / "01 - Track.flac").write_bytes(b"not really audio")
    data = make_grab_list()[42]
    data["album_id"] = 42
    return data


@pytest.mark.parametrize("status", ["aborted", "cancelled", "orphaned"])
def test_import_poll_exits_on_other_terminal_statuses(clock, env, status):
    soularr.lidarr.post_command.return_value = {"id": 7}
    soularr.lidarr.get_command.return_value = {
        "id": 7,
        "status": status,
        "commandName": "DownloadedAlbumsScan",
        "message": "Aborted",
        "body": {"path": "/x"},
    }
    failed_grab = []

    soularr.process_completed_album(make_completed_album(env), failed_grab)

    assert failed_grab == []  # not the release's fault: no denylist, no failed grab
    assert not os.path.exists(soularr.failed_import_denylist_file_path)


def test_import_poll_gives_up_after_deadline(clock, env):
    soularr.lidarr.post_command.return_value = {"id": 7}
    soularr.lidarr.get_command.return_value = {
        "id": 7,
        "status": "started",
        "commandName": "DownloadedAlbumsScan",
        "message": "Processing",
        "body": {"path": "/x"},
    }
    failed_grab = []

    soularr.process_completed_album(make_completed_album(env), failed_grab)

    assert failed_grab == []
    assert clock.now - 1_000_000.0 >= soularr.IMPORT_POLL_TIMEOUT


def test_import_poll_failed_import_still_denylisted(clock, env):
    """Existing behaviour kept: a genuinely failed import still goes to failed_grab and the denylist."""
    soularr.lidarr.post_command.return_value = {"id": 7}
    soularr.lidarr.get_command.return_value = {
        "id": 7,
        "status": "completed",
        "commandName": "DownloadedAlbumsScan",
        "message": "Failed to import",
        "body": {"path": "/x/Artist - Album (2000)"},
    }
    soularr.lidarr.get_album.return_value = {"id": 42, "title": "Album", "artist": {"artistName": "Artist"}}
    failed_grab = []

    soularr.process_completed_album(make_completed_album(env), failed_grab)

    assert len(failed_grab) == 1
    assert os.path.exists(soularr.failed_import_denylist_file_path)


def test_monitor_completes_normal_download(clock, env, monkeypatch):
    """Existing behaviour kept: a finished album is handed to process_completed_album."""
    soularr.slskd.transfers.get_download.return_value = {"state": "Completed, Succeeded"}
    # A finished download is on disk in slskd's download directory (see #205).
    (env / "slskd" / "Album").mkdir()
    (env / "slskd" / "Album" / "01 - Track.flac").write_bytes(b"audio")
    processed = []
    monkeypatch.setattr(soularr, "process_completed_album", lambda data, fg: processed.append(data["album_id"]))
    grab_list = make_grab_list()

    soularr.monitor_downloads(grab_list, [])

    assert processed == [42]
    assert grab_list == {}

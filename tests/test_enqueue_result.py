"""Regression tests: an enqueue that slskd doesn't report back must not count as a successful grab."""
import os
from unittest import mock

import pytest

import soularr

DIR = "Music\\Artist\\Album"


def remote_files():
    return [
        {"filename": "01 - One.flac", "size": 10},
        {"filename": "02 - Two.flac", "size": 20},
    ]


def slskd_listing(*names):
    """What slskd.transfers.get_downloads(username=...) returns for the given enqueued filenames."""
    return {
        "directories": [
            {"directory": DIR, "files": [{"filename": f"{DIR}\\{n}", "id": f"id-{n}"} for n in names]},
        ]
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(soularr, "slskd", mock.MagicMock())
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "download_filtering", False)
    monkeypatch.setattr(soularr, "slskd_download_dir", str(tmp_path))
    monkeypatch.setattr(soularr, "stalled_timeout", 3600)
    monkeypatch.setattr(soularr, "remote_queue_timeout", 300)
    monkeypatch.setattr(soularr.time, "sleep", lambda s: None)
    monkeypatch.setattr(soularr.logger, "disabled", True)
    soularr.lidarr.get_album.return_value = {"id": 42, "title": "Album", "artist": {"artistName": "Artist"}}
    soularr.slskd.transfers.enqueue.return_value = True
    # Every user's folder is a match; these tests are about what happens after the match.
    monkeypatch.setattr(
        soularr, "check_for_match", lambda tracks, ft, dirs, user: (True, {"files": remote_files()}, DIR)
    )
    cwd = os.getcwd()
    yield tmp_path
    os.chdir(cwd)


TRACKS = [{"albumId": 42}]
RESULTS = {"peer": {"flac": [DIR]}}


def test_enqueue_not_reported_by_slskd_is_not_success(env):
    soularr.slskd.transfers.get_downloads.return_value = {"directories": []}

    found, downloads = soularr.try_enqueue(TRACKS, RESULTS, "flac")

    assert (found, downloads) == (False, None)


def test_partially_reported_enqueue_fails_and_cancels_the_rest(env):
    soularr.slskd.transfers.get_downloads.return_value = slskd_listing("01 - One.flac")

    found, downloads = soularr.try_enqueue(TRACKS, RESULTS, "flac")

    assert (found, downloads) == (False, None)
    soularr.slskd.transfers.cancel_download.assert_called_once_with(username="peer", id="id-01 - One.flac")


def test_fully_reported_enqueue_succeeds(env):
    soularr.slskd.transfers.get_downloads.return_value = slskd_listing("01 - One.flac", "02 - Two.flac")

    found, downloads = soularr.try_enqueue(TRACKS, RESULTS, "flac")

    assert found is True
    assert [d["id"] for d in downloads] == ["id-01 - One.flac", "id-02 - Two.flac"]
    soularr.slskd.transfers.cancel_download.assert_not_called()


def test_requeue_not_reported_by_slskd_fails_album_instead_of_crashing(env):
    """monitor_downloads' requeue used requeue[0] and raised IndexError on an empty result."""
    grab_list = {
        42: {
            "files": [
                {"filename": f"{DIR}\\01 - One.flac", "id": "a", "file_dir": DIR, "username": "peer", "size": 10},
                {"filename": f"{DIR}\\02 - Two.flac", "id": "b", "file_dir": DIR, "username": "peer", "size": 20},
            ],
            "filetype": "flac",
            "title": "Album",
            "artist": "Artist",
            "year": "2000",
        }
    }
    states = {"a": "Completed, Errored", "b": "InProgress"}
    soularr.slskd.transfers.get_download.side_effect = lambda user, id: {"state": states[id]}
    soularr.slskd.transfers.get_downloads.return_value = {"directories": []}
    failed_grab = []

    soularr.monitor_downloads(grab_list, failed_grab)

    assert grab_list == {}
    assert len(failed_grab) == 1

"""Tests for ignore_failed_users: users whose downloads fail are skipped on later runs (issue #27)."""
import json
import os
from datetime import datetime, timedelta
from unittest import mock

import pytest

import soularr

DIR = "Music\\Artist\\Album"


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(soularr, "slskd", mock.MagicMock())
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "download_filtering", False)
    monkeypatch.setattr(soularr, "slskd_download_dir", str(tmp_path))
    monkeypatch.setattr(soularr, "stalled_timeout", 3600)
    monkeypatch.setattr(soularr, "remote_queue_timeout", 300)
    monkeypatch.setattr(soularr, "ignored_users", [])
    monkeypatch.setattr(soularr, "ignore_failed_users", True)
    monkeypatch.setattr(soularr, "failed_user_ignore_hours", 168)
    monkeypatch.setattr(soularr, "failed_users_file_path", str(tmp_path / "failed_users.json"))
    monkeypatch.setattr(soularr, "failed_users", {})
    clock = FakeClock()
    monkeypatch.setattr(soularr.time, "time", clock.time)
    monkeypatch.setattr(soularr.time, "sleep", clock.sleep)
    monkeypatch.setattr(soularr.logger, "disabled", True)
    soularr.lidarr.get_album.return_value = {"id": 42, "title": "Album", "artist": {"artistName": "Artist"}}
    cwd = os.getcwd()
    yield tmp_path
    os.chdir(cwd)


def grab_list_for(*users):
    files = [
        {"filename": f"{DIR}\\0{i} - T.flac", "id": f"id{i}", "file_dir": DIR, "username": user, "size": 10}
        for i, user in enumerate(users, 1)
    ]
    return {42: {"files": files, "filetype": "flac", "title": "Album", "artist": "Artist", "year": "2000"}}


def saved_users(env):
    with open(env / "failed_users.json") as f:
        return json.load(f)


def test_user_recorded_when_album_times_out(env):
    soularr.slskd.transfers.get_download.return_value = {"state": "Queued, Remotely"}

    soularr.monitor_downloads(grab_list_for("slowpeer"), [])

    saved = saved_users(env)
    assert list(saved) == ["slowpeer"]
    assert saved["slowpeer"]["failures"] == 1
    assert saved["slowpeer"]["last_album"] == "Artist - Album"


def test_only_users_with_unfinished_files_are_recorded(env):
    """Multi-disc albums can come from two users; don't blame the one whose disc finished."""
    states = {"id1": "Completed, Succeeded", "id2": "InProgress"}
    soularr.slskd.transfers.get_download.side_effect = lambda user, id: {"state": states[id]}

    soularr.monitor_downloads(grab_list_for("goodpeer", "badpeer"), [])

    assert list(saved_users(env)) == ["badpeer"]


def test_failed_user_is_skipped_on_later_search(env, monkeypatch):
    soularr.record_failed_user("badpeer", "Artist - Other", "Timeout waiting for download of")
    browsed = []

    def check_for_match(tracks, ft, dirs, user):
        browsed.append(user)
        return False, {}, ""

    monkeypatch.setattr(soularr, "check_for_match", check_for_match)

    soularr.try_enqueue([{"albumId": 42}], {"badpeer": {"flac": [DIR]}, "goodpeer": {"flac": [DIR]}}, "flac")

    assert browsed == ["goodpeer"]


def test_ignored_users_are_skipped_before_browsing(env, monkeypatch):
    """Previously ignored_users was only checked after browsing the user's folder."""
    monkeypatch.setattr(soularr, "ignored_users", ["Fred"])
    browsed = []
    monkeypatch.setattr(soularr, "check_for_match", lambda t, ft, d, user: browsed.append(user) or (False, {}, ""))

    soularr.try_enqueue([{"albumId": 42}], {"Fred": {"flac": [DIR]}, "Bob": {"flac": [DIR]}}, "flac")

    assert browsed == ["Bob"]


def test_entry_expires_after_configured_hours(env):
    old = (datetime.now() - timedelta(hours=200)).strftime("%Y-%m-%dT%H:%M:%S")
    with open(env / "failed_users.json", "w") as f:
        json.dump({"oldpeer": {"failures": 3, "last_failed": old}}, f)

    soularr.failed_users = soularr.load_failed_users(soularr.failed_users_file_path)

    assert not soularr.is_failed_user("oldpeer")


def test_zero_hours_means_ignore_forever(env, monkeypatch):
    monkeypatch.setattr(soularr, "failed_user_ignore_hours", 0)
    old = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M:%S")
    with open(env / "failed_users.json", "w") as f:
        json.dump({"oldpeer": {"failures": 1, "last_failed": old}}, f)

    soularr.failed_users = soularr.load_failed_users(soularr.failed_users_file_path)

    assert soularr.is_failed_user("oldpeer")


def test_disabled_by_default_records_and_skips_nothing(env, monkeypatch):
    monkeypatch.setattr(soularr, "ignore_failed_users", False)
    soularr.slskd.transfers.get_download.return_value = {"state": "Queued, Remotely"}

    soularr.monitor_downloads(grab_list_for("slowpeer"), [])

    assert not os.path.exists(env / "failed_users.json")
    assert not soularr.is_failed_user("slowpeer")


def test_unreadable_file_starts_empty(env):
    (env / "failed_users.json").write_text("{not json")

    assert soularr.load_failed_users(soularr.failed_users_file_path) == {}

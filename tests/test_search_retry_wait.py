"""Tests for search_retry_wait_hours: don't re-search an album that failed recently (issue #53)."""
import configparser
import json
from datetime import datetime, timedelta
from unittest import mock

import pytest

import soularr


def album(i):
    return {"id": i, "title": f"Album {i}", "artist": {"artistName": "Artist"}, "releases": []}


def stamp(hours_ago):
    return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(soularr, "config", configparser.ConfigParser())
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "failed_import_denylist", False)
    monkeypatch.setattr(soularr, "search_retry_wait_hours", 24)
    monkeypatch.setattr(soularr, "search_attempts_file_path", str(tmp_path / "search_attempts.json"))
    monkeypatch.setattr(soularr, "slskd_host_url", "http://slskd")
    monkeypatch.setattr(soularr, "slskd_url_base", "/")
    monkeypatch.setattr(soularr.logger, "disabled", True)
    return tmp_path


def write_attempts(env, data):
    with open(env / "search_attempts.json", "w") as f:
        json.dump(data, f)


def read_attempts(env):
    with open(env / "search_attempts.json") as f:
        return json.load(f)


def test_recently_failed_album_is_skipped(env):
    write_attempts(env, {"1": {"attempts": 1, "last_failed": stamp(2)}})

    result = soularr.filter_list([album(1), album(2)])

    assert [a["id"] for a in result] == [2]


def test_album_is_searched_again_after_the_wait(env):
    write_attempts(env, {"1": {"attempts": 3, "last_failed": stamp(25)}})

    result = soularr.filter_list([album(1)])

    assert [a["id"] for a in result] == [1]


def test_all_albums_waiting_returns_none(env):
    write_attempts(env, {"1": {"attempts": 1, "last_failed": stamp(1)}})

    assert soularr.filter_list([album(1)]) is None


def test_failures_recorded_and_successes_cleared(env, monkeypatch):
    write_attempts(env, {"3": {"attempts": 2, "last_failed": stamp(30)}, "1": {"attempts": 1, "last_failed": stamp(30)}})
    # album 1: search found nothing; album 2: found but grab failed; album 3: downloaded and imported
    monkeypatch.setattr(soularr, "search_and_queue", lambda albums: ({}, [album(1)], [album(2)]))
    monkeypatch.setattr(soularr, "monitor_downloads", lambda grab_list, failed_grab: None)

    soularr.grab_most_wanted([album(1), album(2), album(3)])

    saved = read_attempts(env)
    assert sorted(saved) == ["1", "2"]
    assert saved["1"]["attempts"] == 2
    assert saved["2"]["attempts"] == 1
    assert saved["2"]["album"] == "Artist - Album 2"


def test_failure_during_download_is_recorded(env, monkeypatch):
    """An album that was enqueued but then failed in monitor_downloads ends up in failed_grab too."""
    monkeypatch.setattr(soularr, "search_and_queue", lambda albums: ({5: {"title": "Album 5", "artist": "Artist"}}, [], []))
    monkeypatch.setattr(soularr, "monitor_downloads", lambda grab_list, failed_grab: failed_grab.append(album(5)))

    soularr.grab_most_wanted([album(5)])

    assert list(read_attempts(env)) == ["5"]


def test_disabled_by_default_changes_nothing(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_retry_wait_hours", 0)
    monkeypatch.setattr(soularr, "search_and_queue", lambda albums: ({}, [album(1)], []))
    monkeypatch.setattr(soularr, "monitor_downloads", lambda grab_list, failed_grab: None)

    soularr.grab_most_wanted([album(1)])

    assert not (env / "search_attempts.json").exists()
    assert [a["id"] for a in soularr.filter_list([album(1)])] == [1]


def test_unreadable_file_starts_empty(env):
    (env / "search_attempts.json").write_text("{not json")

    assert [a["id"] for a in soularr.filter_list([album(1)])] == [1]

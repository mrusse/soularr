"""Regression tests: get_records must handle Lidarr connection errors and a wanted list that shrinks mid-paging."""
from unittest import mock

import pytest
import requests
from pyarr.exceptions import PyarrConnectionError

import soularr


def rec(i):
    return {"id": i, "title": f"Album {i}", "releases": [{"albumId": i}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "page_size", 10)
    monkeypatch.setattr(soularr, "current_page_file_path", str(tmp_path / ".current_page.txt"))
    monkeypatch.setattr(soularr, "lock_file_path", str(tmp_path / ".soularr.lock"))
    monkeypatch.setattr(soularr.logger, "disabled", True)
    soularr.lidarr.get_queue.return_value = {"totalRecords": 0, "pageSize": 10, "records": []}
    return tmp_path


def paged(records, calls_limit=200):
    """get_wanted stand-in serving `records` (a list, may be mutated by the test) page by page."""
    calls = {"n": 0}

    def get_wanted(page=1, page_size=10, **kwargs):
        calls["n"] += 1
        if calls["n"] > calls_limit:
            raise AssertionError("get_records did not terminate (infinite paging loop)")
        start = (page - 1) * page_size
        return {"totalRecords": len(records), "records": records[start : start + page_size]}

    return get_wanted, calls


def test_all_terminates_when_wanted_list_shrinks(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_type", "all")
    records = [rec(i) for i in range(25)]
    get_wanted, _ = paged(records)

    def shrinking(page=1, **kwargs):
        if page == 2:
            del records[20:]  # 5 albums grabbed/removed in Lidarr while we page
        return get_wanted(page=page, **kwargs)

    soularr.lidarr.get_wanted.side_effect = shrinking

    result = soularr.get_records(missing=True)

    assert [r["id"] for r in result] == list(range(20))


def test_initial_connection_error_returns_empty(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_type", "first_page")
    soularr.lidarr.get_wanted.side_effect = PyarrConnectionError("Lidarr down")

    assert soularr.get_records(missing=True) == []


def test_all_connection_error_mid_paging_does_not_duplicate(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_type", "all")
    records = [rec(i) for i in range(25)]
    get_wanted, _ = paged(records)

    def flaky(page=1, **kwargs):
        if page == 2:
            raise PyarrConnectionError("Lidarr restarted")
        return get_wanted(page=page, **kwargs)

    soularr.lidarr.get_wanted.side_effect = flaky

    result = soularr.get_records(missing=True)

    ids = [r["id"] for r in result]
    assert len(ids) == len(set(ids)), "page 1 was added twice"


def test_incrementing_page_not_advanced_on_error(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_type", "incrementing_page")
    (env / ".current_page.txt").write_text("2")
    records = [rec(i) for i in range(35)]
    get_wanted, _ = paged(records)

    def flaky(page=1, **kwargs):
        if page == 2:
            raise PyarrConnectionError("Lidarr restarted")
        return get_wanted(page=page, **kwargs)

    soularr.lidarr.get_wanted.side_effect = flaky

    assert soularr.get_records(missing=True) == []
    assert (env / ".current_page.txt").read_text() == "2"


def test_queue_connection_error_returns_unfiltered(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_type", "first_page")
    get_wanted, _ = paged([rec(1), rec(2)])
    soularr.lidarr.get_wanted.side_effect = get_wanted
    soularr.lidarr.get_queue.side_effect = PyarrConnectionError("Lidarr down")

    assert [r["id"] for r in soularr.get_records(missing=True)] == [1, 2]


def test_connection_refused_returns_empty(env, monkeypatch):
    """pyarr only wraps timeouts in PyarrConnectionError; a refused connection (Lidarr down)
    surfaces as requests.exceptions.ConnectionError."""
    monkeypatch.setattr(soularr, "search_type", "first_page")
    soularr.lidarr.get_wanted.side_effect = requests.exceptions.ConnectionError("Connection refused")

    assert soularr.get_records(missing=True) == []


def test_all_connection_refused_mid_paging_does_not_duplicate(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_type", "all")
    get_wanted, _ = paged([rec(i) for i in range(25)])

    def flaky(page=1, **kwargs):
        if page == 2:
            raise requests.exceptions.ConnectionError("Connection refused")
        return get_wanted(page=page, **kwargs)

    soularr.lidarr.get_wanted.side_effect = flaky

    ids = [r["id"] for r in soularr.get_records(missing=True)]
    assert len(ids) == len(set(ids))

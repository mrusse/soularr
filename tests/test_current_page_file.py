"""Regression tests for #187: a damaged .current_page.txt must not stop every run."""
import os
from unittest import mock

import pytest

import soularr


@pytest.fixture
def page_file(tmp_path, monkeypatch):
    monkeypatch.setattr(soularr.logger, "disabled", True)
    return tmp_path / ".current_page.txt"


@pytest.mark.parametrize(
    "contents",
    [
        b"\x00\x00\x00\x00",  # what #187 hit: file allocated but its data never written (crash/kill mid-write)
        b"\x00\x00",
        b"abc",
        "\u00b2".encode(),  # superscript 2: isdigit() is True but int() rejects it
        b"0",
        b"-3",
        b"   ",
        b"",
    ],
)
def test_unreadable_page_resets_to_first_page(page_file, contents):
    page_file.write_bytes(contents)

    assert soularr.get_current_page(str(page_file)) == 1
    assert page_file.read_text() == "1"


def test_valid_page_is_kept(page_file):
    page_file.write_text("4\n")

    assert soularr.get_current_page(str(page_file)) == 4


def test_missing_file_is_created(page_file):
    assert soularr.get_current_page(str(page_file)) == 1
    assert page_file.read_text() == "1"


def test_update_writes_atomically(page_file):
    page_file.write_text("2")

    soularr.update_current_page(str(page_file), "3")

    assert page_file.read_text() == "3"
    assert os.listdir(page_file.parent) == [page_file.name], "temporary file left behind"


def test_update_failure_leaves_previous_page_intact(page_file, monkeypatch):
    page_file.write_text("2")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(soularr.os, "replace", boom)
    with pytest.raises(OSError):
        soularr.update_current_page(str(page_file), "3")

    assert page_file.read_text() == "2"
    assert os.listdir(page_file.parent) == [page_file.name]


def test_get_records_survives_corrupt_page_file(page_file, monkeypatch):
    """End to end: get_records used to raise ValueError, which main() turns into 'Exiting...' every run."""
    page_file.write_bytes(b"\x00\x00\x00\x00")
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "search_type", "incrementing_page")
    monkeypatch.setattr(soularr, "page_size", 10)
    monkeypatch.setattr(soularr, "current_page_file_path", str(page_file))
    monkeypatch.setattr(soularr, "lock_file_path", str(page_file.parent / ".soularr.lock"))
    records = [{"id": i, "title": f"A{i}", "releases": [{"albumId": i}]} for i in range(3)]
    soularr.lidarr.get_wanted.return_value = {"totalRecords": 3, "records": records}
    soularr.lidarr.get_queue.return_value = {"totalRecords": 0, "pageSize": 10, "records": []}

    assert [r["id"] for r in soularr.get_records(missing=True)] == [0, 1, 2]

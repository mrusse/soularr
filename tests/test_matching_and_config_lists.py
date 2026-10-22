"""Regression tests: upper-case extensions, spaces in config lists, and 10+ disc release formats."""
import os
import sys
from unittest import mock

import pytest

import soularr


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(soularr.logger, "disabled", True)


# --- upper-case file extensions ----------------------------------------------------------


@pytest.mark.parametrize("name", ["01 - Song.FLAC", "01 - Song.Flac", "01 - Song.flac"])
def test_verify_filetype_ignores_extension_case(name):
    assert soularr.verify_filetype({"filename": name}, "flac")


def test_verify_filetype_with_bitrate_ignores_extension_case():
    assert soularr.verify_filetype({"filename": "01 - Song.MP3", "bitRate": 320}, "mp3 320")


def test_album_track_num_counts_upper_case_files(monkeypatch):
    monkeypatch.setattr(soularr, "allowed_filetypes", ["flac", "mp3"])
    directory = {"files": [{"filename": "01 - One.FLAC"}, {"filename": "02 - Two.FLAC"}, {"filename": "cover.JPG"}]}

    assert soularr.album_track_num(directory) == {"count": 2, "filetype": "flac"}


def test_album_match_with_upper_case_extensions(monkeypatch):
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "minimum_match_ratio", 0.8)
    monkeypatch.setattr(soularr, "ignored_users", [])
    soularr.lidarr.get_album.return_value = {"title": "Album", "artist": {"artistName": "Artist"}}
    tracks = [{"albumId": 1, "title": "Go"}, {"albumId": 1, "title": "Up"}]
    lower = [{"filename": "Go.flac"}, {"filename": "Up.flac"}]
    upper = [{"filename": "Go.FLAC"}, {"filename": "Up.FLAC"}]

    assert soularr.album_match(tracks, lower, "peer", "flac")
    assert soularr.album_match(tracks, upper, "peer", "flac")


# --- config lists ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("flac, mp3", ["flac", "mp3"]),
        (" flac 24/192 ,flac,  mp3 320", ["flac 24/192", "flac", "mp3 320"]),
        ("flac  24/192", ["flac 24/192"]),
        ("User1, User2,", ["User1", "User2"]),
        ("", []),
        (" , ", []),
    ],
)
def test_split_config_list(raw, expected):
    assert soularr.split_config_list(raw) == expected


def test_title_blacklist_tolerates_spaces(monkeypatch):
    cfg = soularr.configparser.ConfigParser()
    cfg.read_dict({"Search Settings": {"title_blacklist": "Live, Karaoke"}})
    monkeypatch.setattr(soularr, "config", cfg)

    assert soularr.is_blacklisted("Greatest Hits (Karaoke Version)")
    assert not soularr.is_blacklisted("Greatest Hits")


def test_main_parses_lists_with_spaces(tmp_path, monkeypatch):
    """End to end through main(): 'flac, mp3' used to give [' mp3'], which never matches anything."""
    (tmp_path / "config.ini").write_text(
        "[Lidarr]\napi_key = x\nhost_url = http://lidarr\ndownload_dir = /d\n"
        "[Slskd]\napi_key = x\nhost_url = http://slskd\ndownload_dir = /s\n"
        "[Search Settings]\nallowed_filetypes = FLAC, mp3 320\nignored_users = Fred, Bob\n"
        "[Release Settings]\naccepted_countries = Europe, Japan\naccepted_formats = CD, Vinyl\n"
        "[Download Settings]\nextensions_whitelist = nfo, jpg\n"
        "[Logging]\nlog_to_file = False\n"
    )
    monkeypatch.delenv("IN_DOCKER", raising=False)
    monkeypatch.setattr(sys, "argv", ["soularr.py", "-c", str(tmp_path), "-v", str(tmp_path), "--no-lock-file"])
    lidarr = mock.MagicMock()
    lidarr.get_wanted.return_value = {"totalRecords": 0, "records": []}
    lidarr.get_queue.return_value = {"totalRecords": 0, "pageSize": 10, "records": []}
    monkeypatch.setattr(soularr, "LidarrAPI", lambda *a, **k: lidarr)
    monkeypatch.setattr(soularr.slskd_api, "SlskdClient", lambda *a, **k: mock.MagicMock())
    cwd = os.getcwd()
    try:
        soularr.main()
    finally:
        os.chdir(cwd)

    assert soularr.allowed_filetypes == ["flac", "mp3 320"]
    assert soularr.ignored_users == ["Fred", "Bob"]
    assert soularr.accepted_countries == ["Europe", "Japan"]
    assert soularr.accepted_formats == ["CD", "Vinyl"]
    assert soularr.extensions_whitelist == ["nfo", "jpg"]


# --- release formats with 10 or more discs ------------------------------------------------


def release(fmt, rid=1):
    return {"id": rid, "format": fmt, "country": ["United States"], "status": "Official", "trackCount": 20, "mediumCount": 1}


@pytest.fixture
def release_settings(monkeypatch):
    monkeypatch.setattr(soularr, "use_selected_lidarr_release", False)
    monkeypatch.setattr(soularr, "use_most_common_tracknum", False)
    monkeypatch.setattr(soularr, "allow_multi_disc", True)
    monkeypatch.setattr(soularr, "skip_region_check", False)
    monkeypatch.setattr(soularr, "accepted_countries", ["United States"])
    monkeypatch.setattr(soularr, "accepted_formats", ["CD"])


@pytest.mark.parametrize("fmt", ["2xCD", "10xCD", "12xCD"])
def test_multi_disc_formats_are_accepted(release_settings, fmt):
    releases = [release("Cassette", 1), release(fmt, 2)]

    assert soularr.choose_release("Artist", releases)["id"] == 2


def test_multi_disc_not_accepted_when_disabled(release_settings, monkeypatch):
    monkeypatch.setattr(soularr, "allow_multi_disc", False)
    releases = [release("Cassette", 1), release("10xCD", 2), release("CD", 3)]

    assert soularr.choose_release("Artist", releases)["id"] == 3


@pytest.mark.parametrize("fmt", ["", "X", "x"])
def test_short_or_empty_format_does_not_crash(release_settings, fmt):
    releases = [release(fmt, 1), release("CD", 2)]

    assert soularr.choose_release("Artist", releases)["id"] == 2

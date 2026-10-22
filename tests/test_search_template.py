"""Configurable search strings (#94): search_template, per-album-type overrides, and '|' fallbacks."""
import configparser
from unittest import mock

import pytest

import soularr


def album(title="Paradise", artist="Bone Thugs-n-Harmony", album_type="EP", release_date="1997-07-29T00:00:00Z", album_id=1):
    return {"id": album_id, "title": title, "artist": {"artistName": artist}, "albumType": album_type, "releaseDate": release_date}


def settings(monkeypatch, **search_settings):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_dict({"Search Settings": {k: str(v) for k, v in search_settings.items()}})
    monkeypatch.setattr(soularr, "config", cfg)
    monkeypatch.setattr(soularr, "search_blacklist", [])
    monkeypatch.setattr(soularr, "search_templates", soularr.load_search_templates(cfg))
    monkeypatch.setattr(soularr.logger, "disabled", True)


# --- query building --------------------------------------------------------------------------------


def test_default_is_unchanged_album_title_only(monkeypatch):
    settings(monkeypatch)
    assert soularr.build_search_queries(album()) == ["Paradise"]


def test_default_with_prepend_artist_is_unchanged(monkeypatch):
    settings(monkeypatch, album_prepend_artist=True)
    assert soularr.build_search_queries(album()) == ["Bone Thugs-n-Harmony Paradise"]


def test_default_single_character_title_still_gets_artist(monkeypatch):
    settings(monkeypatch)
    assert soularr.build_search_queries(album(title="X")) == ["Bone Thugs-n-Harmony X"]


def test_template_placeholders(monkeypatch):
    settings(monkeypatch, search_template="{artist} {album} {year} {type}")
    assert soularr.build_search_queries(album()) == ["Bone Thugs-n-Harmony Paradise 1997 EP"]


def test_per_type_template_overrides_default(monkeypatch):
    settings(monkeypatch, search_template="{artist} {album}", search_template_ep="{artist} {album} {year}")

    assert soularr.build_search_queries(album(album_type="EP")) == ["Bone Thugs-n-Harmony Paradise 1997"]
    assert soularr.build_search_queries(album(album_type="Album")) == ["Bone Thugs-n-Harmony Paradise"]


def test_per_type_template_without_global_template(monkeypatch):
    settings(monkeypatch, search_template_single="{artist} {album} {year}")

    assert soularr.build_search_queries(album(album_type="Single")) == ["Bone Thugs-n-Harmony Paradise 1997"]
    assert soularr.build_search_queries(album(album_type="Album")) == ["Paradise"]  # unchanged default


def test_fallbacks_in_order_and_deduplicated(monkeypatch):
    settings(monkeypatch, search_template="{artist} {album} {year} | {artist} {album} | {artist}  {album}")
    assert soularr.build_search_queries(album()) == ["Bone Thugs-n-Harmony Paradise 1997", "Bone Thugs-n-Harmony Paradise"]


def test_missing_year_does_not_leave_gaps(monkeypatch):
    settings(monkeypatch, search_template="{artist} {year} {album}")
    assert soularr.build_search_queries(album(release_date=None)) == ["Bone Thugs-n-Harmony Paradise"]


def test_search_blacklist_still_applies(monkeypatch):
    settings(monkeypatch, search_template="{artist} {album}")
    monkeypatch.setattr(soularr, "search_blacklist", ["Thugs-n-Harmony"])
    assert soularr.build_search_queries(album()) == ["Bone Paradise"]


def test_type_key_with_spaces(monkeypatch):
    settings(monkeypatch, search_template_broadcast="{album} broadcast")
    assert soularr.build_search_queries(album(album_type="Broadcast")) == ["Paradise broadcast"]


@pytest.mark.parametrize("bad", ["{artist} {albm}", "{artist} {0}", "{artist} {album"])
def test_invalid_template_is_rejected_at_startup(bad):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_dict({"Search Settings": {"search_template": bad}})
    with pytest.raises(ValueError) as error:
        soularr.load_search_templates(cfg)
    assert "search_template" in str(error.value)


# --- fallback searching ----------------------------------------------------------------------------


@pytest.fixture
def searching(monkeypatch):
    """Record each query search_and_queue sends, with per-query outcomes."""
    outcomes = {}
    sent = []

    def search_for_album(album, query):
        sent.append(query)
        return outcomes.get(query, ("none",))[0] != "none"

    def find_download(album, grab_list):
        if outcomes.get(sent[-1], ("none",))[0] == "match":
            grab_list[album["id"]] = {"query": sent[-1]}
            return True
        return False

    sleeps = []
    monkeypatch.setattr(soularr, "search_for_album", search_for_album)
    monkeypatch.setattr(soularr, "find_download", find_download)
    monkeypatch.setattr(soularr, "minimum_search_interval", 5)
    monkeypatch.setattr(soularr.time, "sleep", lambda s: sleeps.append(s))
    return outcomes, sent, sleeps


def test_falls_back_when_first_query_finds_nothing(monkeypatch, searching):
    outcomes, sent, _ = searching
    settings(monkeypatch, search_template="{artist} {album} {year} | {artist} {album}")
    outcomes["Bone Thugs-n-Harmony Paradise"] = ("match",)

    grab_list, failed_search, failed_grab = soularr.search_and_queue([album()])

    assert sent == ["Bone Thugs-n-Harmony Paradise 1997", "Bone Thugs-n-Harmony Paradise"]
    assert list(grab_list) == [1] and failed_search == [] and failed_grab == []


def test_falls_back_when_first_query_has_results_but_no_match(monkeypatch, searching):
    """The #94 case: the plain query returns LPs that contain a same-named track, but no matching EP."""
    outcomes, sent, _ = searching
    settings(monkeypatch, search_template_ep="{artist} {album} | {artist} {album} {year}")
    outcomes["Bone Thugs-n-Harmony Paradise"] = ("results",)
    outcomes["Bone Thugs-n-Harmony Paradise 1997"] = ("match",)

    grab_list, _, _ = soularr.search_and_queue([album()])

    assert sent == ["Bone Thugs-n-Harmony Paradise", "Bone Thugs-n-Harmony Paradise 1997"]
    assert list(grab_list) == [1]


def test_stops_after_first_successful_query(monkeypatch, searching):
    outcomes, sent, _ = searching
    settings(monkeypatch, search_template="{artist} {album} {year} | {artist} {album}")
    outcomes["Bone Thugs-n-Harmony Paradise 1997"] = ("match",)

    soularr.search_and_queue([album()])

    assert sent == ["Bone Thugs-n-Harmony Paradise 1997"]


def test_all_queries_fail_classification(monkeypatch, searching):
    outcomes, sent, _ = searching
    settings(monkeypatch, search_template="{artist} {album} {year} | {artist} {album}")

    _, failed_search, failed_grab = soularr.search_and_queue([album()])
    assert len(failed_search) == 1 and failed_grab == []  # no query returned anything

    sent.clear()
    outcomes["Bone Thugs-n-Harmony Paradise"] = ("results",)
    _, failed_search, failed_grab = soularr.search_and_queue([album()])
    assert failed_search == [] and len(failed_grab) == 1  # something was found, nothing matched


def test_minimum_search_interval_between_fallback_queries(monkeypatch, searching):
    outcomes, sent, sleeps = searching
    settings(monkeypatch, search_template="{artist} {album} {year} | {artist} {album} | {album}")

    soularr.search_and_queue([album()])

    assert len(sent) == 3
    assert len(sleeps) == 2  # between the 3 queries, none after the last (single album in the run)


def test_main_rejects_bad_template(tmp_path, monkeypatch):
    import os
    import sys

    (tmp_path / "config.ini").write_text(
        "[Lidarr]\napi_key = x\nhost_url = http://lidarr\ndownload_dir = /d\n"
        "[Slskd]\napi_key = x\nhost_url = http://slskd\ndownload_dir = /s\n"
        "[Search Settings]\nsearch_template = {artist} {albm}\n"
        "[Logging]\nlog_to_file = False\n"
    )
    monkeypatch.delenv("IN_DOCKER", raising=False)
    monkeypatch.setattr(sys, "argv", ["soularr.py", "-c", str(tmp_path), "-v", str(tmp_path), "--no-lock-file"])
    monkeypatch.setattr(soularr, "LidarrAPI", lambda *a, **k: mock.MagicMock())
    monkeypatch.setattr(soularr.slskd_api, "SlskdClient", lambda *a, **k: mock.MagicMock())
    cwd = os.getcwd()
    try:
        with pytest.raises(SystemExit):
            soularr.main()
    finally:
        os.chdir(cwd)

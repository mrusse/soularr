"""
Tests for the search fallback chain (search_fallback_bare_title).

The Soulseek server silently returns nothing for searches containing some terms, several artist names among them, so
when the artist-prefixed search finds nothing soularr retries with the bare album title and then with the album title
plus the first track title. Generic titles skip the bare-title step (search_fallback_generic_titles).
"""
import configparser
import logging
from unittest import mock

import pytest
import requests

import soularr

ARTIST = "Lady Gaga"
TITLE = "The Fame Monster"
RELEASE = {"id": 11, "monitored": True, "format": "CD", "trackCount": 2, "mediumCount": 1, "country": ["US"], "status": "Official", "media": [{}]}
TRACKS = [{"title": "Alejandro", "absoluteTrackNumber": 2}, {"title": "Bad Romance", "absoluteTrackNumber": 1}]
A_RESPONSE = [{"username": "peer", "files": [{"filename": "Music\\Lady Gaga - The Fame Monster\\01 - Bad Romance.flac"}]}]
BAD_REQUEST = "The search text must contain at least one term of 3 or more characters"


def album(title):
    return {"id": 7, "artistId": 3, "title": title, "artist": {"artistName": ARTIST}, "releaseDate": "2009-11-18"}


class FakeSlskd:
    """
    Stands in for the slskd client. `responses` maps a query to what the search returns:
    a list of responses, a str (the body slskd returns with a 400) or an exception to raise.
    Queries not in the map return no responses.
    """

    def __init__(self, responses):
        self.responses = responses
        self.queries = []
        self.searches = mock.MagicMock()
        self.searches.search_text.side_effect = self.search_text
        self.searches.state.return_value = {"state": "Completed"}
        self.searches.search_responses.side_effect = lambda search_id: self.responses.get(self.queries[int(search_id)], [])

    def search_text(self, searchText, **kwargs):
        self.queries.append(searchText)
        result = self.responses.get(searchText, [])
        if isinstance(result, Exception):
            raise result
        if isinstance(result, str):
            return result  # slskd_api hands back the parsed body of an error response, not a search
        return {"id": str(len(self.queries) - 1)}


@pytest.fixture
def env(monkeypatch):
    config = configparser.ConfigParser()
    config["Search Settings"] = {"album_prepend_artist": "True"}
    monkeypatch.setattr(soularr, "config", config)
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    soularr.lidarr.get_album.return_value = {"releases": [RELEASE]}
    soularr.lidarr.get_tracks.return_value = TRACKS
    monkeypatch.setattr(soularr, "use_selected_lidarr_release", True)
    monkeypatch.setattr(soularr, "search_blacklist", [])
    monkeypatch.setattr(soularr, "allowed_filetypes", ["flac"])
    monkeypatch.setattr(soularr, "delete_searches", False)
    monkeypatch.setattr(soularr, "search_cache", {})
    monkeypatch.setattr(soularr.time, "sleep", lambda seconds: None)
    return config


def use_slskd(monkeypatch, responses):
    slskd = FakeSlskd(responses)
    monkeypatch.setattr(soularr, "slskd", slskd)
    return slskd


def messages(caplog, prefix):
    return [record.getMessage() for record in caplog.records if record.getMessage().startswith(prefix)]


def test_prefixed_search_with_results_does_not_fall_back(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {f"{ARTIST} {TITLE}": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album(TITLE)) is True

    assert slskd.queries == [f"{ARTIST} {TITLE}"]
    assert messages(caplog, "Retrying search") == []
    assert soularr.search_cache[7]["peer"]["flac"] == ["Music\\Lady Gaga - The Fame Monster"]
    soularr.lidarr.get_tracks.assert_not_called()


def test_prefixed_search_without_results_retries_with_bare_title(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {TITLE: A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album(TITLE)) is True

    assert slskd.queries == [f"{ARTIST} {TITLE}", TITLE]
    assert messages(caplog, "Retrying search") == [f"Retrying search without artist: {TITLE}"]
    assert soularr.search_cache[7]["peer"]["flac"] == ["Music\\Lady Gaga - The Fame Monster"]


@pytest.mark.parametrize("title", ["X", "XO"])
def test_short_title_falls_through_to_title_plus_first_track(env, monkeypatch, caplog, title):
    slskd = use_slskd(monkeypatch, {f"{title} Bad Romance": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album(title)) is True

    # The bare title is under 3 characters, so it is skipped; the first track is the lowest-numbered one.
    assert slskd.queries == [f"{ARTIST} {title}", f"{title} Bad Romance"]
    assert messages(caplog, "Retrying search") == [f"Retrying search without artist: {title} Bad Romance"]
    soularr.lidarr.get_tracks.assert_called_once_with(artistId=3, albumId=7, albumReleaseId=11)


def test_bare_title_without_results_retries_with_title_plus_first_track(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {f"{TITLE} Bad Romance": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album(TITLE)) is True

    assert slskd.queries == [f"{ARTIST} {TITLE}", TITLE, f"{TITLE} Bad Romance"]
    assert messages(caplog, "Retrying search") == [
        f"Retrying search without artist: {TITLE}",
        f"Retrying search without artist: {TITLE} Bad Romance",
    ]


def test_all_retries_without_results_returns_false(env, monkeypatch):
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album(TITLE)) is False

    assert slskd.queries == [f"{ARTIST} {TITLE}", TITLE, f"{TITLE} Bad Romance"]
    assert 7 not in soularr.search_cache


def test_slskd_rejecting_a_query_counts_as_no_results(env, monkeypatch):
    # slskd_api does not raise on a 400: it returns the parsed body, or raises when the body is not JSON.
    slskd = use_slskd(
        monkeypatch,
        {
            f"{ARTIST} {TITLE}": BAD_REQUEST,
            TITLE: requests.exceptions.JSONDecodeError("Expecting value", BAD_REQUEST, 0),
            f"{TITLE} Bad Romance": A_RESPONSE,
        },
    )

    assert soularr.search_for_album(album(TITLE)) is True

    assert slskd.queries == [f"{ARTIST} {TITLE}", TITLE, f"{TITLE} Bad Romance"]


def test_fallback_can_be_turned_off(env, monkeypatch):
    env["Search Settings"]["search_fallback_bare_title"] = "False"
    slskd = use_slskd(monkeypatch, {TITLE: A_RESPONSE})

    assert soularr.search_for_album(album(TITLE)) is False

    assert slskd.queries == [f"{ARTIST} {TITLE}"]


def test_search_blacklist_still_applies_to_every_query(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_blacklist", ["Lady", "Bad Romance"])
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album(TITLE)) is False

    # The title + track query loses its track title and collapses to the already-tried bare title, so it is not searched again.
    assert slskd.queries == [f"Gaga {TITLE}", TITLE]


def test_without_album_prepend_artist_the_bare_title_is_not_searched_twice(env, monkeypatch):
    env["Search Settings"]["album_prepend_artist"] = "False"
    slskd = use_slskd(monkeypatch, {f"{TITLE} Bad Romance": A_RESPONSE})

    assert soularr.search_for_album(album(TITLE)) is True

    assert slskd.queries == [TITLE, f"{TITLE} Bad Romance"]


def test_unreachable_slskd_stops_the_chain(env, monkeypatch):
    slskd = use_slskd(monkeypatch, {f"{ARTIST} {TITLE}": requests.exceptions.ConnectionError("slskd is down")})

    assert soularr.search_for_album(album(TITLE)) is False

    assert slskd.queries == [f"{ARTIST} {TITLE}"]


def test_lidarr_tracks_unavailable_ends_the_chain_after_the_bare_title(env, monkeypatch):
    soularr.lidarr.get_tracks.side_effect = requests.exceptions.ConnectionError("lidarr is down")
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album(TITLE)) is False

    assert slskd.queries == [f"{ARTIST} {TITLE}", TITLE]


# --- generic titles skip the bare-title retry ----------------------------------------------------------------------


def test_one_word_title_skips_the_bare_title_retry(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {"Remixes Bad Romance": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album("Remixes")) is True

    assert slskd.queries == [f"{ARTIST} Remixes", "Remixes Bad Romance"]
    assert messages(caplog, "Skipping bare-title") == ["Skipping bare-title retry for generic title: Remixes"]
    assert messages(caplog, "Retrying search") == ["Retrying search without artist: Remixes Bad Romance"]


@pytest.mark.parametrize("title", ["Greatest Hits", "the best of", "B-Sides"])
def test_listed_generic_title_skips_the_bare_title_retry(env, monkeypatch, caplog, title):
    slskd = use_slskd(monkeypatch, {f"{title} Bad Romance": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album(title)) is True

    assert slskd.queries == [f"{ARTIST} {title}", f"{title} Bad Romance"]
    assert messages(caplog, "Skipping bare-title") == [f"Skipping bare-title retry for generic title: {title}"]


def test_multi_word_title_still_tries_the_bare_title_first(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album("Born This Way")) is False

    assert slskd.queries == [f"{ARTIST} Born This Way", "Born This Way", "Born This Way Bad Romance"]
    assert messages(caplog, "Skipping bare-title") == []


def test_empty_generic_list_disables_the_list_but_not_the_word_count_rule(env, monkeypatch):
    env["Search Settings"]["search_fallback_generic_titles"] = ""
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album("Greatest Hits")) is False
    assert slskd.queries == [f"{ARTIST} Greatest Hits", "Greatest Hits", "Greatest Hits Bad Romance"]

    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album("Remixes")) is False
    assert slskd.queries == [f"{ARTIST} Remixes", "Remixes Bad Romance"]


def test_configured_generic_list_replaces_the_default(env, monkeypatch):
    env["Search Settings"]["search_fallback_generic_titles"] = "Christmas Album, Live in Concert"
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album("Live In Concert")) is False
    assert slskd.queries == [f"{ARTIST} Live In Concert", "Live In Concert Bad Romance"]

    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album("Greatest Hits")) is False
    assert slskd.queries == [f"{ARTIST} Greatest Hits", "Greatest Hits", "Greatest Hits Bad Romance"]

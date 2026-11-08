"""
Tests for the search fallback chain (search_fallback_bare_title).

The Soulseek server silently returns nothing for searches containing some terms, several artist names among them, so
when the artist-prefixed search finds nothing soularr retries with the bare album title and then with the album title
plus the first track title.
"""
import configparser
import logging
from unittest import mock

import pytest
import requests

import soularr

ARTIST = "Lady Gaga"
RELEASE = {"id": 11, "monitored": True, "format": "CD", "trackCount": 2, "mediumCount": 1, "country": ["US"], "status": "Official", "media": [{}]}
TRACKS = [{"title": "Venus", "absoluteTrackNumber": 2}, {"title": "Aura", "absoluteTrackNumber": 1}]
A_RESPONSE = [{"username": "peer", "files": [{"filename": "Music\\Lady Gaga - ARTPOP\\01 - Aura.flac"}]}]
BAD_REQUEST = "The search text must contain at least one term of 3 or more characters"


def album(title):
    return {"id": 7, "artistId": 3, "title": title, "artist": {"artistName": ARTIST}, "releaseDate": "2013-11-06"}


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


def retries(caplog):
    return [record.getMessage() for record in caplog.records if record.getMessage().startswith("Retrying search")]


def test_prefixed_search_with_results_does_not_fall_back(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {"Lady Gaga ARTPOP": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album("ARTPOP")) is True

    assert slskd.queries == ["Lady Gaga ARTPOP"]
    assert retries(caplog) == []
    assert soularr.search_cache[7]["peer"]["flac"] == ["Music\\Lady Gaga - ARTPOP"]
    soularr.lidarr.get_tracks.assert_not_called()


def test_prefixed_search_without_results_retries_with_bare_title(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {"ARTPOP": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album("ARTPOP")) is True

    assert slskd.queries == ["Lady Gaga ARTPOP", "ARTPOP"]
    assert retries(caplog) == ["Retrying search without artist: ARTPOP"]
    assert soularr.search_cache[7]["peer"]["flac"] == ["Music\\Lady Gaga - ARTPOP"]


@pytest.mark.parametrize("title", ["X", "XO"])
def test_short_title_falls_through_to_title_plus_first_track(env, monkeypatch, caplog, title):
    slskd = use_slskd(monkeypatch, {f"{title} Aura": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album(title)) is True

    # The bare title is under 3 characters, so it is skipped; the first track is the lowest-numbered one.
    assert slskd.queries == [f"Lady Gaga {title}", f"{title} Aura"]
    assert retries(caplog) == [f"Retrying search without artist: {title} Aura"]
    soularr.lidarr.get_tracks.assert_called_once_with(artistId=3, albumId=7, albumReleaseId=11)


def test_bare_title_without_results_retries_with_title_plus_first_track(env, monkeypatch, caplog):
    slskd = use_slskd(monkeypatch, {"ARTPOP Aura": A_RESPONSE})

    with caplog.at_level(logging.INFO, logger="soularr"):
        assert soularr.search_for_album(album("ARTPOP")) is True

    assert slskd.queries == ["Lady Gaga ARTPOP", "ARTPOP", "ARTPOP Aura"]
    assert retries(caplog) == ["Retrying search without artist: ARTPOP", "Retrying search without artist: ARTPOP Aura"]


def test_all_retries_without_results_returns_false(env, monkeypatch):
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album("ARTPOP")) is False

    assert slskd.queries == ["Lady Gaga ARTPOP", "ARTPOP", "ARTPOP Aura"]
    assert 7 not in soularr.search_cache


def test_slskd_rejecting_a_query_counts_as_no_results(env, monkeypatch):
    # slskd_api does not raise on a 400: it returns the parsed body, or raises when the body is not JSON.
    slskd = use_slskd(
        monkeypatch,
        {
            "Lady Gaga ARTPOP": BAD_REQUEST,
            "ARTPOP": requests.exceptions.JSONDecodeError("Expecting value", BAD_REQUEST, 0),
            "ARTPOP Aura": A_RESPONSE,
        },
    )

    assert soularr.search_for_album(album("ARTPOP")) is True

    assert slskd.queries == ["Lady Gaga ARTPOP", "ARTPOP", "ARTPOP Aura"]


def test_fallback_can_be_turned_off(env, monkeypatch):
    env["Search Settings"]["search_fallback_bare_title"] = "False"
    slskd = use_slskd(monkeypatch, {"ARTPOP": A_RESPONSE})

    assert soularr.search_for_album(album("ARTPOP")) is False

    assert slskd.queries == ["Lady Gaga ARTPOP"]


def test_search_blacklist_still_applies_to_every_query(env, monkeypatch):
    monkeypatch.setattr(soularr, "search_blacklist", ["Lady", "Aura"])
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album("ARTPOP")) is False

    # "ARTPOP Aura" loses its track title and collapses to the already-tried bare title, so it is not searched again.
    assert slskd.queries == ["Gaga ARTPOP", "ARTPOP"]


def test_without_album_prepend_artist_the_bare_title_is_not_searched_twice(env, monkeypatch):
    env["Search Settings"]["album_prepend_artist"] = "False"
    slskd = use_slskd(monkeypatch, {"ARTPOP Aura": A_RESPONSE})

    assert soularr.search_for_album(album("ARTPOP")) is True

    assert slskd.queries == ["ARTPOP", "ARTPOP Aura"]


def test_unreachable_slskd_stops_the_chain(env, monkeypatch):
    slskd = use_slskd(monkeypatch, {"Lady Gaga ARTPOP": requests.exceptions.ConnectionError("slskd is down")})

    assert soularr.search_for_album(album("ARTPOP")) is False

    assert slskd.queries == ["Lady Gaga ARTPOP"]


def test_lidarr_tracks_unavailable_ends_the_chain_after_the_bare_title(env, monkeypatch):
    soularr.lidarr.get_tracks.side_effect = requests.exceptions.ConnectionError("lidarr is down")
    slskd = use_slskd(monkeypatch, {})

    assert soularr.search_for_album(album("ARTPOP")) is False

    assert slskd.queries == ["Lady Gaga ARTPOP", "ARTPOP"]

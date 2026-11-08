"""Tests for use_selected_lidarr_release_for_singles: singles and EPs follow the release selected in Lidarr."""
import pytest

import soularr


def release(release_id, track_count, monitored=False, fmt="CD"):
    return {
        "id": release_id,
        "monitored": monitored,
        "format": fmt,
        "trackCount": track_count,
        "mediumCount": 1,
        "country": ["United States"],
        "status": "Official",
        "media": [{}],
    }


# Three CD singles with 3 tracks win on track count; the user selected the 1-track digital release in Lidarr.
RELEASES = [release(1, 3), release(2, 3), release(3, 3), release(4, 1, monitored=True, fmt="Digital Media")]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(soularr.logger, "disabled", True)
    monkeypatch.setattr(soularr, "use_selected_lidarr_release", False)
    monkeypatch.setattr(soularr, "use_selected_lidarr_release_for_singles", True)
    monkeypatch.setattr(soularr, "use_most_common_tracknum", True)
    monkeypatch.setattr(soularr, "allow_multi_disc", True)
    monkeypatch.setattr(soularr, "accepted_countries", ["United States"])
    monkeypatch.setattr(soularr, "skip_region_check", False)
    monkeypatch.setattr(soularr, "accepted_formats", ["CD", "Digital Media"])


@pytest.mark.parametrize("album_type", ["Single", "EP", "single"])
def test_single_or_ep_uses_the_release_selected_in_lidarr(env, album_type):
    assert soularr.choose_release("The Killers", list(RELEASES), album_type)["id"] == 4


def test_album_keeps_the_most_common_track_count_release(env):
    assert soularr.choose_release("The Killers", list(RELEASES), "Album")["id"] == 1


def test_no_album_type_keeps_the_most_common_track_count_release(env):
    assert soularr.choose_release("The Killers", list(RELEASES))["id"] == 1


def test_single_without_a_selected_release_falls_back_to_the_usual_logic(env):
    releases = [release(1, 3), release(2, 3), release(3, 1, fmt="Digital Media")]

    assert soularr.choose_release("The Killers", releases, "Single")["id"] == 1


def test_option_off_treats_singles_like_albums(env, monkeypatch):
    monkeypatch.setattr(soularr, "use_selected_lidarr_release_for_singles", False)

    assert soularr.choose_release("The Killers", list(RELEASES), "Single")["id"] == 1


def test_global_option_still_applies_to_albums(env, monkeypatch):
    monkeypatch.setattr(soularr, "use_selected_lidarr_release", True)

    assert soularr.choose_release("The Killers", list(RELEASES), "Album")["id"] == 4

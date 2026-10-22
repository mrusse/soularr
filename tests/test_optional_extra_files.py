"""#194: a failed or stuck extra file (.nfo, .jpg, .cue) must not fail an album whose audio downloaded."""
import os
from unittest import mock

import pytest

import soularr

DIR = "music\\Heart\\Fanatic (2012)"
AUDIO = ["01 - Fanatic.flac", "02 - Dear Old America.flac"]


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0
        self.sleeps = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 5_000:
            raise AssertionError("monitor loop did not terminate")
        self.now += seconds


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(soularr.time, "time", clock.time)
    monkeypatch.setattr(soularr.time, "sleep", clock.sleep)
    monkeypatch.setattr(soularr, "slskd", mock.MagicMock())
    monkeypatch.setattr(soularr, "lidarr", mock.MagicMock())
    monkeypatch.setattr(soularr, "slskd_download_dir", str(tmp_path))
    monkeypatch.setattr(soularr, "stalled_timeout", 3600)
    monkeypatch.setattr(soularr, "remote_queue_timeout", 300)
    monkeypatch.setattr(soularr, "ignore_failed_users", True)
    monkeypatch.setattr(soularr, "failed_user_ignore_hours", 168)
    monkeypatch.setattr(soularr, "failed_users", {})
    monkeypatch.setattr(soularr, "failed_users_file_path", str(tmp_path / "failed_users.json"))
    monkeypatch.setattr(soularr.logger, "disabled", True)
    soularr.lidarr.get_album.return_value = {"id": 42, "title": "Fanatic", "artist": {"artistName": "Heart"}}
    soularr.slskd.transfers.enqueue.return_value = True
    soularr.slskd.transfers.get_downloads.return_value = {"directories": []}
    cwd = os.getcwd()
    yield tmp_path
    os.chdir(cwd)


def album(*extras):
    names = AUDIO + list(extras)
    files = [{"filename": f"{DIR}\\{n}", "id": n, "file_dir": DIR, "username": "peer", "size": 10} for n in names]
    return {42: {"files": files, "filetype": "flac", "title": "Fanatic", "artist": "Heart", "year": "2012"}}


def on_disk(root, *names):
    folder = root / "Fanatic (2012)"
    folder.mkdir(exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"x")


def states(mapping):
    soularr.slskd.transfers.get_download.side_effect = lambda user, id: {"state": mapping[id]}


def capture_processed(monkeypatch):
    processed = []
    monkeypatch.setattr(
        soularr, "process_completed_album", lambda data, fg: processed.append([f["filename"].split("\\")[-1] for f in data["files"]])
    )
    return processed


def test_failed_nfo_does_not_fail_the_album(env, monkeypatch):
    """The exact case in #194: FLACs and art succeed, album.nfo keeps erroring."""
    on_disk(env, *AUDIO, "albumart.jpg")
    states({AUDIO[0]: "Completed, Succeeded", AUDIO[1]: "Completed, Succeeded",
            "albumart.jpg": "Completed, Succeeded", "album.nfo": "Completed, Errored"})
    processed = capture_processed(monkeypatch)
    failed_grab = []

    soularr.monitor_downloads(album("albumart.jpg", "album.nfo"), failed_grab)

    assert processed == [AUDIO + ["albumart.jpg"]]
    assert failed_grab == []
    assert soularr.failed_users == {}, "user was blamed for an .nfo"
    soularr.slskd.transfers.enqueue.assert_not_called()  # no requeue churn for extras


def test_stuck_extra_does_not_hold_the_album(env, monkeypatch):
    """A .jpg stuck in the peer's queue used to keep the album waiting until a timeout deleted it."""
    on_disk(env, *AUDIO)
    states({AUDIO[0]: "Completed, Succeeded", AUDIO[1]: "Completed, Succeeded", "cover.jpg": "Queued, Remotely"})
    processed = capture_processed(monkeypatch)

    soularr.monitor_downloads(album("cover.jpg"), [])

    assert processed == [AUDIO]
    soularr.slskd.transfers.cancel_download.assert_called_once_with(username="peer", id="cover.jpg")


def test_extra_whose_status_lookup_fails_does_not_hold_the_album(env, monkeypatch):
    on_disk(env, *AUDIO)

    def get_download(user, id):
        if id == "info.txt":
            raise Exception("404")
        return {"state": "Completed, Succeeded"}

    soularr.slskd.transfers.get_download.side_effect = get_download
    processed = capture_processed(monkeypatch)

    soularr.monitor_downloads(album("info.txt"), [])

    assert processed == [AUDIO]


def test_downloaded_extra_is_still_waited_for_and_imported(env, monkeypatch):
    on_disk(env, *AUDIO)  # cover.jpg reported done but not moved yet
    states({AUDIO[0]: "Completed, Succeeded", AUDIO[1]: "Completed, Succeeded", "cover.jpg": "Completed, Succeeded"})
    processed = capture_processed(monkeypatch)
    original_sleep = soularr.time.sleep

    def sleep_then_move(seconds):
        original_sleep(seconds)
        on_disk(env, "cover.jpg")

    monkeypatch.setattr(soularr.time, "sleep", sleep_then_move)

    soularr.monitor_downloads(album("cover.jpg"), [])

    assert processed == [AUDIO + ["cover.jpg"]]


def test_failed_audio_still_fails_the_album_and_blames_only_its_user(env, monkeypatch):
    files = album("cover.jpg")
    files[42]["files"][2]["username"] = "artpeer"  # extras from a different user
    states({AUDIO[0]: "Completed, Succeeded", AUDIO[1]: "Completed, Errored", "cover.jpg": "Queued, Remotely"})
    processed = capture_processed(monkeypatch)
    failed_grab = []

    soularr.monitor_downloads(files, failed_grab)

    assert processed == []
    assert len(failed_grab) == 1
    assert list(soularr.failed_users) == ["peer"]


def test_remote_queue_timeout_counts_audio_only(env, monkeypatch):
    """All audio stuck in the remote queue still times out even though the extras finished."""
    on_disk(env, "cover.jpg")
    states({AUDIO[0]: "Queued, Remotely", AUDIO[1]: "Queued, Remotely", "cover.jpg": "Completed, Succeeded"})
    processed = capture_processed(monkeypatch)
    failed_grab = []

    soularr.monitor_downloads(album("cover.jpg"), failed_grab)

    assert processed == []
    assert len(failed_grab) == 1
    assert soularr.time.time() - 1_000_000.0 < soularr.stalled_timeout  # remote_queue_timeout, not stalled_timeout


def test_end_to_end_import_skips_the_missing_nfo(env, monkeypatch):
    """Real process_completed_album: before the fix a missing extra meant FileNotFoundError and rollback."""
    monkeypatch.setattr(soularr, "rename_download_folders", True)
    monkeypatch.setattr(soularr, "lidarr_disable_sync", True)
    monkeypatch.setattr(soularr, "lidarr_download_dir", "/lidarr")
    on_disk(env, *AUDIO)
    states({AUDIO[0]: "Completed, Succeeded", AUDIO[1]: "Completed, Succeeded", "album.nfo": "Completed, Errored"})
    failed_grab = []

    soularr.monitor_downloads(album("album.nfo"), failed_grab)

    assert failed_grab == []
    assert sorted(os.listdir(env / "Heart - Fanatic (2012)")) == sorted(AUDIO)

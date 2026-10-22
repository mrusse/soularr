"""The web UI log stream must follow soularr.log across rotation and send keepalives while idle."""
import importlib.util
import os
import pathlib

import pytest

spec = importlib.util.spec_from_file_location("webui", pathlib.Path(__file__).parents[1] / "webui" / "webui.py")
webui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(webui)


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "soularr.log"
    path.write_text("one\ntwo\n")
    return path


def drive(monkeypatch, actions):
    """Replace time.sleep: each idle tick runs the next action; fail if the stream never moves on."""
    ticks = {"n": 0}

    def fake_sleep(seconds):
        ticks["n"] += 1
        if ticks["n"] > 1000:
            raise AssertionError("stream stopped producing lines")
        if actions:
            actions.pop(0)()

    monkeypatch.setattr(webui.time, "sleep", fake_sleep)
    return ticks


def rotate(path, new_text):
    """What RotatingFileHandler does: rename the full log, start a new one."""
    def action():
        os.replace(path, f"{path}.1")
        path.write_text(new_text)
    return action


def test_streams_existing_lines(log, monkeypatch):
    drive(monkeypatch, [])
    stream = webui.follow_log(str(log))

    assert [next(stream), next(stream)] == ["data: one\n\n", "data: two\n\n"]


def test_follows_new_file_after_rotation(log, monkeypatch):
    drive(monkeypatch, [rotate(log, "after rotation\n")])
    stream = webui.follow_log(str(log))
    next(stream), next(stream)

    assert next(stream) == "data: after rotation\n\n"


def test_lines_written_just_before_rotation_are_not_lost(log, monkeypatch):
    def append_then_rotate():
        with open(log, "a") as f:
            f.write("last line of old file\n")
        rotate(log, "first line of new file\n")()

    drive(monkeypatch, [append_then_rotate])
    stream = webui.follow_log(str(log))
    next(stream), next(stream)

    assert [next(stream), next(stream)] == ["data: last line of old file\n\n", "data: first line of new file\n\n"]


def test_waits_while_log_is_briefly_missing_during_rotation(log, monkeypatch):
    drive(monkeypatch, [lambda: os.replace(log, f"{log}.1"), lambda: None, lambda: log.write_text("back\n")])
    stream = webui.follow_log(str(log))
    next(stream), next(stream)

    assert next(stream) == "data: back\n\n"


def test_follows_truncated_log(log, monkeypatch):
    drive(monkeypatch, [lambda: log.write_text("x\n")])  # same file, now shorter than what was read
    stream = webui.follow_log(str(log))
    next(stream), next(stream)

    assert next(stream) == "data: x\n\n"


def test_sends_keepalive_when_idle(log, monkeypatch):
    ticks = drive(monkeypatch, [])
    stream = webui.follow_log(str(log))
    next(stream), next(stream)

    assert next(stream) == ": keepalive\n\n"
    assert ticks["n"] * webui.LOG_POLL_SECONDS >= webui.LOG_KEEPALIVE_SECONDS


def test_closing_the_stream_closes_the_file(log, monkeypatch):
    drive(monkeypatch, [])
    stream = webui.follow_log(str(log))
    next(stream)
    handle = stream.gi_frame.f_locals["f"]

    stream.close()

    assert handle.closed


def test_stream_endpoint_follows_rotation(log, monkeypatch):
    """End to end through /stream. On the old code the stream stayed on the renamed file and froze."""
    monkeypatch.setattr(webui, "get_var_dir", lambda: str(log.parent))
    drive(monkeypatch, [rotate(log, "after rotation\n")])
    response = webui.app.test_client().get("/stream", buffered=False)
    stream = iter(response.response)

    received = [next(stream) for _ in range(3)]

    assert [r if isinstance(r, str) else r.decode() for r in received] == [
        "data: one\n\n",
        "data: two\n\n",
        "data: after rotation\n\n",
    ]
    response.close()

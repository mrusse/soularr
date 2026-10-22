"""A peer whose folder can't be browsed is routine on Soulseek: one WARNING line, no ERROR traceback."""
import logging
from unittest import mock

import pytest
import requests

import soularr


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(soularr, "slskd", mock.MagicMock())
    monkeypatch.setattr(soularr, "folder_cache", {})
    monkeypatch.setattr(soularr, "broken_user", [])
    soularr.slskd.application.version.return_value = "0.26.0"


def http_500():
    response = requests.Response()
    response.status_code = 500
    return requests.exceptions.HTTPError("500 Server Error", response=response)


@pytest.mark.parametrize(
    "error, reason",
    [
        (http_500(), "slskd HTTP 500"),  # what slskd returns when the peer can't be reached
        (requests.exceptions.ReadTimeout("read timed out"), "ReadTimeout"),
    ],
)
def test_browse_failure_is_one_warning_line(env, caplog, error, reason):
    soularr.slskd.users.directory.side_effect = error
    caplog.set_level(logging.DEBUG, logger="soularr")

    result = soularr.check_for_match([{}], "flac", ["Music\\Album"], "overwheat")

    assert result == (False, {}, "")
    assert soularr.broken_user == ["overwheat"]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], "logged as an error"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert '"overwheat"' in message and "Music\\Album" in message and reason in message
    assert "rest of the run" in message
    assert warnings[0].exc_info is None, "traceback attached to the warning"
    assert any(r.levelno == logging.DEBUG and r.exc_info for r in caplog.records), "traceback should still be available at DEBUG"


def test_user_is_not_browsed_again_in_the_same_run(env):
    soularr.slskd.users.directory.side_effect = http_500()

    soularr.check_for_match([{}], "flac", ["Music\\Album"], "overwheat")
    soularr.check_for_match([{}], "flac", ["Music\\Other"], "overwheat")

    assert soularr.slskd.users.directory.call_count == 1

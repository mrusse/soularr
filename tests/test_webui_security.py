"""Web UI access control: optional login, DNS-rebinding guard, masked secrets, confined delete, headers."""
import base64
import importlib.util
import json
import pathlib

import pytest

spec = importlib.util.spec_from_file_location("webui", pathlib.Path(__file__).parents[1] / "webui" / "webui.py")
webui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(webui)

CONFIG = """[Lidarr]
# Get from Lidarr: Settings > General > Security
api_key = lidarr-secret-123
host_url = http://lidarr:8686
download_dir = /data/slskd_downloads

[Slskd]
api_key = ${SLSKD_API_KEY}
host_url = http://slskd:5030
download_dir = {downloads}

[Search Settings]
search_timeout = 5000
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    for var in ("WEBUI_PASSWORD", "WEBUI_USERNAME", "WEBUI_ALLOWED_HOSTS"):
        monkeypatch.delenv(var, raising=False)
    downloads = tmp_path / "downloads"
    (downloads / "failed_imports").mkdir(parents=True)
    (tmp_path / "config.ini").write_text(CONFIG.replace("{downloads}", str(downloads)))
    monkeypatch.setattr(webui, "get_var_dir", lambda: str(tmp_path))
    webui.logger.disabled = True
    return tmp_path


def client(host="10.0.0.6:8265"):
    return webui.app.test_client(), {"base_url": f"http://{host}"}


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


# --- DNS-rebinding guard (no password set) ---------------------------------------------------------


@pytest.mark.parametrize("host", ["10.0.0.6:8265", "127.0.0.1", "[::1]:8265", "localhost:8265", "tower", "unraid.local", "soularr.lan:18265", "nas.home.arpa"])
def test_local_hosts_allowed_without_password(env, host):
    c, kw = client(host)
    assert c.get("/api/config", **kw).status_code == 200


@pytest.mark.parametrize("path, method", [("/", "get"), ("/api/config", "get"), ("/api/config", "post"), ("/stream", "get"), ("/api/failed-imports", "get"), ("/api/failed-imports/1", "delete")])
def test_public_hostname_refused_without_password(env, path, method):
    """What a DNS-rebinding page would send: its own public hostname, pointed at the LAN IP."""
    c, kw = client("evil.example.com")
    response = getattr(c, method)(path, json={"content": "x"} if method == "post" else None, **kw)

    assert response.status_code == 403
    assert b"WEBUI_PASSWORD" in response.data and b"WEBUI_ALLOWED_HOSTS" in response.data
    assert b"lidarr-secret-123" not in response.data


def test_allowed_hosts_setting(env, monkeypatch):
    monkeypatch.setenv("WEBUI_ALLOWED_HOSTS", "soularr.example.com, other.example.com")
    c, kw = client("Soularr.Example.com:443")
    assert c.get("/api/config", **kw).status_code == 200

    monkeypatch.setenv("WEBUI_ALLOWED_HOSTS", "*")
    c, kw = client("anything.example.net")
    assert c.get("/api/config", **kw).status_code == 200


# --- login ---------------------------------------------------------------------------------------------


def test_password_required_on_every_route(env, monkeypatch):
    monkeypatch.setenv("WEBUI_PASSWORD", "hunter2")
    c, kw = client()
    for path in ("/", "/api/config", "/stream", "/api/failed-imports", "/static/app.js"):
        response = c.get(path, **kw)
        assert response.status_code == 401, path
        assert response.headers["WWW-Authenticate"].startswith("Basic")


def test_wrong_and_right_credentials(env, monkeypatch):
    monkeypatch.setenv("WEBUI_PASSWORD", "hunter2")
    c, kw = client()

    assert c.get("/api/config", headers=basic("soularr", "nope"), **kw).status_code == 401
    assert c.get("/api/config", headers=basic("admin", "hunter2"), **kw).status_code == 401
    assert c.get("/api/config", headers=basic("soularr", "hunter2"), **kw).status_code == 200


def test_custom_username_and_non_ascii_password(env, monkeypatch):
    monkeypatch.setenv("WEBUI_USERNAME", "earl")
    monkeypatch.setenv("WEBUI_PASSWORD", "pässwörd")
    c, kw = client()

    assert c.get("/api/config", headers=basic("earl", "pässwörd"), **kw).status_code == 200
    assert c.get("/api/config", headers=basic("earl", "passwort"), **kw).status_code == 401


def test_password_set_allows_any_hostname(env, monkeypatch):
    """Behind a reverse proxy with a password, the Host check isn't needed (the browser won't send
    the credentials to a rebinding attacker's hostname)."""
    monkeypatch.setenv("WEBUI_PASSWORD", "hunter2")
    c, kw = client("soularr.example.com")
    assert c.get("/api/config", headers=basic("soularr", "hunter2"), **kw).status_code == 200


# --- masked secrets ------------------------------------------------------------------------------------


def test_config_editor_masks_secrets(env):
    c, kw = client()
    content = c.get("/api/config", **kw).get_json()["content"]

    assert "lidarr-secret-123" not in content and "SLSKD_API_KEY" not in content
    assert content.count(webui.SECRET_PLACEHOLDER) == 2
    assert "# Get from Lidarr: Settings > General > Security" in content
    assert "host_url = http://lidarr:8686" in content


def test_saving_masked_config_keeps_stored_secrets(env):
    c, kw = client()
    content = c.get("/api/config", **kw).get_json()["content"]
    edited = content.replace("search_timeout = 5000", "search_timeout = 9000")

    assert c.post("/api/config", json={"content": edited}, **kw).get_json()["ok"]

    saved = (env / "config.ini").read_text()
    assert saved == CONFIG.replace("{downloads}", str(env / "downloads")).replace("search_timeout = 5000", "search_timeout = 9000")


def test_saving_a_new_secret_value(env):
    c, kw = client()
    content = c.get("/api/config", **kw).get_json()["content"]
    edited = content.replace(f"api_key = {webui.SECRET_PLACEHOLDER}", "api_key = rotated-456", 1)

    c.post("/api/config", json={"content": edited}, **kw)

    saved = (env / "config.ini").read_text()
    assert "api_key = rotated-456" in saved and "lidarr-secret-123" not in saved
    assert "api_key = ${SLSKD_API_KEY}" in saved


def test_placeholder_without_stored_value_is_rejected(env):
    c, kw = client()
    before = (env / "config.ini").read_text()
    edited = before + f"\n[Extra]\npassword = {webui.SECRET_PLACEHOLDER}\n"

    response = c.post("/api/config", json={"content": edited}, **kw)

    assert response.status_code == 400
    assert "[Extra] password" in response.get_json()["error"]
    assert (env / "config.ini").read_text() == before


def test_mask_round_trip_keeps_line_endings():
    original = "[Lidarr]\r\napi_key = abc  \r\nhost_url = x\r\n"
    masked = webui.mask_secrets(original)

    assert masked == f"[Lidarr]\r\napi_key = {webui.SECRET_PLACEHOLDER}  \r\nhost_url = x\r\n"
    assert webui.unmask_secrets(masked, original) == original


# --- confined delete -----------------------------------------------------------------------------------


def write_failed(env, folder):
    (env / "failed_imports.json").write_text(json.dumps({"7": {"album_id": 7, "folder_path": str(folder)}}))


def test_delete_removes_folder_inside_failed_imports(env):
    folder = env / "downloads" / "failed_imports" / "Artist - Album"
    folder.mkdir()
    write_failed(env, folder)
    c, kw = client()

    assert c.delete("/api/failed-imports/7", **kw).get_json() == {"ok": True, "folder_deleted": True}
    assert not folder.exists()


@pytest.mark.parametrize("where", ["outside", "root", "traversal"])
def test_delete_refuses_folders_outside_failed_imports(env, where):
    outside = env / "music"
    outside.mkdir()
    (outside / "keep.flac").write_text("x")
    folder = {
        "outside": outside,
        "root": env / "downloads" / "failed_imports",
        "traversal": env / "downloads" / "failed_imports" / ".." / ".." / "music",
    }[where]
    write_failed(env, folder)
    c, kw = client()

    assert c.delete("/api/failed-imports/7", **kw).get_json() == {"ok": True, "folder_deleted": False}
    assert (outside / "keep.flac").exists()
    assert (env / "downloads" / "failed_imports").exists()
    assert json.loads((env / "failed_imports.json").read_text()) == {}


# --- headers -------------------------------------------------------------------------------------------


def test_security_headers(env):
    c, kw = client()
    response = c.get("/api/config", **kw)

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert response.headers["X-Content-Type-Options"] == "nosniff"

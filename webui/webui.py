import os
import re
import hmac
import json
import shutil
import ipaddress
import time
import logging
import configparser
import argparse
from datetime import datetime, timezone
from flask import Flask, Response, render_template, send_from_directory, jsonify, request
from waitress import serve

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger(__name__)


def _fmt(msg, level="INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
    return f"[{level}|webui] {ts}: {msg}"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCES_DIR = os.path.join(BASE_DIR, "..", "resources")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    template_folder="templates",
    static_folder=RESOURCES_DIR,
    static_url_path="/resources",
)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# === Access control ===
# WEBUI_PASSWORD (optional WEBUI_USERNAME, default "soularr"): require HTTP Basic auth on every route.
# Without a password the UI stays open, but only answers to IP addresses, localhost and local
# names (or hosts listed in WEBUI_ALLOWED_HOSTS), so a web page on another site can't reach it
# through DNS rebinding and read the API keys in config.ini.
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".home.arpa", ".localhost")


def webui_credentials():
    return os.environ.get("WEBUI_USERNAME", "soularr"), os.environ.get("WEBUI_PASSWORD", "")


def split_host(host_header):
    """'[::1]:8265' -> '::1', 'tower:8265' -> 'tower', 'Unraid.local.' -> 'unraid.local'."""
    host = (host_header or "").strip()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host.rstrip(".").lower()


def host_allowed(host_header):
    allowed = [h.strip().lower() for h in os.environ.get("WEBUI_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if "*" in allowed:
        return True
    host = split_host(host_header)
    if not host:
        return False
    if host in allowed or host == "localhost" or "." not in host or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def credentials_match(auth, username, password):
    if auth is None or auth.type != "basic":
        return False
    user_ok = hmac.compare_digest((auth.username or "").encode(), username.encode())
    pass_ok = hmac.compare_digest((auth.password or "").encode(), password.encode())
    return user_ok and pass_ok


@app.before_request
def check_access():
    username, password = webui_credentials()
    if password:
        if not credentials_match(request.authorization, username, password):
            return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Soularr", charset="UTF-8"'})
        return None
    if not host_allowed(request.host):
        host = split_host(request.host)
        logger.warning(f"Refused web UI request for host {host!r}; set WEBUI_PASSWORD or add it to WEBUI_ALLOWED_HOSTS")
        message = (
            f"Soularr's web UI refused this request for host '{host}'.\n\n"
            "Without a password the web UI only answers to IP addresses, localhost and local names, "
            "so other websites can't read your API keys through it. To use this hostname, either set "
            "WEBUI_PASSWORD (recommended) or add the host to WEBUI_ALLOWED_HOSTS.\n"
        )
        return Response(message, 403, mimetype="text/plain")
    return None


@app.after_request
def security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# === Secrets in the config editor ===
SECRET_PLACEHOLDER = "********"
SECRET_KEY = re.compile(r"api_?key|password|passwd|token|secret", re.IGNORECASE)
SECTION_LINE = re.compile(r"^\s*\[([^\]]+)\]")
OPTION_LINE = re.compile(r"^(\s*)([^#;\s\[][^=:]*?)(\s*[=:]\s*)(.*?)(\s*)$")


def _secret_options(content):
    """Yield (line index, section, key, match) for every secret option line in a config.ini text."""
    section = None
    for index, line in enumerate(content.splitlines(keepends=True)):
        header = SECTION_LINE.match(line)
        if header:
            section = header.group(1).strip()
            continue
        option = OPTION_LINE.match(line.rstrip("\r\n"))
        if option and SECRET_KEY.search(option.group(2)):
            yield index, section, option.group(2).strip().lower(), option


def mask_secrets(content):
    """Replace secret values (API keys, passwords) with a placeholder, keeping everything else as-is."""
    lines = content.splitlines(keepends=True)
    for index, _section, _key, option in _secret_options(content):
        if option.group(4):
            ending = lines[index][len(lines[index].rstrip("\r\n")):]
            lines[index] = f"{option.group(1)}{option.group(2)}{option.group(3)}{SECRET_PLACEHOLDER}{option.group(5)}{ending}"
    return "".join(lines)


def unmask_secrets(new_content, old_content):
    """Put the stored values back wherever the edited config still has the placeholder."""
    stored = {(section, key): option.group(4) for _i, section, key, option in _secret_options(old_content)}
    lines = new_content.splitlines(keepends=True)
    for index, section, key, option in _secret_options(new_content):
        if option.group(4) != SECRET_PLACEHOLDER:
            continue
        if (section, key) not in stored or stored[(section, key)] == SECRET_PLACEHOLDER:
            raise ValueError(f"[{section}] {option.group(2).strip()} is masked but has no saved value; enter the real value")
        ending = lines[index][len(lines[index].rstrip("\r\n")):]
        lines[index] = f"{option.group(1)}{option.group(2)}{option.group(3)}{stored[(section, key)]}{option.group(5)}{ending}"
    return "".join(lines)

def get_var_dir():
    parser = argparse.ArgumentParser(add_help=False)
    default = "/data" if os.environ.get("IN_DOCKER") else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--var-dir", default=default)
    args, _ = parser.parse_known_args()
    return args.var_dir


def get_config_path(var_dir):
    for path in [os.path.join(var_dir, "config.ini"), "config.ini"]:
        if os.path.exists(path):
            return path
    return os.path.join(var_dir, "config.ini")


def get_log_path(var_dir):
    config = configparser.ConfigParser()
    for path in [os.path.join(var_dir, "config.ini"), "config.ini"]:
        if os.path.exists(path):
            config.read(path)
            break
    log_file = config.get("Logging", "log_file", fallback="soularr.log")
    return os.path.join(var_dir, log_file)

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    config_path = get_config_path(get_var_dir())
    if not os.path.exists(config_path):
        return jsonify({"content": "", "path": config_path, "exists": False})
    with open(config_path, "r") as f:
        content = f.read()
    return jsonify({"content": mask_secrets(content), "path": config_path, "exists": True})


@app.route("/api/config", methods=["POST"])
def save_config():
    config_path = get_config_path(get_var_dir())
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "No content provided"}), 400
    try:
        old_content = ""
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                old_content = f.read()
        try:
            content = unmask_secrets(data["content"], old_content)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        with open(config_path, "w") as f:
            f.write(content)
        logger.info(f"Config saved: {config_path}")
        return jsonify({"ok": True, "path": config_path})
    except Exception as e:
        logger.exception(f"Failed to save config: {config_path}")
        return jsonify({"error": str(e)}), 500


@app.route("/stream")
def stream():
    log_path = get_log_path(get_var_dir())

    def generate():
        while not os.path.exists(log_path):
            config = configparser.ConfigParser()
            config.read(get_config_path(get_var_dir()))
            log_to_file = config.getboolean("Logging", "log_to_file", fallback=False)
            if not log_to_file:
                yield f"data: {_fmt('Log file not found. Make sure log_to_file = True is set in your config.ini')}\n\n"
            else:
                yield f"data: {_fmt(f'Waiting for log file: {log_path}')}\n\n"
            time.sleep(5)
        with open(log_path, "r") as f:
            for line in f:
                line = line.rstrip("\n")
                if line:
                    yield f"data: {line}\n\n"
            while True:
                line = f.readline()
                if line:
                    line = line.rstrip("\n")
                    if line:
                        yield f"data: {line}\n\n"
                else:
                    time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

def get_failed_imports_path(var_dir):
    return os.path.join(var_dir, "failed_imports.json")


@app.route("/api/failed-imports", methods=["GET"])
def get_failed_imports():
    path = get_failed_imports_path(get_var_dir())
    if not os.path.exists(path):
        return jsonify([])
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return jsonify(list(data.values()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def inside_failed_imports_dir(folder):
    """Only ever rmtree a folder inside <slskd download_dir>/failed_imports, where Soularr moves failed imports."""
    config = configparser.ConfigParser(interpolation=None)
    config.read(get_config_path(get_var_dir()))
    download_dir = config.get("Slskd", "download_dir", fallback="")
    if not download_dir:
        return False
    root = os.path.realpath(os.path.join(download_dir, "failed_imports"))
    target = os.path.realpath(folder)
    return target != root and os.path.commonpath([root, target]) == root


@app.route("/api/failed-imports/<album_id>", methods=["DELETE"])
def delete_failed_import(album_id):
    path = get_failed_imports_path(get_var_dir())
    if not os.path.exists(path):
        return jsonify({"ok": True})
    try:
        with open(path, "r") as f:
            data = json.load(f)
        entry = data.pop(str(album_id), None)
        folder_deleted = False
        folder = entry.get("folder_path") if entry else None
        if folder and os.path.isdir(folder):
            if inside_failed_imports_dir(folder):
                shutil.rmtree(folder)
                folder_deleted = True
                logger.info(f"Deleted failed import folder: {folder}")
            else:
                logger.warning(f"Not deleting {folder}: it isn't inside Soularr's failed_imports folder")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return jsonify({"ok": True, "folder_deleted": folder_deleted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Soularr Web UI")
    default = "/data" if os.environ.get("IN_DOCKER") else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--var-dir", default=default, help="Directory containing config.ini and soularr.log")
    parser.add_argument("--port", type=int, default=8265, help="Port to listen on (default: 8265)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    log_path = get_log_path(args.var_dir)
    logger.info(f"Soularr Web UI starting on http://{args.host}:{args.port}")
    if not webui_credentials()[1]:
        logger.warning("Web UI has no password: anyone who can reach it can read and change config.ini. Set WEBUI_PASSWORD to require a login.")
    logger.info(f"Reading log from: {log_path}")

    serve(app, host=args.host, port=args.port, threads=16)

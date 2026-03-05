import os
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

def get_var_dir():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--var-dir", default="/data")
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
    return jsonify({"content": content, "path": config_path, "exists": True})


@app.route("/api/config", methods=["POST"])
def save_config():
    config_path = get_config_path(get_var_dir())
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "No content provided"}), 400
    try:
        with open(config_path, "w") as f:
            f.write(data["content"])
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Soularr Web UI")
    parser.add_argument("--var-dir", default="/data", help="Directory containing config.ini and soularr.log")
    parser.add_argument("--port", type=int, default=8265, help="Port to listen on (default: 8265)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    log_path = get_log_path(args.var_dir)
    logger.info(f"Soularr Web UI starting on http://{args.host}:{args.port}")
    logger.info(f"Reading log from: {log_path}")

    serve(app, host=args.host, port=args.port, threads=16)

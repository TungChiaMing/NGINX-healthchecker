#!/usr/bin/env python3
"""Supervisor + control API for the split_clients demo.

Starts two real Nginx processes (legacy and new) and serves a small JSON API
on 127.0.0.1:9000 that the Legacy Nginx exposes under /api/.

Visitors may only change the split_clients block and the X-Canary map. Every
field is validated here, then Nginx itself has the last word via `nginx -t`.
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = "/run/split"
LOG_DIR = "/var/log/split"
LEGACY_CONF = os.path.join(RUN_DIR, "legacy.conf")
NEW_CONF = os.path.join(APP, "new.conf")
TEMPLATE = os.path.join(APP, "legacy.conf.tmpl")
PORT = os.environ.get("PORT", "10000")
API_PORT = 9000
NEW_ADDR = ("127.0.0.1", 8082)
NEW_DOWN_SECONDS = 120          # New Nginx comes back by itself after this
LOG_MAX_BYTES = 2 * 1024 * 1024
TRACE_TAIL_BYTES = 512 * 1024

KEYS = ["$request_id", "$remote_addr", "$arg_user", "$http_x_user"]
TARGETS = ["new_nginx", "legacy_nginx"]
MAX_ROWS = 8

DEFAULT_SETTINGS = {
    "key": "$request_id",
    "buckets": [
        {"percent": "50%", "target": "new_nginx"},
        {"percent": "*", "target": "legacy_nginx"},
    ],
    "canary": [
        {"match": "new", "target": "new_nginx"},
        {"match": "legacy", "target": "legacy_nginx"},
    ],
}

PERCENT_RE = re.compile(r"^\d{1,3}(\.\d{1,2})?%$")
MATCH_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")

lock = threading.Lock()
state = {
    "version": 0,
    "settings": DEFAULT_SETTINGS,
    "updated_at": time.time(),
    "new_down_until": 0,
}
restart_timer = None


class BadRequest(Exception):
    pass


def validate(raw):
    """Return a clean settings dict built only from whitelisted values."""
    if not isinstance(raw, dict):
        raise BadRequest("settings must be an object")

    key = raw.get("key")
    if key not in KEYS:
        raise BadRequest("split key must be one of: " + ", ".join(KEYS))

    buckets = raw.get("buckets")
    if not isinstance(buckets, list) or not 1 <= len(buckets) <= MAX_ROWS:
        raise BadRequest("split_clients needs 1 to %d buckets" % MAX_ROWS)
    clean_buckets = []
    for b in buckets:
        if not isinstance(b, dict):
            raise BadRequest("invalid bucket")
        percent, target = b.get("percent"), b.get("target")
        if percent != "*" and not (isinstance(percent, str) and PERCENT_RE.match(percent)):
            raise BadRequest('invalid percent "%s" (use e.g. 50%%, 0.5%% or *)' % str(percent)[:20])
        if target not in TARGETS:
            raise BadRequest("bucket target must be one of: " + ", ".join(TARGETS))
        clean_buckets.append({"percent": percent, "target": target})

    canary = raw.get("canary", [])
    if not isinstance(canary, list) or len(canary) > MAX_ROWS:
        raise BadRequest("the X-Canary map accepts at most %d entries" % MAX_ROWS)
    clean_canary = []
    for c in canary:
        if not isinstance(c, dict):
            raise BadRequest("invalid X-Canary entry")
        match, target = c.get("match"), c.get("target")
        if not (isinstance(match, str) and MATCH_RE.match(match)) or match in ("default", "include", "hostnames", "volatile"):
            raise BadRequest("X-Canary values may only use letters, digits, _ and -")
        if target not in TARGETS:
            raise BadRequest("X-Canary target must be one of: " + ", ".join(TARGETS))
        clean_canary.append({"match": match, "target": target})

    return {"key": key, "buckets": clean_buckets, "canary": clean_canary}


def render_editable(settings):
    lines = ["split_clients %s $split_target {" % settings["key"]]
    for b in settings["buckets"]:
        lines.append("    %-8s%s;" % (b["percent"], b["target"]))
    lines.append("}")
    lines.append("")
    lines.append("map $http_x_canary $route {")
    for c in settings["canary"]:
        lines.append("    %-8s%s;" % (c["match"], c["target"]))
    lines.append("    default $split_target;")
    lines.append("}")
    return "\n".join(lines)


def render_conf(settings):
    with open(TEMPLATE) as f:
        template = f.read()
    block = "\n".join(("    " + line) if line else "" for line in render_editable(settings).split("\n"))
    return template.replace("@@EDITABLE@@", block).replace("@@PORT@@", PORT)


def nginx(*args):
    return subprocess.run(["nginx", *args], capture_output=True, text=True, timeout=20)


def pid_alive(pid_file):
    try:
        with open(pid_file) as f:
            os.kill(int(f.read().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def new_is_up():
    try:
        with socket.create_connection(NEW_ADDR, timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_new(up):
    for _ in range(40):
        if new_is_up() == up:
            return
        time.sleep(0.05)


def apply_settings(settings):
    """Write the config, let Nginx test it, then reload. Caller holds the lock."""
    tmp = LEGACY_CONF + ".candidate"
    with open(tmp, "w") as f:
        f.write(render_conf(settings))
    test = nginx("-t", "-c", tmp)
    if test.returncode != 0:
        os.remove(tmp)
        lines = [l[len("nginx: "):] for l in test.stderr.splitlines() if l.startswith("nginx: ")]
        message = "\n".join(lines).replace(tmp, "nginx.conf").strip()
        raise BadRequest(message or "nginx -t rejected the configuration")
    os.replace(tmp, LEGACY_CONF)
    if pid_alive(os.path.join(RUN_DIR, "legacy.pid")):
        result = nginx("-s", "reload", "-c", LEGACY_CONF)
    else:
        result = nginx("-c", LEGACY_CONF)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    time.sleep(0.3)   # give the new worker time to take over from the old one
    state["settings"] = settings
    state["version"] += 1
    state["updated_at"] = time.time()


def start_new():
    global restart_timer
    with lock:
        if restart_timer:
            restart_timer.cancel()
            restart_timer = None
        if not new_is_up():
            nginx("-c", NEW_CONF)
            wait_for_new(True)
        state["new_down_until"] = 0
        state["version"] += 1


def stop_new():
    global restart_timer
    with lock:
        if new_is_up():
            nginx("-s", "stop", "-c", NEW_CONF)
            wait_for_new(False)
        if restart_timer:
            restart_timer.cancel()
        restart_timer = threading.Timer(NEW_DOWN_SECONDS, start_new)
        restart_timer.daemon = True
        restart_timer.start()
        state["new_down_until"] = time.time() + NEW_DOWN_SECONDS
        state["version"] += 1


def read_file(path):
    with open(path) as f:
        return f.read()


def snapshot():
    with lock:
        settings = state["settings"]
        return {
            "version": state["version"],
            "updated_at": state["updated_at"],
            "settings": settings,
            "editable": render_editable(settings),
            "legacy_conf": read_file(LEGACY_CONF),
            "new_conf": read_file(NEW_CONF),
            "new_up": new_is_up(),
            "new_down_until": state["new_down_until"],
            "keys": KEYS,
            "targets": TARGETS,
            "default_settings": DEFAULT_SETTINGS,
        }


def trace(request_id):
    """Access log lines from both Nginx processes for one request."""
    needle = '"request_id":"%s"' % request_id
    hops = []
    for name in ("legacy-access.log", "new-access.log"):
        path = os.path.join(LOG_DIR, name)
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - TRACE_TAIL_BYTES))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        for line in tail.splitlines():
            if needle in line:
                try:
                    hops.append(json.loads(line))
                except ValueError:
                    pass
    hops.sort(key=lambda h: float(h.get("t", 0)) - float(h.get("request_time", 0) or 0))
    return hops


def trim_logs():
    while True:
        time.sleep(60)
        for name in os.listdir(LOG_DIR):
            path = os.path.join(LOG_DIR, name)
            try:
                if os.path.getsize(path) > LOG_MAX_BYTES:
                    open(path, "w").close()   # Nginx appends, so truncating is safe
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 8192:
            raise BadRequest("request body too large")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise BadRequest("body is not valid JSON")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/state":
            return self.send_json(200, snapshot())
        if url.path == "/api/trace":
            request_id = (parse_qs(url.query).get("id") or [""])[0]
            if not REQUEST_ID_RE.match(request_id):
                return self.send_json(400, {"error": "invalid request id"})
            return self.send_json(200, {"hops": trace(request_id)})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/config":
                settings = validate(self.read_json())
                with lock:
                    apply_settings(settings)
            elif url.path == "/api/reset":
                with lock:
                    apply_settings(DEFAULT_SETTINGS)
                start_new()
            elif url.path == "/api/new-nginx":
                if self.read_json().get("up"):
                    start_new()
                else:
                    stop_new()
            else:
                return self.send_json(404, {"error": "not found"})
        except BadRequest as e:
            return self.send_json(400, {"error": str(e)})
        except Exception as e:  # keep the API alive whatever happens
            return self.send_json(500, {"error": str(e)})
        self.send_json(200, snapshot())


def shutdown(*_):
    nginx("-s", "stop", "-c", NEW_CONF)
    nginx("-s", "stop", "-c", LEGACY_CONF)
    sys.exit(0)


def main():
    os.makedirs(RUN_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    started = nginx("-c", NEW_CONF)
    if started.returncode != 0:
        sys.exit("new nginx failed to start: " + started.stderr)
    with lock:
        apply_settings(DEFAULT_SETTINGS)
    threading.Thread(target=trim_logs, daemon=True).start()
    print("legacy nginx on :%s, new nginx on 127.0.0.1:8082, control api on 127.0.0.1:%d" % (PORT, API_PORT), flush=True)
    ThreadingHTTPServer(("127.0.0.1", API_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

# main.py — fixed, hardened, single-file version (2025)
import os
import uuid
import threading
import subprocess
import select
from pathlib import Path
from collections import defaultdict
import logging
import secrets

from flask import (
    Flask, render_template, request,
    redirect, session, send_file, abort
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

# -------------------------------------------------
# Platform
# -------------------------------------------------
IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    # Note: winpty / PtyProcess is platform-dependent; keep branch as original
    from winpty import PtyProcess
else:
    import pty

# -------------------------------------------------
# Paths
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
KEY_PATH = BASE_DIR / "gl_term" / "key.file"

if not KEY_PATH.is_file():
    raise RuntimeError("Missing authentication key file")

try:
    _BASE_KEY = KEY_PATH.read_text().strip()
except Exception as e:
    raise RuntimeError(f"Failed to read key file: {e}")

# -------------------------------------------------
# App
# -------------------------------------------------
app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)

# Ensure secret_key is a string and cryptographically strong if not provided
_env_secret = os.environ.get("FLASK_SECRET")
if _env_secret:
    app.secret_key = _env_secret
else:
    # fallback: URL-safe token string
    app.secret_key = secrets.token_urlsafe(32)

# Security-related cookie defaults (can be toggled by setting env PRODUCTION=1)
PRODUCTION = os.environ.get("PRODUCTION", "0") == "1"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = PRODUCTION  # set True in real production
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit

# Minimal logging configuration
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("gl_term_server")

# Allow configuring CORS origins for Socket.IO via env (default '*' same as before)
_socket_cors = os.environ.get("SOCKETIO_CORS", "*")
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins=_socket_cors)

# -------------------------------------------------
# Authentication
# -------------------------------------------------
def base_key() -> str:
    # use cached read value to avoid reading file repeatedly
    return _BASE_KEY

def is_authenticated() -> bool:
    return session.get("auth") is True

# Socket.IO auth binding
socket_auth = set()
socket_auth_lock = threading.Lock()

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        if request.form.get("key") == base_key():
            session.clear()
            session["auth"] = True
            return redirect("/")
        return render_template("a/login.html", error="Invalid key")

    if not is_authenticated():
        return render_template("a/login.html")

    return render_template("a/apps.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/upload", methods=["POST"])
def upload():
    if not is_authenticated():
        abort(403)

    file = request.files.get("file")
    if not file or not file.filename:
        abort(400, "Missing file")

    filename = secure_filename(file.filename)
    if not filename:
        abort(400, "Invalid filename")

    rel = request.form.get("path", "")
    # Resolve and validate target directory safely
    try:
        target_dir = (BASE_DIR / rel).resolve()
        # Use relative_to for compatibility (raises ValueError if outside)
        target_dir.relative_to(BASE_DIR)
    except Exception:
        abort(400, "Invalid path")

    if not target_dir.is_dir():
        abort(400, "Invalid path")

    # Save file
    try:
        file.save(target_dir / filename)
    except Exception as e:
        logger.exception("Failed to save uploaded file")
        abort(500, "Failed to save file")
    return redirect("/")

@app.route("/api_fetchfile/<path:relpath>")
def fetch_file(relpath):
    if not is_authenticated():
        abort(403)

    try:
        target = (BASE_DIR / relpath).resolve()
        target.relative_to(BASE_DIR)
    except Exception:
        abort(404)

    if not target.is_file():
        abort(404)

    return send_file(target)

@app.route("/terminal")
def terminal_page():
    if not is_authenticated():
        return redirect("/")
    return render_template("terminal.html")

# -------------------------------------------------
# Terminal Management
# -------------------------------------------------
terminals = {}
terminals_lock = threading.Lock()
MAX_TERMINALS_PER_CLIENT = 2

def create_terminal(owner_sid: str):
    with terminals_lock:
        count = sum(1 for t in terminals.values() if t["owner"] == owner_sid)
        if count >= MAX_TERMINALS_PER_CLIENT:
            raise RuntimeError("Terminal limit reached")

    tab = uuid.uuid4().hex

    if IS_WINDOWS:
        proc = PtyProcess.spawn("cmd.exe")

        def reader():
            try:
                while proc.isalive():
                    data = proc.read(4096)
                    if data:
                        # ensure we emit a string (avoid JSON/bytes issue)
                        try:
                            text = data.decode(errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
                        except Exception:
                            text = str(data)
                        socketio.emit(
                            "term_output",
                            {"tab": tab, "output": text},
                            room=owner_sid,
                        )
            finally:
                try:
                    proc.close()
                except Exception:
                    pass

        with terminals_lock:
            terminals[tab] = {"proc": proc, "owner": owner_sid}

        threading.Thread(target=reader, daemon=True).start()
        return tab

    master, slave = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash")

    proc = subprocess.Popen(
        [shell],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)

    def reader():
        try:
            while True:
                r, _, _ = select.select([master], [], [], 0.1)
                if master in r:
                    data = os.read(master, 4096)
                    if not data:
                        break
                    # always send string to avoid JSON/bytes issues
                    socketio.emit(
                        "term_output",
                        {"tab": tab, "output": data.decode(errors="ignore")},
                        room=owner_sid,
                    )
        finally:
            try:
                proc.wait()
            except Exception:
                pass
            try:
                os.close(master)
            except Exception:
                pass

    with terminals_lock:
        terminals[tab] = {"proc": proc, "fd": master, "owner": owner_sid}

    threading.Thread(target=reader, daemon=True).start()
    return tab

def close_terminal(tab: str):
    with terminals_lock:
        info = terminals.pop(tab, None)

    if not info:
        return

    try:
        info["proc"].terminate()
    except Exception:
        try:
            info["proc"].kill()
        except Exception:
            pass

# -------------------------------------------------
# Socket.IO
# -------------------------------------------------
@socketio.on("connect")
def on_connect():
    if not is_authenticated():
        return False

    with socket_auth_lock:
        socket_auth.add(request.sid)

    join_room(request.sid)

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid

    with socket_auth_lock:
        socket_auth.discard(sid)

    with terminals_lock:
        owned = [t for t, i in terminals.items() if i["owner"] == sid]

    for tab in owned:
        close_terminal(tab)

    leave_room(sid)

@socketio.on("term_new")
def on_term_new():
    if request.sid not in socket_auth:
        return

    try:
        tab = create_terminal(request.sid)
        emit("term_created", {"tab": tab})
    except RuntimeError as e:
        emit("error", {"message": str(e)})

@socketio.on("term_input")
def on_term_input(msg):
    tab = msg.get("tab")
    data = msg.get("data", "")

    with terminals_lock:
        info = terminals.get(tab)

    if not info or info["owner"] != request.sid:
        return

    try:
        if IS_WINDOWS:
            # PtyProcess.write expects str input; ensure type safety
            if isinstance(data, (bytes, bytearray)):
                data = data.decode(errors="ignore")
            info["proc"].write(data)
        else:
            os.write(info["fd"], data.encode())
    except Exception:
        logger.exception("Failed to write to terminal")

@socketio.on("term_close")
def on_term_close(msg):
    tab = msg.get("tab")
    if tab:
        close_terminal(tab)
        emit("term_closed", {"tab": tab})

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting server")
    socketio.run(app, host="0.0.0.0", port=8080, debug=False)

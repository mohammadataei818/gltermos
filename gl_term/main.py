# main.py — DROP-IN replacement (bytes-safe key handling)
import os
import uuid
import threading
import subprocess
import select
from pathlib import Path
import logging
import secrets
import sys
import tempfile

from flask import (
    Flask, render_template, request,
    redirect, session, send_file, abort, flash
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from jinja2 import TemplateNotFound

# -------------------------------------------------
# Platform
# -------------------------------------------------
IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    from winpty import PtyProcess
else:
    import pty

# -------------------------------------------------
# Paths
# -------------------------------------------------
APP_DIR = Path(__file__).resolve().parent        # gl_term/
BASE_DIR = APP_DIR.parent                        # project root

TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
KEY_PATH = APP_DIR / "key.file"

# -------------------------------------------------
# Key handling: always operate on bytes (source-of-truth = file)
# -------------------------------------------------
def load_base_key_bytes():
    """
    Return key as bytes (stripped), or None if not present.
    Falls back to GLTERM_KEY env var (encoded utf-8) if file missing.
    """
    try:
        if KEY_PATH.is_file():
            b = KEY_PATH.read_bytes()
            if b is not None:
                b = b.strip()
                if b:
                    return b
    except Exception:
        pass

    env_key = os.environ.get("GLTERM_KEY")
    if env_key:
        return env_key.encode("utf-8")
    return None

def auth_enabled():
    return bool(load_base_key_bytes())

def load_base_key_str_for_templates():
    """
    Helper used for template globals: decode bytes to string for display.
    Returns '' if no key.
    """
    kb = load_base_key_bytes()
    if not kb:
        return ""
    try:
        return kb.decode("utf-8", errors="ignore")
    except Exception:
        return ""

def write_key_atomic_bytes(new_key_bytes: bytes) -> None:
    """
    Atomically write the new key bytes to KEY_PATH with restrictive permissions.
    Raises on failure.
    """
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        tf = tempfile.NamedTemporaryFile(delete=False, dir=str(KEY_PATH.parent))
        tmp = Path(tf.name)
        # write bytes
        if isinstance(new_key_bytes, str):
            new_key_bytes = new_key_bytes.encode("utf-8")
        tf.write(new_key_bytes + b"\n")
        tf.flush()
        os.fsync(tf.fileno())
        tf.close()
        # set 0600
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, KEY_PATH)
    except Exception:
        # cleanup
        try:
            if tmp and tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise

# -------------------------------------------------
# App init
# -------------------------------------------------
app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)

# Legacy template globals
app.jinja_env.globals["os"] = os
app.jinja_env.globals["open"] = open
app.jinja_env.globals["flash"] = flash
# provide function so templates get up-to-date key as string
app.jinja_env.globals["refbas"] = load_base_key_str_for_templates

# sessions / cookies
app.secret_key = os.environ.get("FLASK_SECRET") or secrets.token_urlsafe(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("PRODUCTION", "0") == "1"
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("gl_term")

if not auth_enabled():
    logger.warning("Authentication disabled: no key found (file or GLTERM_KEY env)")

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# -------------------------------------------------
# Auth helpers
# -------------------------------------------------
def is_authenticated():
    if not auth_enabled():
        return True
    return session.get("auth") is True

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    if not auth_enabled():
        session["auth"] = True
        return render_template("a/apps.html")

    if request.method == "POST":
        submitted = (request.form.get("key", "") or "").encode("utf-8")
        base_bytes = load_base_key_bytes()

        if base_bytes and secrets.compare_digest(submitted, base_bytes):
            session.clear()
            session["auth"] = True
            session.permanent = True
            session.modified = True
            return redirect("/")

        return render_template("a/login.html", error="Invalid key")

    if not is_authenticated():
        return render_template("a/login.html")

    return render_template("a/apps.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# -------------------------------------------------
# /modules dispatcher (specific-first)
# -------------------------------------------------
@app.route("/modules", defaults={"path": ""})
@app.route("/modules/<path:path>")
def modules(path):
    if not is_authenticated():
        abort(403)

    path = (path or "").strip("/")
    candidates = []

    if path:
        parts = path.split("/")
        candidates.append(f"modules/{parts[0]}/index.html")
        if len(parts) > 1:
            candidates.append(f"modules/{parts[0]}/{parts[1]}.html")
            tail = "/".join(parts[1:])
            candidates.append(f"modules/{parts[0]}/{tail}.html")
        candidates.append(f"modules/{path}.html")

    candidates.extend(["modules/Files/index.html", "modules/index.html"])
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    for tpl in candidates:
        try:
            return render_template(tpl)
        except TemplateNotFound:
            continue
    abort(404)

# -------------------------------------------------
# /apisettings dispatcher (legacy chapi via GET)
# -------------------------------------------------
@app.route("/apisettings", defaults={"name": "lists"}, methods=["GET"])
@app.route("/apisettings/<name>", methods=["GET"])
def api_settings(name):
    if not is_authenticated():
        abort(403)

    if name == "chapi":
        prevpass = request.args.get("prevpass", "")
        newpass = request.args.get("newpass", "")
        newpassagain = request.args.get("newpassagain", "")

        if not prevpass or not newpass or not newpassagain:
            return render_template("sysmodules/chapi.html")

        current_b = load_base_key_bytes()
        if not current_b:
            flash("Internal error: key not configured")
            return redirect("/apisettings/chapi")

        if not secrets.compare_digest(prevpass.encode("utf-8"), current_b):
            flash('Error. The "Previous Password" is incorrect')
            return redirect("/apisettings/chapi")

        if newpass != newpassagain:
            flash('Error. The "New Password Again" is not equal to "New Password"')
            return redirect("/apisettings/chapi")

        try:
            write_key_atomic_bytes(newpass.encode("utf-8"))
        except Exception:
            logger.exception("Failed to write new key")
            flash("Internal error: unable to write key file")
            return redirect("/apisettings/chapi")

        # logout after change
        session.clear()
        return redirect("/logout")

    # default sysmodules render
    try:
        return render_template(f"sysmodules/{name}.html")
    except TemplateNotFound:
        abort(404)

# -------------------------------------------------
# File upload / fetch
# -------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload():
    if not is_authenticated():
        abort(403)

    file = request.files.get("file")
    if not file or not file.filename:
        abort(400)

    filename = secure_filename(file.filename)
    if not filename:
        abort(400)

    rel = request.form.get("path", "")
    try:
        target_dir = (BASE_DIR / rel).resolve()
        target_dir.relative_to(BASE_DIR)
    except Exception:
        abort(400)

    if not target_dir.is_dir():
        abort(400)

    file.save(target_dir / filename)
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
# Terminal management and Socket.IO (unchanged)
# -------------------------------------------------
terminals = {}
terminals_lock = threading.Lock()

def create_terminal(owner_sid):
    tab = uuid.uuid4().hex
    if IS_WINDOWS:
        proc = PtyProcess.spawn("cmd.exe")
        def reader():
            while proc.isalive():
                data = proc.read(4096)
                if data:
                    socketio.emit("term_output", {"tab": tab, "output": str(data)}, room=owner_sid)
        terminals[tab] = {"proc": proc, "owner": owner_sid}
        threading.Thread(target=reader, daemon=True).start()
        return tab

    master, slave = pty.openpty()
    proc = subprocess.Popen([os.environ.get("SHELL", "/bin/bash")], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)

    def reader():
        while True:
            r, _, _ = select.select([master], [], [], 0.1)
            if master in r:
                data = os.read(master, 4096)
                if not data:
                    break
                socketio.emit("term_output", {"tab": tab, "output": data.decode(errors="ignore")}, room=owner_sid)

    terminals[tab] = {"proc": proc, "fd": master, "owner": owner_sid}
    threading.Thread(target=reader, daemon=True).start()
    return tab

def close_terminal(tab):
    info = terminals.pop(tab, None)
    if not info:
        return
    try:
        info["proc"].terminate()
    except Exception:
        pass

@socketio.on("connect")
def on_connect():
    if not is_authenticated():
        return False
    join_room(request.sid)

@socketio.on("disconnect")
def on_disconnect():
    owned = [t for t, i in terminals.items() if i["owner"] == request.sid]
    for tab in owned:
        close_terminal(tab)
    leave_room(request.sid)

@socketio.on("term_new")
def on_term_new():
    tab = create_terminal(request.sid)
    emit("term_created", {"tab": tab})

@socketio.on("term_input")
def on_term_input(msg):
    tab = msg.get("tab")
    data = msg.get("data", "")

    info = terminals.get(tab)
    if not info or info["owner"] != request.sid:
        return

    if IS_WINDOWS:
        info["proc"].write(data)
    else:
        os.write(info["fd"], data.encode())

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
    socketio.run(app, host="0.0.0.0", port=8080, debug=False)

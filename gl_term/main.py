import os
import sys
import uuid
import threading
import subprocess
import select
from pathlib import Path
import logging
import secrets
import tempfile
from jinja2 import TemplateNotFound
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
	s.connect(("8.8.8.8", 80))
except OSError:
	print('offline mode')
	ipaddr = "127.0.0.1"
ipaddr = s.getsockname()[0]
s.close()
from flask import (
    Flask, render_template, request, redirect,
    session, send_file, abort, flash
)
from flask_socketio import SocketIO, emit, join_room

from werkzeug.utils import secure_filename

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
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
KEY_PATH = APP_DIR / "key.file"

# -------------------------------------------------
# Key handling (auth)
# -------------------------------------------------
def load_base_key_bytes():
    try:
        if KEY_PATH.is_file():
            b = KEY_PATH.read_bytes().strip()
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

def write_key_atomic_bytes(new_key: bytes):
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=KEY_PATH.parent) as f:
        f.write(new_key.strip() + b"\n")
        f.flush()
    os.replace(f.name, KEY_PATH)

# -------------------------------------------------
# Flask App
# -------------------------------------------------
app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)
# Legacy globals
app.jinja_env.globals["os"] = os
app.jinja_env.globals["open"] = open
app.jinja_env.globals["len"] = len
app.jinja_env.globals["str"] = str
app.jinja_env.globals["ipaddr"] = ipaddr
app.jinja_env.globals["sys"] = __import__('sys')
app.jinja_env.globals["getoutput"] = subprocess.getoutput
app.secret_key = os.environ.get("SESSION_SECRET", "SUPER_SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("PRODUCTION") == "1"
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("gl_term")

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# -------------------------------------------------
# Authentication Helpers
# -------------------------------------------------
def is_authenticated():
    if not auth_enabled():
        return True
    return session.get("auth") is True

APPS = {}
# -------------------------------------------------
# LOGIN / HOME
# -------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    # Authentication (original logic)
    if not auth_enabled():
        session["auth"] = True
        return render_template("a/apps.html")

    if request.method == "POST":
        submitted = (request.form.get("key") or "").encode()
        real = load_base_key_bytes()
        if real and secrets.compare_digest(submitted, real):
            session.clear()
            session["auth"] = True
            return redirect("/")
        flash("Invalid key")
        return render_template("a/login.html", error="Invalid key")

    if not is_authenticated():
        return render_template("a/login.html")

    # NEW: Serve Umbrel‑style home screen
    return render_template("a/apps.html", apps=APPS)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# -------------------------------------------------
# UPLOAD
# -------------------------------------------------
@app.route("/upload",methods=["POST"])
def upload():
    path = request.form.get('path')
    upload = request.files.get('file')
    upload.save(path.replace('/','\\') + '\\' + upload.filename)
    flash('Uploaded')
    return redirect('/')


# -------------------------------------------------
# /modules (same as before)
# -------------------------------------------------
TEMPLATE_PREFIXES = [
    "gl_term/modules",
    "modules",
]
def check_path(path: str):
    """
    Checks if the path is accessible.
    Returns:
      - True if path is readable
      - Error string if an exception occurs
    """
    try:
        if os.path.isdir(path):
            os.listdir(path)  # Test read
        elif os.path.isfile(path):
            open(path, 'rb').close()
        else:
            return f"Path does not exist"
        return True
    except Exception as e:
        return str(e)

# Expose request to templates
app.jinja_env.globals['request'] = request

# Helper to get list of drives (Windows) or root (Linux)
import os
import sys
from urllib.parse import quote_plus

def build_breadcrumbs(path: str):
    """
    Return list of (label, url) tuples for breadcrumbs.
    Works for Windows drive roots (C:/...) and Linux (/...).
    Example:
      "C:/Users/me/docs" -> [("C:/","C:/"), ("Users","C:/Users"), ("me","C:/Users/me"), ("docs","C:/Users/me/docs")]
      "/home/me" -> [("/", "/"), ("home", "/home"), ("me", "/home/me")]
    """
    if path is None:
        path = ("C:/" if sys.platform.startswith("win") else "/")

    # normalize separators
    norm = path.replace("\\", "/")
    # remove duplicate slashes
    while '//' in norm:
        norm = norm.replace('//', '/')
    # strip trailing slash except keep root "/"
    if norm != '/' and norm.endswith('/'):
        norm = norm.rstrip('/')

    crumbs = []

    # Windows drive-root handling
    if sys.platform.startswith("win"):
        # e.g. "C:", "C:/", "C:/Users", "C:/Users/me"
        # ensure we have at least "C:/" style for drive roots
        if len(norm) >= 2 and norm[1] == ':':
            drive = norm[:2] + '/'
            rest = norm[3:] if norm.startswith(drive) else norm[2:].lstrip('/')
            # add drive root crumb
            crumbs.append((drive, drive))
            if rest:
                parts = rest.split('/')
                acc = drive.rstrip('/')  # "C:"
                for p in parts:
                    acc = acc + '/' + p
                    crumbs.append((p, acc))
            return crumbs
        # fallback: not recognized as drive letter -> treat normally below

    # POSIX / and generic path handling
    if norm == '' or norm == '/':
        return [('/', '/')]
    parts = norm.split('/')
    # if absolute path (leading ''), make root crumb
    if parts and parts[0] == '':
        acc = '/'
        crumbs.append(('/', '/'))
        parts = parts[1:]
    else:
        acc = parts[0]
        crumbs.append((parts[0], acc))
        parts = parts[1:]

    for p in parts:
        if acc == '/':
            acc = '/' + p
        else:
            acc = acc.rstrip('/') + '/' + p
        crumbs.append((p, acc))

    return crumbs

# expose to jinja
app.jinja_env.globals['build_breadcrumbs'] = build_breadcrumbs

def get_volumes():
    vols = []
    if sys.platform.startswith("win"):
        import ctypes

        # Get bitmask of drives that are ready
        drives_bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if drives_bitmask & (1 << i):
                drive = f"{chr(65 + i)}:/"
                try:
                    ready = os.path.exists(drive)
                except Exception:
                    ready = False
                vols.append({"path": drive, "ready": ready})
    else:
        # Linux root ("/") and optionally /mnt or /media
        vols.append({"path": "/", "ready": True})
    return vols

app.jinja_env.globals['get_volumes'] = get_volumes

# Helper to list directory contents safely
def list_dir_safe(path):
    try:
        entries = []
        for entry in os.listdir(path):
            full = os.path.join(path, entry)
            entries.append({
                "name": entry,
                "path": full,
                "is_dir": os.path.isdir(full),
                "is_file": os.path.isfile(full),
                "size": os.path.getsize(full) if os.path.isfile(full) else None,
                "mtime": os.path.getmtime(full)
            })
        return entries
    except Exception as e:
        return str(e)  # Return error string
app.jinja_env.globals['list_dir_safe'] = list_dir_safe
# Expose to templates
app.jinja_env.globals["check_path"] = check_path

@app.route('/api_fetchfile/<path:path>')
def api_fetchdata(path):
    # if not is_authenticated():
    #     abort(403)
    return send_file(path)
@app.errorhandler(404)
def error_not_founnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnd(err):
    return render_template('404.html')
@app.route("/modules", defaults={"path": "", "a": None},methods=['GET','POST'])
@app.route("/modules/<path:path>/<a>",methods=['GET','POST'])
def modules(path, a):
    if not is_authenticated():
        abort(403)

    path = (path or "").strip("/")

    candidates = []

    # merge path + a if a exists
    full_path = f"{path}/{a}".strip("/") if a else path

    if full_path:
        parts = full_path.split("/")

        # try index at each folder
        for i in range(1, len(parts) + 1):
            prefix_path = "/".join(parts[:i])
            suffix_path = "/".join(parts[i:])
            if suffix_path:
                candidates.append(f"{prefix_path}/{suffix_path}.html")
            candidates.append(f"{prefix_path}/index.html")

        # also try the full path itself
        candidates.append(f"{full_path}.html")

    elif a:
        candidates.append(f"{a}.html")

    # de-duplicate while preserving order
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    # try all prefixes
    for c in candidates:
        for prefix in TEMPLATE_PREFIXES:
            try_path = f"{prefix}/{c}"
            try:
                print(f"Trying template: {try_path}")
                return render_template(try_path)
            except TemplateNotFound:
                continue

    # last resort: try without prefix
    for c in candidates:
        try:
            print(f"Trying template (no prefix): {c}")
            return render_template(c)
        except TemplateNotFound:
            continue

    abort(404)
# -------------------------------------------------
# /apisettings
# -------------------------------------------------
from urllib.parse import unquote

@app.route("/apisettings", defaults={"name": "lists"}, methods=["GET"])
@app.route("/apisettings/<name>", methods=["GET"])
def api_settings(name):
    if not is_authenticated():
        abort(403)

    sys_dir = TEMPLATE_DIR / "sysmodules"
    if not sys_dir.is_dir():
        return abort(404)

    name = unquote(name.strip().lower())
    target_html = f"{name}.html"

    for f in sys_dir.iterdir():
        if f.is_file() and f.name.lower() == target_html:
            return render_template(f"sysmodules/{f.name}")
    return abort(404)

# -------------------------------------------------
# Terminal Logic (Intact)
# -------------------------------------------------

@app.route('/termapi')
def term_api():
    a = request.args.get('cmd')
    return subprocess.getoutput(a)
@app.route("/terminal")
def terminal_page():
    if not is_authenticated():
        return redirect("/")
    return render_template("terminal.html")

terminals = {}

def create_terminal(owner_sid):
    tab = uuid.uuid4().hex
    if IS_WINDOWS:
        proc = PtyProcess.spawn("cmd.exe")

        def reader():
            while proc.isalive():
                data = proc.read(4096)
                if data:
                    socketio.emit("term_output", {"tab": tab, "output": str(data)}, room=owner_sid)

        threading.Thread(target=reader, daemon=True).start()
        terminals[tab] = {"proc": proc, "owner": owner_sid}
        return tab

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [os.environ.get("SHELL", "/bin/bash")],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)

    def reader():
        while True:
            r, _, _ = select.select([master], [], [], 0.1)
            if master in r:
                data = os.read(master, 4096)
                if not data:
                    break
                socketio.emit("term_output", {"tab": tab, "output": data.decode(errors="ignore")}, room=owner_sid)

    threading.Thread(target=reader, daemon=True).start()
    terminals[tab] = {"proc": proc, "fd": master, "owner": owner_sid}
    return tab

@socketio.on("connect")
def on_connect():
    if not is_authenticated():
        return False
    join_room(request.sid)

@socketio.on("term_new")
def on_term_new():
    emit("term_created", {"tab": create_terminal(request.sid)})

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

@socketio.on("disconnect")
def on_disconnect():
    for t, i in list(terminals.items()):
        if i["owner"] == request.sid:
            try:
                i["proc"].terminate()
            except Exception:
                pass
            terminals.pop(t)

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8080, debug=True)

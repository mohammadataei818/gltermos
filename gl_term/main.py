import os
import uuid
import threading
import subprocess
import select
from pathlib import Path
import logging
import secrets
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
# Key handling (bytes-safe)
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
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=KEY_PATH.parent) as f:
            tmp = Path(f.name)
            f.write(new_key.strip() + b"\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, KEY_PATH)
    finally:
        if tmp and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

# -------------------------------------------------
# App
# -------------------------------------------------
app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)

# legacy template globals
app.jinja_env.globals["os"] = os
app.jinja_env.globals["open"] = open
app.jinja_env.globals["sys"] = __import__('sys')
app.jinja_env.globals["getoutput"] = subprocess.getoutput
app.jinja_env.globals["refbas"] = lambda: (load_base_key_bytes() or b"").decode("utf-8", "ignore")

# session
app.secret_key = os.environ.get("FLASK_SECRET") or secrets.token_urlsafe(32)
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
# Helpers
# -------------------------------------------------
def is_authenticated():
    if not auth_enabled():
        return True
    return session.get("auth") is True


def resolve_template(relative_dir: str, name: str):
    """
    Case-insensitive, filesystem-backed resolver.
    Returns template path relative to templates/ or None.
    """
    base = TEMPLATE_DIR / relative_dir
    if not base.is_dir():
        return None

    parts = Path(name).parts
    cur = base

    for part in parts:
        if not cur.is_dir():
            return None
        match = None
        for p in cur.iterdir():
            if p.name.lower() == part.lower():
                match = p
                break
        if not match:
            return None
        cur = match

    if cur.is_file():
        return f"{relative_dir}/" + cur.relative_to(base).as_posix()
    return None

# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
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
        return render_template("a/login.html", error="Invalid key")

    if not is_authenticated():
        return render_template("a/login.html")

    return render_template("a/apps.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# -------------------------------------------------
# /modules (FINAL, WORKING)
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
        candidates.append(f"{parts[0]}/index.html")
        if len(parts) > 1:
            candidates.append(f"{parts[0]}/{parts[1]}.html")
            candidates.append(f"{parts[0]}/{'/'.join(parts[1:])}.html")
        candidates.append(f"{path}.html")

    candidates.extend([
        "Files/index.html",
        "index.html",
    ])

    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    for c in candidates:
        tpl = resolve_template("modules", c)
        if tpl:
            return render_template(tpl)

    abort(404)

# -------------------------------------------------
# /apisettings (sysmodules, FINAL)
# -------------------------------------------------
# DROP-IN replacement for api_settings route
from urllib.parse import unquote

@app.route("/apisettings", defaults={"name": "lists"}, methods=["GET"])
@app.route("/apisettings/<name>", methods=["GET"])
def api_settings(name):
    logger.debug("REQUEST /apisettings path=%s args=%s", request.path, dict(request.args))
    if not is_authenticated():
        logger.debug("Unauthenticated access to /apisettings -> 403")
        abort(403)

    name = unquote((name or "lists").strip())

    sys_dir = TEMPLATE_DIR / "sysmodules"
    if not sys_dir.is_dir():
        logger.error("templates/sysmodules directory not found at %s", sys_dir)
        abort(404)

    # --- legacy chapi handling (GET-based) ---
    if name.lower() == "chapi":
        prevpass = request.args.get("prevpass", "")
        newpass = request.args.get("newpass", "")
        newpassagain = request.args.get("newpassagain", "")

        # no params -> just render the template if exists
        if not (prevpass and newpass and newpassagain):
            # try to locate the template case-insensitively
            for f in sys_dir.iterdir():
                if f.is_file() and f.name.lower() == "chapi.html":
                    logger.debug("Rendering chapi template file=%s", f.name)
                    return render_template(f"sysmodules/{f.name}")
            logger.info("chapi template not found under %s", sys_dir)
            abort(404)

        # validate current key
        current_b = load_base_key_bytes()
        if not current_b or not secrets.compare_digest(prevpass.encode("utf-8"), current_b):
            flash('Error. The "Previous Password" is incorrect')
            return redirect("/apisettings/chapi")  # keep legacy redirect behaviour for errors

        if newpass != newpassagain:
            flash('Error. The "New Password Again" is not equal to "New Password"')
            return redirect("/apisettings/chapi")

        try:
            write_key_atomic_bytes(newpass.encode("utf-8"))
        except Exception:
            logger.exception("Failed to write new key")
            flash("Internal error: unable to write key file")
            return redirect("/apisettings/chapi")

        session.clear()
        return redirect("/logout")

    # --- normal sysmodules pages: do case-insensitive lookup ---
    target = f"{name}.html".lower()
    for f in sys_dir.iterdir():
        if f.is_file() and f.name.lower() == target:
            logger.debug("Found sysmodules template match: %s -> %s", name, f.name)
            return render_template(f"sysmodules/{f.name}")

    # Optional: fallback to lists instead of 404
    # logger.info("sysmodules: template not found for %s; falling back to lists", name)
    # return render_template("sysmodules/lists.html")

    logger.info("sysmodules: template not found for %s; returning 404. Checked %s", name, [p.name for p in sys_dir.iterdir() if p.is_file()])
    abort(404)

# -------------------------------------------------
# Terminal (unchanged)
# -------------------------------------------------
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

        terminals[tab] = {"proc": proc, "owner": owner_sid}
        threading.Thread(target=reader, daemon=True).start()
        return tab

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [os.environ.get("SHELL", "/bin/bash")],
        stdin=slave, stdout=slave, stderr=slave, close_fds=True,
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

    terminals[tab] = {"proc": proc, "fd": master, "owner": owner_sid}
    threading.Thread(target=reader, daemon=True).start()
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
            terminals.pop(t, None)

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8080, debug=False)

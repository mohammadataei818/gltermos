# server.py (drop-in replacement)
import os
import sys
import uuid
import datetime
import subprocess
import select
import threading
from collections import deque

from flask import Flask, render_template, request, redirect, session, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room

IS_WINDOWS = os.name == "nt"

# On Windows we use pywinpty (pip install pywinpty)
if IS_WINDOWS:
    try:
        from winpty import PtyProcess
    except Exception as ex:
        raise ImportError("pywinpty (winpty) is required on Windows. Run: pip install pywinpty") from ex
else:
    import pty

# ---------------- app config ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = "replace-with-your-real-secret"

socketio = SocketIO(app, async_mode="threading")

# ---------------- key/session (your existing key file) ----------------
KEY_PATH = r"./gl_term/key.file"
if not os.path.exists(KEY_PATH):
    raise FileNotFoundError(f"Key file not found: {KEY_PATH}")

with open(KEY_PATH, "r", encoding="utf-8") as f:
    base_key = f.read().strip()

session_key_value = base_key * 3 + "ThisIsKeyRepeated3TimesAndMore" + base_key * 5

# ---------------- helper safe render ----------------
def safe_render(template_name, **kwargs):
    full = os.path.join(TEMPLATE_DIR, template_name)
    if not os.path.exists(full):
        return f"Template not found: {template_name}", 404
    return render_template(template_name, **kwargs)

# ---------------- routes (kept minimal & compatible) ----------------
@app.route("/", methods=["GET", "POST"])
def home():
    try:
        if session.get("wallpaper") is None:
            session["wallpaper"] = "1.jpg"
        if request.method == "POST":
            if request.form.get("key") == base_key:
                session["pop_login"] = session_key_value
                return redirect("/")
            else:
                return render_template("a/login.html", error="Incorrect key")
        if session.get("pop_login") != session_key_value:
            return render_template("a/login.html")
        return render_template("a/apps.html")
    except Exception:
        import traceback
        return f"<pre>{traceback.format_exc()}</pre>", 500

@app.route("/logout")
def logout():
    session.pop("pop_login", None)
    return redirect("/")

@app.route("/settings/")
def settings_appx():
    if session.get("pop_login") != session_key_value:
        return redirect("/")
    return safe_render("a/settings.html")

@app.route("/void_appx")
def void_appx():
    if session.get("pop_login") != session_key_value:
        return redirect("/")
    try:
        os.system("taskkill /f /im pythonw.exe")
        os.system("taskkill /f /im python.exe")
    except Exception:
        pass
    return "<h2>Have A Great Day Ended.</h2>"

@app.route("/apisettings/<apiname>")
def api_settings(apiname):
    if session.get("pop_login") != session_key_value:
        return redirect("/")
    if apiname == "wlch":
        wallpapers_dir = os.path.join(STATIC_DIR, "wallpapers")
        filelist = os.listdir(wallpapers_dir) if os.path.isdir(wallpapers_dir) else []
        return safe_render("sysmodules/wlch.html")
    if apiname == "wlcmd":
        session["wallpaper"] = request.args.get("w", "")
        return redirect("/settings")
    return "Unknown API", 404

@app.route("/upload", methods=["POST"])
def upload():
    if session.get("pop_login") != session_key_value:
        return redirect("/")
    file = request.files.get("file")
    path = request.form.get("path", "")
    if not os.path.isdir(path):
        return f"Upload path not found: {path}", 400
    file.save(os.path.join(path, file.filename))
    return redirect("/")

@app.route("/favicon.ico")
def favicon():
    return send_file(os.path.join(BASE_DIR, "app_favicon.png"))

@app.route("/api_fetchfile/<path:path>")
def fetchfile(path):
    if session.get("pop_login") != session_key_value:
        return redirect("/")
    if not os.path.isfile(path):
        return f"File not found: {path}", 404
    return send_file(path)

@app.route("/modules/<aasd>/<ddda>")
def modules_aasd_index(aasd, ddda):
    safe_aasd = aasd.replace("..", "").replace("/", "")
    safe_ddda = ddda.replace("..", "").replace("/", "")
    template_path = f"modules/{safe_aasd}/{safe_ddda}.html"
    full_template = os.path.join(TEMPLATE_DIR, template_path)
    if not os.path.isfile(full_template):
        return f"<h2>Module template not found: {template_path}</h2>", 404
    return render_template(
        template_path,
        getoutput=lambda cmd: subprocess.check_output(cmd, shell=True, text=True),
        os=os, open=open, sys=sys, subprocess=subprocess, bytes=bytes, str=str, len=len, datetime=datetime
    )

@app.route("/terminal")
def terminal_page():
    if session.get("pop_login") != session_key_value:
        return redirect("/")
    return render_template("terminal.html")

# ---------------- terminal management (multi-tab) ----------------
# Each tab is represented by an entry in terminals[tab_id]
# On Windows: terminals[tab]['proc'] is a winpty PtyProcess
# On Unix: terminals[tab]['proc'] is subprocess and 'fd' is pty master fd
terminals = {}

def create_terminal_for_owner(owner_sid):
    """
    Create a new terminal for the owner (socket sid).
    Returns (tab_id, local_echo_flag)
    """
    tab = str(uuid.uuid4())

    if IS_WINDOWS:
        # Use pywinpty high-level API: PtyProcess.spawn
        # This gives a real console (ConPTY/winpty) and proper interactive behavior.
        proc = PtyProcess.spawn("cmd.exe")  # spawns cmd.exe
        terminals[tab] = {"proc": proc, "owner": owner_sid, "is_windows": True, "pending_echo": deque()}

        def reader():
            try:
                # read in chunks until the process exits
                while proc.isalive():
                    # proc.read may block; read small chunks with a short timeout approach
                    try:
                        data = proc.read(4096)
                    except Exception:
                        # some pywinpty versions may raise on short reads; try readline fallback
                        try:
                            data = proc.readline()
                        except Exception:
                            data = ''
                    if not data:
                        break
                    # proc.read returns unicode (str), emit directly
                    socketio.emit("term_output", {"tab": tab, "output": data}, room=owner_sid)
            except Exception:
                socketio.emit("term_output", {"tab": tab, "output": "\r\n[winpty read error]\r\n"}, room=owner_sid)
            finally:
                socketio.emit("term_output", {"tab": tab, "output": "\r\n[terminal exited]\r\n"}, room=owner_sid)

        threading.Thread(target=reader, daemon=True).start()
        # With PtyProcess/ConPTY there is proper terminal echo, so client should NOT do local echo
        return tab, False

    # Unix-like: PTY approach
    master, slave = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash")
    proc = subprocess.Popen([shell], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    terminals[tab] = {"proc": proc, "fd": master, "owner": owner_sid, "is_windows": False}

    def read_pty():
        try:
            while True:
                r, _, _ = select.select([master], [], [], 0.1)
                if master in r:
                    data = os.read(master, 4096)
                    if not data:
                        break
                    socketio.emit("term_output", {"tab": tab, "output": data.decode(errors="ignore")}, room=owner_sid)
        except Exception:
            socketio.emit("term_output", {"tab": tab, "output": "\n[pty read error]\n"}, room=owner_sid)
        finally:
            socketio.emit("term_output", {"tab": tab, "output": "\n[pty exited]\n"}, room=owner_sid)

    threading.Thread(target=read_pty, daemon=True).start()
    # PTY provides echo, client should NOT do local echo
    return tab, False

def close_terminal(tab):
    info = terminals.pop(tab, None)
    if not info:
        return
    try:
        if info.get("is_windows"):
            proc = info.get("proc")
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.close()
                except Exception:
                    pass
        else:
            p = info.get("proc")
            if p:
                p.terminate()
    except Exception:
        pass

# ---------------- Socket.IO handlers ----------------
@socketio.on("connect")
def on_connect():
    sid = request.sid
    join_room(sid)

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    # close any terminals owned by this sid
    to_close = [t for t, info in list(terminals.items()) if info.get("owner") == sid]
    for t in to_close:
        close_terminal(t)
    try:
        leave_room(sid)
    except Exception:
        pass

@socketio.on("term_new")
def on_term_new():
    if session.get("pop_login") != session_key_value:
        return False
    sid = request.sid
    tab_id, local_echo = create_terminal_for_owner(sid)
    emit("term_created", {"tab": tab_id, "local_echo": local_echo})

@socketio.on("term_input")
def on_term_input(msg):
    if session.get("pop_login") != session_key_value:
        return False
    sid = request.sid
    tab = msg.get("tab")
    data = msg.get("data", "")
    if not tab or tab not in terminals:
        return
    info = terminals[tab]
    if info.get("owner") != sid:
        return
    try:
        if info.get("is_windows"):
            # proc.write accepts strings
            info["proc"].write(data)
        else:
            os.write(info["fd"], data.encode(errors="ignore"))
    except Exception:
        pass

@socketio.on("term_close")
def on_term_close(msg):
    if session.get("pop_login") != session_key_value:
        return False
    tab = msg.get("tab")
    if tab:
        close_terminal(tab)
        emit("term_closed", {"tab": tab})

# ---------------- run ----------------
if __name__ == "__main__":

    socketio.run(app, host="0.0.0.0", port=80, debug=True)

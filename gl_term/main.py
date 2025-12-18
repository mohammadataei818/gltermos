from flask import *
from subprocess import getoutput
import subprocess
import datetime
import os
import sys
app = Flask(__name__)
key = open('v:\\glance\\gl_term\\key.file').read()
session_key_value = key + key + key + "ThisIsKeyRepeated3TimesAndMore" + key +key +key +key + key

@app.route('/settings/')
def settings_appx():
    if not session.get('pop_login') == session_key_value:
        return redirect('/')
    else:
        return render_template('a/settings.html')
@app.route('/apisettings/<apiname>')
def api_settings(apiname):
    if apiname == "wlch":
        return render_template('sysmodules/wlch.html',filelist=os.listdir('./gl_term/static/wallpapers'))
    if apiname == "wlcmd":
        wlacually = request.args.get('w')
        session['wallpaper'] = wlacually
        return redirect('/settings')
@app.route('/',methods=["GET",'POST'])
def a():
    if session.get('wallpaper') == None:
        session['wallpaper'] = '1.jpg'
        return redirect('/')
    if not session.get('pop_login') == session_key_value:
        if request.method == "GET":
            return render_template('a/login.html',hostname=getoutput('hostname'),username=getoutput('whoami'))
        else:
            if request.form.get('key') == key:
                session['pop_login'] = session_key_value
                flash('login successfully done.')
                return redirect('/')
            else:
                flash('incorrct key. try again')
                return redirect('/')
    else:
        resp = make_response(render_template('a/apps.html',resp=make_response('e,aaksdpk')))
        return resp
@app.route('/logout')
def logout():
    session.pop('pop_login')
    return redirect('/')

@app.route('/upload', methods = ['POST'])  
def upload():  
    if not session.get('pop_login') == session_key_value:
        return redirect('/')
    else:
        if request.method == 'POST':  
            file = request.files.get('file')
            path = request.form.get('path')
            file.save(path + file.filename)
            flash('Upload Successful.')
            return redirect('/')
@app.errorhandler(404)
def html_of_handle_404(err):
    return redirect('/static/rickroll.mp4')

@app.route('/favicon.ico')
def favicon():
    return send_file('V:\\glance\\gl_term\\app_favicon.png')
@app.route('/api_fetchfile/<path:path>')
def fetchfile(path):
    if not session.get('pop_login') == session_key_value:
        return redirect('/')
    else:
            return send_file(path)
@app.route('/modules/<aasd>/<ddda>')
def modules_aasd_index(aasd,ddda):
    if not session.get('pop_login') == session_key_value:
        return redirect('/')
    else:
            return render_template(f'modules/{aasd}/{ddda}.html',getoutput=lambda cmd:subprocess.check_output(cmd, shell=True, text=True),os=os,open=open,sys=sys,subprocess=subprocess,bytes=bytes,str=str,len=len,datetime=datetime)
def file_read_lines(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.readlines()
    except Exception:
        return ["File could not be read."]

if __name__ == "__main__":
    app.secret_key = "key_aosdoiajsiodhisduiadsiioashdjih9uy2unijc6fyb9uq2tgnjigfuhndyhunjoeih"
    app.jinja_env.filters['file_read_lines'] = file_read_lines
    app.run(debug=True,port=80,host="0.0.0.0")

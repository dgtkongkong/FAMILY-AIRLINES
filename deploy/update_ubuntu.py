"""Update an existing Ubuntu installation, preserving accounts and all family data.
Run from a reviewed checkout: sudo python3 deploy/update_ubuntu.py
"""
import datetime, os, pathlib, shutil, sqlite3, subprocess, time, urllib.request, urllib.error
from contextlib import closing

SOURCE=pathlib.Path(__file__).resolve().parents[1]
TARGET=pathlib.Path('/opt/ace-captain')
FILES=['server.py','excel_export.py','web/index.html','web/app.js','web/style.css','web/icon.svg','web/manifest.webmanifest','web/sw.js']

def run(*args): subprocess.run(args,check=True)
def healthy():
    for _ in range(15):
        try:
            urllib.request.urlopen('http://127.0.0.1:8765/api/state',timeout=3).close()
        except urllib.error.HTTPError as e:
            if e.code==401:return True
        except OSError:pass
        time.sleep(1)
    return False

def main():
    if os.geteuid()!=0:raise SystemExit('Run with sudo.')
    os.umask(0o077)
    db=TARGET/'data/captain.sqlite3'
    if not db.is_file():raise SystemExit('Existing installation not found. No changes made.')
    for name in FILES:
        if not (SOURCE/name).is_file():raise SystemExit('Missing source: '+name)
    for name in ['server.py','excel_export.py']:
        compile((SOURCE/name).read_text('utf-8'),name,'exec')
    backup=pathlib.Path('/var/backups/ace-captain')/('upgrade-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True,mode=0o700)
    for name in FILES:
        (backup/name).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(TARGET/name,backup/name)
    run('systemctl','stop','ace-captain.service')
    try:
        with closing(sqlite3.connect(db)) as src,closing(sqlite3.connect(backup/'captain.sqlite3')) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity check failed')
        for name in FILES:
            shutil.copyfile(SOURCE/name,TARGET/name)
            os.chmod(TARGET/name,0o644)
        run('systemctl','start','ace-captain.service')
        if not healthy():raise RuntimeError('New backend health check failed')
    except Exception:
        run('systemctl','stop','ace-captain.service')
        for name in FILES:shutil.copy2(backup/name,TARGET/name)
        run('systemctl','start','ace-captain.service')
        raise
    print('UPDATE OK: backend returned 401; accounts and records preserved.')
    print('Backup directory:',backup)
    print('Daily backup timer and HTTPS configuration are unchanged.')

if __name__=='__main__':main()

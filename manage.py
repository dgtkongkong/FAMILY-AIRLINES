"""Local administration: password reset and transactionally consistent backup."""
import argparse,getpass,secrets,sqlite3
from pathlib import Path
import server as s

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',default=str(s.DB))
    sub=p.add_subparsers(dest='command',required=True)
    reset=sub.add_parser('reset-password');reset.add_argument('user',choices=['child','dad','mom'])
    backup=sub.add_parser('backup');backup.add_argument('destination')
    a=p.parse_args();s.DB=Path(a.db).resolve()
    if not s.DB.exists():raise SystemExit('Database not found. Run server.py --setup first.')
    if a.command=='backup':
        dest=Path(a.destination).resolve()
        if dest.exists():raise SystemExit('Destination exists; choose a new filename.')
        dest.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(s.DB) as src,sqlite3.connect(dest) as target:src.backup(target)
        print('Backup created:',dest)
    else:
        password=getpass.getpass('New password (8+ characters): ')
        confirm=getpass.getpass('Repeat password: ')
        if password!=confirm or len(password)<8:raise SystemExit('Passwords must match and be at least 8 characters.')
        with s.transaction() as c:
            if not c.execute('SELECT 1 FROM users WHERE id=?',(a.user,)).fetchone():raise SystemExit('User not found')
            salt=secrets.token_hex(16)
            c.execute('UPDATE users SET salt=?,hash=? WHERE id=?',(salt,s.hash_password(password,salt),a.user))
            c.execute('DELETE FROM sessions WHERE user=?',(a.user,))
            s.audit(c,'local-admin','password-reset',a.user)
        print('Password updated; existing sessions revoked.')

if __name__=='__main__':main()

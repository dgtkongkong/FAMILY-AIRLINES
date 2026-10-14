"""Make a private, consistent SQLite snapshot without logging ledger contents."""
import datetime
import sqlite3
from pathlib import Path

source = Path('/opt/ace-captain/data/captain.sqlite3')
target_dir = Path('/var/backups/ace-captain')
if not source.is_file():
    raise SystemExit('Family database is not initialized.')
target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
suffix = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
target = target_dir / ('ledger-' + suffix + '.sqlite3')
with sqlite3.connect(source) as connection, sqlite3.connect(target) as backup:
    connection.backup(backup)
target.chmod(0o600)
print('Private database snapshot complete.')

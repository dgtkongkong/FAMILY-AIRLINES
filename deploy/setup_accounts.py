"""Interactive first-time setup. Never print or save plaintext passwords."""
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

if server.has_accounts():
    print('Existing accounts retained; no password changes made.')
    raise SystemExit(0)
passwords = {}
for user, label in [('child', 'Child'), ('dad', 'Dad'), ('mom', 'Mom')]:
    while True:
        value = getpass.getpass(label + ' password (8+ characters): ')
        repeat = getpass.getpass('Repeat password: ')
        if len(value) >= 8 and value == repeat:
            passwords[user] = value
            break
        print('Passwords must match and contain at least 8 characters.')
server.init_db(passwords)
print('Three family accounts created. No demo records imported.')

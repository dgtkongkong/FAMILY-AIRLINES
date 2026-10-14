#!/usr/bin/env bash
# Run from a reviewed source checkout: sudo bash deploy/install-ubuntu.sh
# Installs only the private, loopback backend. Public HTTPS is a separate step.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run with sudo.'; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
target=/opt/ace-captain
[[ -f "$source_dir/server.py" && -d "$source_dir/web" ]] || exit 1
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 22.04 ]] || { echo 'Expected Ubuntu 22.04.'; exit 1; }
if [[ -e "$target/server.py" ]]; then
    echo 'Existing installation found; stopping to protect existing code and data.'
    echo 'Use the update procedure after backing up, rather than reinstalling.'
    exit 1
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 ca-certificates curl
id captain >/dev/null 2>&1 || useradd --system --home-dir "$target" --shell /usr/sbin/nologin captain
install -d -m 0755 "$target" "$target/web" "$target/deploy"
install -m 0644 "$source_dir/server.py" "$source_dir/excel_export.py" "$source_dir/manage.py" "$source_dir/rules.json" "$target/"
for asset in index.html app.js style.css icon.svg manifest.webmanifest sw.js; do
    install -m 0644 "$source_dir/web/$asset" "$target/web/$asset"
done
install -m 0644 "$source_dir/deploy/setup_accounts.py" "$source_dir/deploy/backup_daily.py" "$target/deploy/"
install -d -o captain -g captain -m 0700 "$target/data"
install -d -m 0700 /var/backups/ace-captain
cat > /etc/systemd/system/ace-captain.service <<'UNIT'
[Unit]
Description=ACE Captain family application
After=network.target
[Service]
Type=simple
User=captain
Group=captain
WorkingDirectory=/opt/ace-captain
Environment=CAPTAIN_SECURE_COOKIE=1
ExecStart=/usr/bin/python3 /opt/ace-captain/server.py --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/opt/ace-captain/data
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/ace-captain-backup.service <<'UNIT'
[Unit]
Description=Back up family mileage database
[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/bin/python3 /opt/ace-captain/deploy/backup_daily.py
UNIT
cat > /etc/systemd/system/ace-captain-backup.timer <<'UNIT'
[Unit]
Description=Daily family ledger backup
[Timer]
OnCalendar=*-*-* 19:15:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
echo 'Set the three app passwords locally. Input is hidden.'
runuser -u captain -- /usr/bin/python3 "$target/deploy/setup_accounts.py"
systemctl enable --now ace-captain.service ace-captain-backup.timer
systemctl start ace-captain-backup.service
status=000
for attempt in {1..10}; do
    status=$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8765/api/state || true)
    [[ "$status" == 401 ]] && break
    sleep 1
done
[[ "$status" == 401 ]] || { echo "Unexpected backend response: $status"; exit 1; }
echo 'Backend ready on 127.0.0.1:8765, initial backup complete.'
echo 'No public HTTP port was opened. Configure domain and HTTPS after filing.'

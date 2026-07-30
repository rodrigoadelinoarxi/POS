#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Execute: sudo bash update.sh"; exit 1; }
cp app.py requirements.txt "/opt/pos-receipt-api/"
"/opt/pos-receipt-api/venv/bin/pip" install -r "/opt/pos-receipt-api/requirements.txt"
chown -R posprinter:posprinter "/opt/pos-receipt-api"
systemctl restart "pos-receipt-api"
systemctl status "pos-receipt-api" --no-pager

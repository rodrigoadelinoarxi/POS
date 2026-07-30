#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Execute: sudo bash update.sh"; exit 1; }
cp app.py requirements.txt "/opt/pos-beverages-api/"
"/opt/pos-beverages-api/venv/bin/pip" install -r "/opt/pos-beverages-api/requirements.txt"
chown -R posprinter:posprinter "/opt/pos-beverages-api"
systemctl restart "pos-beverages-api"
systemctl status "pos-beverages-api" --no-pager

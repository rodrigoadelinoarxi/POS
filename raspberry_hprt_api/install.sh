#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="pos-beverages-api"
INSTALL_DIR="/opt/pos-beverages-api"
RUN_USER="posprinter"
DEFAULT_VENDOR="0x0000"
DEFAULT_PRODUCT="0x0000"

if [ "$(id -u)" -ne 0 ]; then echo "Execute: sudo bash install.sh"; exit 1; fi
apt-get update
apt-get install -y python3 python3-venv python3-pip libusb-1.0-0 usbutils
id -u "$RUN_USER" >/dev/null 2>&1 || useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$RUN_USER"
mkdir -p "$INSTALL_DIR" "/etc/$SERVICE_NAME" "/var/lib/$SERVICE_NAME"
cp app.py requirements.txt "$INSTALL_DIR/"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
VENDOR="$DEFAULT_VENDOR"; PRODUCT="$DEFAULT_PRODUCT"
if command -v lsusb >/dev/null 2>&1; then
  DETECTED="$(lsusb | awk '/Printer|printer|HPRT|Xprinter|STMicroelectronics/ {print $6; exit}')"
  if [ -n "$DETECTED" ]; then VENDOR="0x${DETECTED%:*}"; PRODUCT="0x${DETECTED#*:}"; fi
fi
if [ -f "/etc/$SERVICE_NAME/env" ]; then
  OLD_TOKEN="$(sed -n 's/^PRINT_TOKEN=//p' "/etc/$SERVICE_NAME/env" | head -1)"
  [ -n "$OLD_TOKEN" ] && TOKEN="$OLD_TOKEN"
fi
cat > "/etc/$SERVICE_NAME/env" <<ENV
PRINT_TOKEN=$TOKEN
PRINTER_VENDOR_ID=$VENDOR
PRINTER_PRODUCT_ID=$PRODUCT
PRINTER_OUT_EP=0x01
PRINTER_IN_EP=0x81
PRINT_DATA_DIR=/var/lib/$SERVICE_NAME
ENV
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<UNIT
[Unit]
Description=POS Beverages API - Raspberry HPRT
After=network-online.target tailscaled.service
Wants=network-online.target
[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=/etc/$SERVICE_NAME/env
ExecStart=$INSTALL_DIR/venv/bin/gunicorn -w 1 -b 0.0.0.0:5000 app:app
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/udev/rules.d/99-pos-printer.rules <<RULE
SUBSYSTEM=="usb", ATTR{idVendor}=="${VENDOR#0x}", ATTR{idProduct}=="${PRODUCT#0x}", MODE="0660", GROUP="$RUN_USER"
RULE
chown -R "$RUN_USER:$RUN_USER" "$INSTALL_DIR" "/var/lib/$SERVICE_NAME"
udevadm control --reload-rules
udevadm trigger
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
echo
echo "INSTALACAO CONCLUIDA"
echo "Servico: $SERVICE_NAME"
echo "Token: $TOKEN"
echo "USB: $VENDOR:$PRODUCT"
echo "Use este token nos Parametros do Sistema do Odoo."
echo "Teste: curl http://127.0.0.1:5000/health"

#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root (sudo)." >&2
    exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname -- "$SCRIPT_DIR")
APP_DIR=/home/pi/rocket
LOG_DIR=/home/pi/rocket/logs
RECORDING_DIR=/home/pi/rocket/recordings
AIRFRAME_DIR=/etc/rocket-guidance/airframes

install -d -o pi -g pi -m 0755 "$APP_DIR" "$LOG_DIR" "$RECORDING_DIR"
install -d -o root -g root -m 0755 "$AIRFRAME_DIR"
install -o pi -g pi -m 0644 "$PROJECT_DIR"/src/*.py "$APP_DIR"/
install -o root -g root -m 0644 "$PROJECT_DIR"/deploy/airframes/*.json "$AIRFRAME_DIR"/

if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    echo "Missing $APP_DIR/venv/bin/python; create the Pi virtual environment first." >&2
    exit 1
fi

install -o root -g root -m 0644 \
    "$PROJECT_DIR/deploy/rocket-guidance.service" \
    /etc/systemd/system/rocket-guidance.service

install -o root -g root -m 0644 \
    "$PROJECT_DIR/deploy/rocket-guidance.default" \
    /etc/default/rocket-guidance

install -o root -g root -m 0644 \
    "$PROJECT_DIR/deploy/rocket-guidance.logrotate" \
    /etc/logrotate.d/rocket-guidance

systemctl daemon-reload
systemctl enable rocket-guidance.service
echo "Installed and enabled rocket-guidance.service without starting it."

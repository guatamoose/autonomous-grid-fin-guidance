#!/bin/sh
set -eu

config=/boot/firmware/config.txt
cmdline=/boot/firmware/cmdline.txt
cp -n "$config" "$config.before-grid-fin-uart"
cp -n "$cmdline" "$cmdline.before-grid-fin-uart"

# Raspberry Pi OS: disable the serial login console; enable UART hardware.
raspi-config nonint do_serial_cons 1
raspi-config nonint do_serial_hw 0

grep -q '^enable_uart=1' "$config"
if grep -q 'console=serial0,' "$cmdline"; then
    echo 'Serial console is still enabled' >&2
    exit 1
fi
echo 'UART configured; reboot required.'

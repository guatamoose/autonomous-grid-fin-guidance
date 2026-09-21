"""Passive read-only probe of Pi GPIO UART for MAVLink framing."""

import serial


for baud in (57600, 115200):
    port = serial.Serial("/dev/serial0", baudrate=baud, timeout=3)
    try:
        data = port.read(120)
    finally:
        port.close()
    print(f"{baud}: {len(data)} bytes, prefix={data[:16].hex()}")

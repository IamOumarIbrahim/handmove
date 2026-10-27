"""
Continuous Live Wave & Motion Transmitter for uHand UNO / COM3.
Runs an indefinite oscillating wave sequence with dtr=False so that as soon as
the physical hardware prerequisites (Bluetooth conflict, power switch) are aligned,
the robotic hand immediately begins moving in real time.
"""

import os
import sys
import time
import serial

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from controller import HandController


def make_uhand_packet(func: int, data: list) -> bytes:
    """Build native uHand UNO packet: AA 77 <func> <len> <data...> <chk>."""
    length = len(data)
    total = (func + length + sum(data)) & 0xFF
    chk = (0xFF - total) & 0xFF
    return bytes([0xAA, 0x77, func, length]) + bytes(data) + bytes([chk])


def run_continuous_wave(port: str = "COM3", baud: int = 9600):
    print("=" * 76)
    print("  uHand UNO Continuous Wave & Gesture Loop")
    print(f"  Target: {port} @ {baud} baud | DTR=False (Arduino will not reset)")
    print("=" * 76)

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.bytesize = serial.EIGHTBITS
    ser.parity = serial.PARITY_NONE
    ser.stopbits = serial.STOPBITS_ONE
    ser.timeout = 0.1
    ser.write_timeout = 1.0
    ser.dtr = False
    ser.rts = False

    try:
        ser.open()
        print(f"[CONNECTED] Opened {port} successfully with DTR=False.")
    except Exception as e:
        print(f"[ERROR] Could not open {port}: {e}")
        return

    # Motion keyframes: Open -> Fist -> Peace -> Wave Left -> Wave Right -> Open
    poses = [
        ("Open Hand", [180, 180, 180, 180, 180, 90]),
        ("Closed Fist", [0, 0, 0, 0, 0, 90]),
        ("Peace / Victory", [0, 180, 180, 0, 0, 90]),
        ("Wave Left", [180, 180, 180, 180, 180, 45]),
        ("Wave Right", [180, 180, 180, 180, 180, 135]),
        ("Neutral Rest", [90, 90, 90, 90, 90, 90]),
    ]

    print("\n[TRANSMITTING] Streaming continuous movement packets every 0.6 seconds...")
    print("Press Ctrl+C at any time to stop.\n")

    step = 0
    try:
        while True:
            name, angles = poses[step % len(poses)]
            step += 1

            # Build and transmit packet
            pkt = make_uhand_packet(0x01, angles)
            ser.write(pkt)
            ser.flush()

            # Read any feedback
            rx = ser.read(ser.in_waiting) if ser.in_waiting > 0 else b""
            rx_str = f" | RX: {rx.hex(' ').upper()}" if rx else ""

            print(f"[{step:04d}] TX >> {pkt.hex(' ').upper()} ({name}){rx_str}", flush=True)
            time.sleep(0.6)

    except KeyboardInterrupt:
        print("\n[STOPPED] Continuous wave loop stopped by user.")
    finally:
        ser.close()
        print("[CLOSED] Port closed.")


if __name__ == "__main__":
    run_continuous_wave(port="COM3", baud=9600)

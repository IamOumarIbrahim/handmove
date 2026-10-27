"""Continuous motion demo using the saved Hiwonder BLE or serial connection."""

import time
from typing import Optional

from controller import HandController
from connection_settings import load_connection_settings


def run_continuous_wave(port: Optional[str] = None, baud: Optional[int] = None):
    defaults = load_connection_settings()
    port = defaults["port"] if port is None else port
    baud = defaults["baudrate"] if baud is None else baud

    print("=" * 76)
    print("  uHand UNO Continuous Wave & Gesture Loop")
    print(f"  Target: {defaults['ble_name']} BLE" if defaults["transport"] == "ble" else f"  Target: {port or 'select COM port'} @ {baud} baud")
    print("=" * 76)

    controller = HandController(port=port, baudrate=baud)
    controller.on_log = lambda direction, text: print(f"[{direction}] {text}") if direction in ("TX", "ERR") else None
    success, message = controller.connect()
    if not success:
        print(f"[DISCONNECTED] {message}")
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

            controller.send_angles(angles)
            print(f"[{step:04d}] {name}: {angles}", flush=True)
            time.sleep(0.6)

    except KeyboardInterrupt:
        print("\n[STOPPED] Continuous wave loop stopped by user.")
    finally:
        controller.disconnect()
        print("[CLOSED] Connection closed.")


if __name__ == "__main__":
    run_continuous_wave()

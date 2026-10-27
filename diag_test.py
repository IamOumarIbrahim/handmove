"""
Quick diagnostic: opens COM3 with DTR=False, fires 3 basic commands,
and verifies bytes are actually being written to the port.
Run from HANDMOVE directory: python diag_test.py
"""
import serial
import time
import sys


def make_pkt(func: int, data: list) -> bytes:
    length = len(data)
    total = (func + length + sum(data)) & 0xFF
    chk = (0xFF - total) & 0xFF
    return bytes([0xAA, 0x77, func, length] + data + [chk])


def main():
    port = "COM3"
    baud = 9600

    print("=" * 60)
    print(f"  uHand UNO Diagnostic Test — {port} @ {baud}")
    print("=" * 60)

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.bytesize = serial.EIGHTBITS
    ser.parity = serial.PARITY_NONE
    ser.stopbits = serial.STOPBITS_ONE
    ser.timeout = 0.3
    ser.write_timeout = 1.0
    ser.dtr = False    # <-- CRITICAL: must be set BEFORE open()
    ser.rts = False    # <-- CRITICAL: must be set BEFORE open()

    try:
        ser.open()
    except Exception as e:
        print(f"[FAIL] Cannot open {port}: {e}")
        sys.exit(1)

    print(f"[OK]   Port opened — dtr={ser.dtr}, rts={ser.rts}")
    # Give the board a moment to settle without resetting
    time.sleep(0.4)

    commands = [
        ("NEUTRAL (90,90,90,90,90,90)", make_pkt(0x01, [90, 90, 90, 90, 90, 90])),
        ("OPEN HAND (180,180,180,180,180,90)", make_pkt(0x01, [180, 180, 180, 180, 180, 90])),
        ("FIST (0,0,0,0,0,90)", make_pkt(0x01, [0, 0, 0, 0, 0, 90])),
        ("OPEN HAND (180,180,180,180,180,90)", make_pkt(0x01, [180, 180, 180, 180, 180, 90])),
        ("FIST (0,0,0,0,0,90)", make_pkt(0x01, [0, 0, 0, 0, 0, 90])),
        ("NEUTRAL (90,90,90,90,90,90)", make_pkt(0x01, [90, 90, 90, 90, 90, 90])),
    ]

    for name, pkt in commands:
        hex_str = pkt.hex(" ").upper()
        print(f"\n  TX >> {hex_str}")
        print(f"         ({name})")
        n = ser.write(pkt)
        ser.flush()
        print(f"         Wrote {n} bytes")
        time.sleep(1.0)

        rx = ser.read(ser.in_waiting) if ser.in_waiting > 0 else b""
        if rx:
            print(f"  RX << {rx.hex(' ').upper()}")
        else:
            print(f"  RX << (no response)")

    ser.close()
    print("\n[DONE] Diagnostic complete. Did you see any servo movement?")
    print("If NOT: check that BLE module is removed from the RX socket on the shield.")


if __name__ == "__main__":
    main()

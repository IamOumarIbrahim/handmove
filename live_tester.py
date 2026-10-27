"""
Live Persistent Hardware Tester for uHand UNO / COM3.
Maintains persistent connection with dtr=False so the Arduino ATmega328P
never resets back into midpoint mode.
Cycles through all protocol configurations with 5-second active test windows.
"""

import os
import sys
import time
from typing import Dict, List, Optional, Tuple
import serial

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from controller import HandController


def make_uhand_packet(func: int, data: List[int]) -> bytes:
    """Build uHand UNO packet (AA 77)."""
    length = len(data)
    total = (func + length + sum(data)) & 0xFF
    chk = (0xFF - total) & 0xFF
    return bytes([0xAA, 0x77, func, length]) + bytes(data) + bytes([chk])


def make_lobot_multi(pulse_open: int, pulse_close: int, toggle: bool) -> bytes:
    """Build Lobot multi-servo frame (55 55 17 03 06 ...)."""
    pulse = pulse_open if toggle else pulse_close
    time_ms = 400
    params = [6, time_ms & 0xFF, (time_ms >> 8) & 0xFF]
    for ch in range(1, 7):
        p = pulse if ch <= 5 else 1500
        params.extend([ch, p & 0xFF, (p >> 8) & 0xFF])
    return bytes([0x55, 0x55, len(params) + 2, 0x03]) + bytes(params)


def make_lobot_single(ch: int, pulse: int) -> bytes:
    """Build Lobot single servo frame."""
    time_ms = 350
    params = [1, time_ms & 0xFF, (time_ms >> 8) & 0xFF, ch, pulse & 0xFF, (pulse >> 8) & 0xFF]
    return bytes([0x55, 0x55, len(params) + 2, 0x03]) + bytes(params)


def run_live_test(port: str = "COM3", baud: int = 9600) -> None:
    print("\n" + "="*76)
    print("  uHand UNO Live Persistent Hardware Tester (NO ARDUINO RESET)")
    print(f"  Port: {port} | Baud: {baud} | DTR=False (Midpoint mode preserved)")
    print("="*76 + "\n")

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.bytesize = serial.EIGHTBITS
    ser.parity = serial.PARITY_NONE
    ser.stopbits = serial.STOPBITS_ONE
    ser.timeout = 0.2
    ser.write_timeout = 1.0
    ser.dtr = False
    ser.rts = False

    try:
        ser.open()
        print(f"[OK] Port {port} opened with DTR=False. Arduino was NOT reset.")
    except Exception as e:
        print(f"[ERR] Failed to open {port}: {e}")
        return

    # Preparation countdown
    print("\n" + "*"*76)
    print("  IMPORTANT: Push buttons K1 & K2 (D1 and D2) NOW until the RGB LED turns GREEN.")
    print("  This exits midpoint mode. Because DTR=False, it will STAY out of midpoint mode!")
    print("*"*76)

    for countdown in range(5, 0, -1):
        print(f"  Starting 5-second test cycles in {countdown}s...", end="\r", flush=True)
        time.sleep(1.0)
    print("\n  >>> STARTING PROTOCOL TEST SWEEP NOW <<<\n")

    test_dialects = [
        # (ID, Name, Generator Function, Description)
        (
            1, "uHand UNO Standard (0xAA 0x77)",
            lambda toggle: make_uhand_packet(0x01, [180, 180, 180, 180, 180, 90] if toggle else [0, 0, 0, 0, 0, 90]),
            "Official protocol: AA 77 01 06 <S1..S6> <chk>"
        ),
        (
            2, "uHand UNO Alternate Pulse (0-100% scaled)",
            lambda toggle: make_uhand_packet(0x01, [100, 100, 100, 100, 100, 50] if toggle else [0, 0, 0, 0, 0, 50]),
            "0-100 percentage angle payload"
        ),
        (
            3, "uHand UNO Additive Checksum",
            lambda toggle: bytes([0xAA, 0x77, 0x01, 0x06]) + (bytes([180, 180, 180, 180, 180, 90]) if toggle else bytes([0, 0, 0, 0, 0, 90])) + bytes([(0x07 + (540 if toggle else 90)) & 0xFF]),
            "AA 77 framing with additive sum & 0xFF"
        ),
        (
            4, "Lobot Multi-Servo (0x55 0x55, CMD 0x03)",
            lambda toggle: make_lobot_multi(2400, 600, toggle),
            "Hiwonder 6CH controller multi-servo frame (pulse width 600-2400us)"
        ),
        (
            5, "Lobot Single-Servo Burst (0x55 0x55)",
            lambda toggle: b"".join(make_lobot_single(ch, 2400 if toggle else 600) for ch in range(1, 7)),
            "Hiwonder individual servo move packets (ch 1 to 6)"
        ),
        (
            6, "ASCII CSV Angles Stream",
            lambda toggle: b"180,180,180,180,180,90\r\n" if toggle else b"0,0,0,0,0,90\r\n",
            "Text format: '180,180,180,180,180,90\\r\\n'"
        ),
        (
            7, "ASCII Delimited '<...>'",
            lambda toggle: b"<180,180,180,180,180,90>\n" if toggle else b"<0,0,0,0,0,90>\n",
            "Text format: '<180,180,180,180,180,90>\\n'"
        ),
        (
            8, "ASCII PSC Protocol (#1P...)",
            lambda toggle: b"#1P2200T400!#2P2200T400!#3P2200T400!#4P2200T400!#5P2200T400!#6P1500T400!\r\n" if toggle else b"#1P800T400!#2P800T400!#3P800T400!#4P800T400!#5P800T400!#6P1500T400!\r\n",
            "Industry standard servo command: '#1P2200T400!...\\r\\n'"
        ),
        (
            9, "ASCII Channel Tagged (S1:180)",
            lambda toggle: b"S1:180\nS2:180\nS3:180\nS4:180\nS5:180\nS6:90\n" if toggle else b"S1:0\nS2:0\nS3:0\nS4:0\nS5:0\nS6:90\n",
            "Text format: 'S1:180\\n...S6:90\\n'"
        ),
        (
            10, "Buzzer + RGB Activation + Move",
            lambda toggle: (make_uhand_packet(0x02, [20, 2, 232, 3]) + make_uhand_packet(0x03, [0, 255, 0])) if toggle else make_uhand_packet(0x01, [180, 180, 180, 180, 180, 90]),
            "Buzzer tone + RGB green + servo move combo"
        )
    ]

    results = []
    report_file = os.path.join(os.path.dirname(__file__), "LIVE_TEST_RESULTS.md")

    for cfg_id, name, gen_fn, desc in test_dialects:
        print(f"\n[{cfg_id:02d}/{len(test_dialects):02d}] TESTING (5 Seconds): {name}")
        print(f"    Description: {desc}")
        print(f"    -> Actively sending OPEN/CLOSE pulses every 0.8s...")

        start_time = time.time()
        toggle = True
        rx_accum = bytearray()
        tx_count = 0
        sample_hex = ""

        while time.time() - start_time < 5.0:
            pkt = gen_fn(toggle)
            toggle = not toggle
            if not sample_hex:
                sample_hex = pkt.hex(" ").upper()[:24]

            ser.write(pkt)
            ser.flush()
            tx_count += 1

            sub_start = time.time()
            while time.time() - sub_start < 0.8:
                if ser.in_waiting > 0:
                    rx_accum.extend(ser.read(ser.in_waiting))
                time.sleep(0.04)

        rx_str = rx_accum.hex(" ").upper() if rx_accum else "No response"
        print(f"    -> TX sent {tx_count} packets. Sample: {sample_hex}...")
        print(f"    -> RX received: {rx_str}")

        results.append((cfg_id, name, baud, "COMPLETED", sample_hex, rx_str))

        # Save markdown report
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# Live Hardware Test Results (Persistent Connection - DTR=False)\n\n")
            f.write(f"Port: `{port}` | Baud: `{baud}` | Active Test Duration: 5.0s per dialect\n\n")
            f.write("| ID | Configuration / Dialect | Baud | Status | Sent Packet (TX) | Response (RX) |\n")
            f.write("| :---: | :--- | :---: | :---: | :--- | :--- |\n")
            for r_id, r_name, r_baud, r_stat, r_tx, r_rx in results:
                f.write(f"| {r_id:02d} | {r_name} | {r_baud} | {r_stat} | `{r_tx}` | `{r_rx}` |\n")

    ser.close()
    print("\n" + "="*76)
    print(f"  Live test session complete! Check which test visibly moved the robotic hand.")
    print("="*76 + "\n")


if __name__ == "__main__":
    run_live_test(port="COM3", baud=9600)

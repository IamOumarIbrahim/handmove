"""
Automated Hardware Sweep Engine for uHand UNO / COM3.
Systematically tests baud rates, protocol dialetcs, framing headers,
ASCII streams, and timing profiles with a 5-second active test window per configuration.
Maintains and outputs a real-time Markdown progress table.
"""

import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import serial
import serial.tools.list_ports

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from controller import HandController


class ConfigTest:
    def __init__(
        self,
        cfg_id: int,
        name: str,
        port: str,
        baud: int,
        description: str,
        test_fn: Callable[[serial.Serial], Tuple[str, str]],
        dtr: bool = True
    ):
        self.cfg_id = cfg_id
        self.name = name
        self.port = port
        self.baud = baud
        self.description = description
        self.test_fn = test_fn
        self.dtr = dtr
        self.status = "PENDING"
        self.tx_summary = ""
        self.rx_summary = ""
        self.notes = ""


# =============================================================================
# Helper Builders for Protocol Dialects
# =============================================================================

def send_5s_oscillation(
    ser: serial.Serial,
    pkt_open: bytes,
    pkt_close: bytes,
    pkt_neutral: Optional[bytes] = None,
    interval: float = 1.0,
    total_time: float = 5.0
) -> Tuple[str, str]:
    """Send alternating open/close packets for total_time seconds and read RX."""
    start_time = time.time()
    toggle = True
    rx_bytes = bytearray()
    tx_count = 0

    while time.time() - start_time < total_time:
        pkt = pkt_open if toggle else pkt_close
        toggle = not toggle
        try:
            ser.write(pkt)
            ser.flush()
            tx_count += 1
        except Exception:
            pass

        # Read any incoming bytes during the interval
        sub_start = time.time()
        while time.time() - sub_start < interval:
            try:
                waiting = ser.in_waiting
                if waiting > 0:
                    rx_bytes.extend(ser.read(waiting))
            except Exception:
                pass
            time.sleep(0.05)

    if pkt_neutral:
        try:
            ser.write(pkt_neutral)
            ser.flush()
        except Exception:
            pass

    tx_summary = f"{tx_count} pkts ({pkt_open.hex(' ').upper()[:24]}...)"
    rx_summary = rx_bytes.hex(" ").upper() if rx_bytes else "No response"
    return tx_summary, rx_summary


# =============================================================================
# Test Configuration Definitions
# =============================================================================

def build_test_configurations(port: str = "COM3") -> List[ConfigTest]:
    configs = []

    # 1. uHand UNO Protocol (0xAA 0x77), Inverted Checksum
    def test_uhand_aa77_std(ser: serial.Serial):
        open_pkt = HandController.build_uhand_packet(0x01, [180, 180, 180, 180, 180, 90])
        close_pkt = HandController.build_uhand_packet(0x01, [0, 0, 0, 0, 0, 90])
        neutral_pkt = HandController.build_uhand_packet(0x01, [90, 90, 90, 90, 90, 90])
        return send_5s_oscillation(ser, open_pkt, close_pkt, neutral_pkt)

    configs.append(ConfigTest(
        1, "uHand UNO (0xAA 0x77) Bitwise Inv Checksum", port, 9600,
        "Official Hiwonder uHand UNO protocol (AA 77 01 06 ... chk=~sum)",
        test_uhand_aa77_std
    ))
    configs.append(ConfigTest(
        2, "uHand UNO (0xAA 0x77) Bitwise Inv Checksum", port, 115200,
        "Official Hiwonder uHand UNO protocol at 115200 baud",
        test_uhand_aa77_std
    ))

    # 2. uHand UNO Protocol (0xAA 0x77), Additive Checksum
    def test_uhand_aa77_add(ser: serial.Serial):
        # chk = sum & 0xFF
        def make_add(angles):
            payload = bytes([0xAA, 0x77, 0x01, 0x06]) + bytes(angles)
            chk = (0x01 + 0x06 + sum(angles)) & 0xFF
            return payload + bytes([chk])
        open_pkt = make_add([180, 180, 180, 180, 180, 90])
        close_pkt = make_add([0, 0, 0, 0, 0, 90])
        return send_5s_oscillation(ser, open_pkt, close_pkt)

    configs.append(ConfigTest(
        3, "uHand UNO (0xAA 0x77) Additive Checksum", port, 9600,
        "uHand UNO framing with additive checksum (sum & 0xFF)",
        test_uhand_aa77_add
    ))
    configs.append(ConfigTest(
        4, "uHand UNO (0xAA 0x77) Additive Checksum", port, 115200,
        "uHand UNO framing with additive checksum at 115200 baud",
        test_uhand_aa77_add
    ))

    # 3. uHand UNO Mode Exit / Unlock Sequence (K1/K2 serial simulation)
    def test_uhand_unlock_and_move(ser: serial.Serial):
        # Step 1: Send Green RGB (AA 77 03 03 00 FF 00 FA) and Buzzer Beep
        rgb_green = bytes([0xAA, 0x77, 0x03, 0x03, 0x00, 0xFF, 0x00, 0xFA])
        buz_beep = bytes([0xAA, 0x77, 0x02, 0x04, 0x14, 0x02, 0x90, 0x01, 0x51])
        ser.write(rgb_green)
        time.sleep(0.1)
        ser.write(buz_beep)
        time.sleep(0.2)
        # Step 2: Send servo movements
        open_pkt = HandController.build_uhand_packet(0x01, [180, 180, 180, 180, 180, 90])
        close_pkt = HandController.build_uhand_packet(0x01, [0, 0, 0, 0, 0, 90])
        return send_5s_oscillation(ser, open_pkt, close_pkt)

    configs.append(ConfigTest(
        5, "uHand UNO Unlock RGB + Move", port, 9600,
        "Emulates K1/K2 calibration exit: Sets RGB Green + Tone, then oscillates",
        test_uhand_unlock_and_move
    ))
    configs.append(ConfigTest(
        6, "uHand UNO Unlock RGB + Move", port, 115200,
        "Unlock RGB + Tone + Servo oscillation at 115200 baud",
        test_uhand_unlock_and_move
    ))

    # 4. Lobot Multi-Servo Move (0x55 0x55, CMD=0x03)
    def test_lobot_mult_servo(ser: serial.Serial):
        # 55 55 <len> 03 <count> <time_lo> <time_hi> <id> <pos_lo> <pos_hi> ...
        # Pulse 500us (0x01F4) to 2500us (0x09C4)
        def make_lobot_multi(pulse):
            time_ms = 400
            params = [6, time_ms & 0xFF, (time_ms >> 8) & 0xFF]
            for ch in range(1, 7):
                p = pulse if ch <= 5 else 1500
                params.extend([ch, p & 0xFF, (p >> 8) & 0xFF])
            return bytes([0x55, 0x55, len(params) + 2, 0x03]) + bytes(params)

        open_pkt = make_lobot_multi(2400)
        close_pkt = make_lobot_multi(600)
        return send_5s_oscillation(ser, open_pkt, close_pkt)

    configs.append(ConfigTest(
        7, "Lobot Multi-Servo (0x55 0x55, CMD=0x03)", port, 9600,
        "Hiwonder 6CH controller multi-servo frame (pulse width 600-2400us)",
        test_lobot_mult_servo
    ))
    configs.append(ConfigTest(
        8, "Lobot Multi-Servo (0x55 0x55, CMD=0x03)", port, 115200,
        "Hiwonder 6CH controller multi-servo frame at 115200 baud",
        test_lobot_mult_servo
    ))

    # 5. Lobot Single-Servo Move (0x55 0x55, CMD=0x03) - all channels in burst
    def test_lobot_single_burst(ser: serial.Serial):
        def make_single(ch, pulse):
            time_ms = 350
            params = [1, time_ms & 0xFF, (time_ms >> 8) & 0xFF, ch, pulse & 0xFF, (pulse >> 8) & 0xFF]
            return bytes([0x55, 0x55, len(params) + 2, 0x03]) + bytes(params)

        open_burst = b"".join(make_single(c, 2400) for c in range(1, 7))
        close_burst = b"".join(make_single(c, 600) for c in range(1, 7))
        return send_5s_oscillation(ser, open_burst, close_burst)

    configs.append(ConfigTest(
        9, "Lobot Single-Servo Burst (0x55 0x55)", port, 9600,
        "Hiwonder individual servo move packets (1 to 6) in burst",
        test_lobot_single_burst
    ))
    configs.append(ConfigTest(
        10, "Lobot Single-Servo Burst (0x55 0x55)", port, 115200,
        "Hiwonder individual servo move packets at 115200 baud",
        test_lobot_single_burst
    ))

    # 6. LewanSoul Serial Bus Servo Frame (0x55 0x55, ID-first, CMD_SERVO_MOVE=1)
    def test_lewansoul_bus(ser: serial.Serial):
        # 55 55 <id> <len> 01 <pos_lo> <pos_hi> <time_lo> <time_hi> <chk>
        def make_bus(id_num, pos, time_ms=350):
            payload = [id_num, 7, 1, pos & 0xFF, (pos >> 8) & 0xFF, time_ms & 0xFF, (time_ms >> 8) & 0xFF]
            chk = (~sum(payload)) & 0xFF
            return bytes([0x55, 0x55]) + bytes(payload) + bytes([chk])

        open_bus = b"".join(make_bus(c, 900) for c in range(1, 7))
        close_bus = b"".join(make_bus(c, 100) for c in range(1, 7))
        return send_5s_oscillation(ser, open_bus, close_bus)

    configs.append(ConfigTest(
        11, "LewanSoul Bus Servo Frame (ID-first)", port, 115200,
        "Bus servo protocol: 55 55 <ID> <Len> 01 <Pos> <Time> <Chk>",
        test_lewansoul_bus
    ))
    configs.append(ConfigTest(
        12, "LewanSoul Bus Servo Frame (ID-first)", port, 9600,
        "Bus servo protocol at 9600 baud",
        test_lewansoul_bus
    ))

    # 7. ASCII CSV Angles: "180,180,180,180,180,90\r\n"
    def test_ascii_csv(ser: serial.Serial):
        open_csv = b"180,180,180,180,180,90\r\n"
        close_csv = b"0,0,0,0,0,90\r\n"
        return send_5s_oscillation(ser, open_csv, close_csv)

    configs.append(ConfigTest(
        13, "ASCII CSV Angle Stream", port, 9600,
        "Plain text format: '180,180,180,180,180,90\\r\\n' <-> '0,0,0,0,0,90\\r\\n'",
        test_ascii_csv
    ))
    configs.append(ConfigTest(
        14, "ASCII CSV Angle Stream", port, 115200,
        "Plain text format at 115200 baud",
        test_ascii_csv
    ))

    # 8. ASCII Bracketed Angles: "<180,180,180,180,180,90>\n"
    def test_ascii_bracketed(ser: serial.Serial):
        open_b = b"<180,180,180,180,180,90>\n"
        close_b = b"<0,0,0,0,0,90>\n"
        return send_5s_oscillation(ser, open_b, close_b)

    configs.append(ConfigTest(
        15, "ASCII Bracketed Angles '<...>'", port, 9600,
        "Delimited format: '<180,180,180,180,180,90>\\n'",
        test_ascii_bracketed
    ))
    configs.append(ConfigTest(
        16, "ASCII Bracketed Angles '<...>'", port, 115200,
        "Delimited format at 115200 baud",
        test_ascii_bracketed
    ))

    # 9. ASCII PSC Controller: "#1P1500T500! ... #6P1500T500!\r\n"
    def test_ascii_psc(ser: serial.Serial):
        open_psc = b"#1P2200T400!#2P2200T400!#3P2200T400!#4P2200T400!#5P2200T400!#6P1500T400!\r\n"
        close_psc = b"#1P800T400!#2P800T400!#3P800T400!#4P800T400!#5P800T400!#6P1500T400!\r\n"
        return send_5s_oscillation(ser, open_psc, close_psc)

    configs.append(ConfigTest(
        17, "ASCII PSC Protocol (#1P2000T500!)", port, 9600,
        "Industry standard servo controller ASCII: '#1P2200T400!...\\r\\n'",
        test_ascii_psc
    ))
    configs.append(ConfigTest(
        18, "ASCII PSC Protocol (#1P2000T500!)", port, 115200,
        "ASCII PSC Protocol at 115200 baud",
        test_ascii_psc
    ))

    # 10. ASCII Individual Channel Commands: "S1:180\n" ...
    def test_ascii_channel(ser: serial.Serial):
        open_s = b"S1:180\nS2:180\nS3:180\nS4:180\nS5:180\nS6:90\n"
        close_s = b"S1:0\nS2:0\nS3:0\nS4:0\nS5:0\nS6:90\n"
        return send_5s_oscillation(ser, open_s, close_s)

    configs.append(ConfigTest(
        19, "ASCII Channel Tagged (S1:180)", port, 9600,
        "Individual channel format: 'S1:180\\n...S6:90\\n'",
        test_ascii_channel
    ))
    configs.append(ConfigTest(
        20, "ASCII Channel Tagged (S1:180)", port, 115200,
        "Individual channel format at 115200 baud",
        test_ascii_channel
    ))

    # 11. ASCII Single Character Mode Triggers: 'O' (Open), 'C' (Close), '1'..'5'
    def test_ascii_single_char(ser: serial.Serial):
        open_c = b"O\n"
        close_c = b"C\n"
        return send_5s_oscillation(ser, open_c, close_c)

    configs.append(ConfigTest(
        21, "ASCII Single Character ('O'/'C')", port, 9600,
        "Simple character triggers: 'O\\n' (Open), 'C\\n' (Close)",
        test_ascii_single_char
    ))
    configs.append(ConfigTest(
        22, "ASCII Single Character ('O'/'C')", port, 115200,
        "Simple character triggers at 115200 baud",
        test_ascii_single_char
    ))

    # 12. Baud 57600 Tests
    configs.append(ConfigTest(
        23, "uHand UNO (0xAA 0x77) @ 57600 baud", port, 57600,
        "Official protocol at 57600 baud",
        test_uhand_aa77_std
    ))
    configs.append(ConfigTest(
        24, "Lobot Multi-Servo (0x55 0x55) @ 57600 baud", port, 57600,
        "Lobot protocol at 57600 baud",
        test_lobot_mult_servo
    ))

    # 13. Baud 38400 & 19200 Tests
    configs.append(ConfigTest(
        25, "uHand UNO (0xAA 0x77) @ 38400 baud", port, 38400,
        "Official protocol at 38400 baud",
        test_uhand_aa77_std
    ))
    configs.append(ConfigTest(
        26, "uHand UNO (0xAA 0x77) @ 19200 baud", port, 19200,
        "Official protocol at 19200 baud",
        test_uhand_aa77_std
    ))

    # 14. DTR=False (No-Reset connection) Tests
    configs.append(ConfigTest(
        27, "uHand UNO without DTR Reset (dtr=False)", port, 9600,
        "Prevents Arduino reboot upon serial open",
        test_uhand_aa77_std,
        dtr=False
    ))
    configs.append(ConfigTest(
        28, "uHand UNO without DTR Reset (dtr=False)", port, 115200,
        "Prevents Arduino reboot at 115200 baud",
        test_uhand_aa77_std,
        dtr=False
    ))

    # 15. COM1 Cross-Check
    configs.append(ConfigTest(
        29, "COM1 Cross-Check (uHand UNO 0xAA 0x77)", "COM1", 9600,
        "Checks COM1 serial port in case of port mapping variance",
        test_uhand_aa77_std
    ))

    return configs


# =============================================================================
# Execution Engine & Markdown Reporter
# =============================================================================

def generate_markdown_table(tests: List[ConfigTest]) -> str:
    """Format all results into a clean markdown table."""
    lines = [
        "| ID | Configuration Name | Port | Baud | Status | Sent Sample (TX) | Received Feedback (RX) |",
        "| :---: | :--- | :---: | :---: | :---: | :--- | :--- |"
    ]
    for t in tests:
        status_badge = {
            "TESTING": "🟡 **TESTING (5s)**",
            "COMPLETED": "✔️ COMPLETED",
            "FAILED": "❌ FAILED (Port Busy/Error)",
            "PENDING": "⏳ PENDING"
        }.get(t.status, t.status)

        tx = t.tx_summary if t.tx_summary else "-"
        rx = t.rx_summary if t.rx_summary else "-"
        lines.append(f"| {t.cfg_id:02d} | {t.name} | `{t.port}` | {t.baud} | {status_badge} | `{tx[:28]}` | `{rx[:24]}` |")

    return "\n".join(lines)


def run_sweep(port: str = "COM3", duration_per_test: float = 5.0) -> None:
    """Run full sequential sweep testing each configuration for 5 seconds."""
    configs = build_test_configurations(port)
    report_file = os.path.join(os.path.dirname(__file__), "SWEEP_RESULTS.md")

    print(f"\n{'='*78}")
    print(f"  uHand UNO Hardware Sweep Engine - 5-Second Active Test Per Configuration")
    print(f"  Target Port: {port} | Total Configurations: {len(configs)}")
    print(f"{'='*78}\n")

    for idx, cfg in enumerate(configs, 1):
        print(f"\n>>> [{idx:02d}/{len(configs):02d}] TESTING: {cfg.name} on {cfg.port} @ {cfg.baud} baud (Duration: {duration_per_test}s)")
        print(f"    Description: {cfg.description}")
        cfg.status = "TESTING"

        # Update markdown file
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# uHand UNO Configuration Sweep Report\n\n")
            f.write(f"Testing in progress... Active: **Config {cfg.cfg_id:02d}** ({cfg.name})\n\n")
            f.write(generate_markdown_table(configs))

        ser = None
        try:
            ser = serial.Serial(
                port=cfg.port,
                baudrate=cfg.baud,
                timeout=0.3,
                write_timeout=1.0
            )
            ser.dtr = cfg.dtr
            if cfg.dtr:
                # Wait for Arduino UNO reset bootloader
                time.sleep(1.8)
            else:
                time.sleep(0.2)

            # Flush any boot noise
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Run 5-second oscillation test
            print(f"    -> Actively transmitting OPEN/CLOSE oscillation for {duration_per_test}s...")
            tx_sum, rx_sum = cfg.test_fn(ser)
            cfg.tx_summary = tx_sum
            cfg.rx_summary = rx_sum
            cfg.status = "COMPLETED"
            print(f"    -> TX: {tx_sum}")
            print(f"    -> RX: {rx_sum}")

        except Exception as ex:
            cfg.status = "FAILED"
            cfg.notes = str(ex)
            print(f"    -> Port access error: {ex}")
        finally:
            if ser and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass

        # Update markdown report file after each run
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# uHand UNO Configuration Sweep Report\n\n")
            f.write(f"Last updated: Config {cfg.cfg_id:02d}/{len(configs):02d} completed.\n\n")
            f.write(generate_markdown_table(configs))

        time.sleep(0.5)

    print(f"\n{'='*78}")
    print(f"  SWEEP COMPLETED! All {len(configs)} configurations tested for {duration_per_test}s each.")
    print(f"  Results saved to: {report_file}")
    print(f"{'='*78}\n")


if __name__ == "__main__":
    run_sweep(port="COM3", duration_per_test=5.0)

"""
Core Hardware Controller for Hiwonder uHand UNO and compatible robotic hands.
Handles serial communications, protocol framing, checksums, calibration,
kinematics state, preset sequences, and peripheral actuators (Buzzer, RGB LED).
"""

import enum
import json
import logging
import math
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple, Union

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


class ProtocolType(enum.Enum):
    UHAND_UNO = "uHand UNO (0xAA 0x77)"
    LOBOT_BUS = "Lobot / Hiwonder Bus (0x55 0x55)"


class HandController:
    """
    High-level controller for the uHand UNO robotic hand.
    Supports real hardware over COM3/serial and an offline simulation mode.
    """

    NUM_SERVOS = 6
    SERVO_NAMES = [
        "Thumb",
        "Index",
        "Middle",
        "Ring",
        "Pinky",
        "Wrist / Base"
    ]

    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = 9600,
        protocol: ProtocolType = ProtocolType.UHAND_UNO,
        simulation_mode: bool = False
    ):
        self.port = port
        self.baudrate = baudrate
        self.protocol = protocol
        self.simulation_mode = simulation_mode

        self.ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._running = False
        self._rx_thread: Optional[threading.Thread] = None

        # Current state: logical angles (0 - 180 degrees)
        self.current_angles = [90, 90, 90, 90, 90, 90]
        self.target_angles = [90, 90, 90, 90, 90, 90]

        # Per-servo calibration trims (-45 to +45 deg) and inversion flags
        self.trims = [0, 0, 0, 0, 0, 0]
        self.inverted = [False, False, False, False, False, False]
        self.min_limits = [0, 0, 0, 0, 0, 0]
        self.max_limits = [180, 180, 180, 180, 180, 180]

        # Peripherals state
        self.rgb_color = (0, 0, 0)
        self.last_buzzer = (0, 0)

        # Sequence player state
        self._seq_thread: Optional[threading.Thread] = None
        self._seq_stop_event = threading.Event()
        self._seq_pause_event = threading.Event()
        self._seq_pause_event.set()
        self.is_playing_sequence = False

        # Callbacks
        self.on_log: Optional[Callable[[str, str], None]] = None  # (direction, text)
        self.on_angles_updated: Optional[Callable[[List[int]], None]] = None
        self.on_connection_changed: Optional[Callable[[bool, str], None]] = None
        self.on_sequence_step: Optional[Callable[[int, int], None]] = None

    # =========================================================================
    # Connection Management
    # =========================================================================

    def log(self, direction: str, text: str) -> None:
        """Log serial / internal event."""
        if self.on_log:
            try:
                self.on_log(direction, text)
            except Exception:
                pass

    def connect(self) -> Tuple[bool, str]:
        """Establish connection with the controller board."""
        if self.simulation_mode:
            self.log("SYS", f"Connected in Simulation Mode (Virtual uHand UNO)")
            if self.on_connection_changed:
                self.on_connection_changed(True, "Simulation Mode")
            return True, "Simulation Mode Connected"

        if not SERIAL_AVAILABLE:
            self.simulation_mode = True
            msg = "pyserial not available; defaulting to Simulation Mode"
            self.log("WARN", msg)
            if self.on_connection_changed:
                self.on_connection_changed(True, "Simulation (No PySerial)")
            return True, msg

        try:
            self.ser = serial.Serial()
            self.ser.port = self.port
            self.ser.baudrate = self.baudrate
            self.ser.bytesize = serial.EIGHTBITS
            self.ser.parity = serial.PARITY_NONE
            self.ser.stopbits = serial.STOPBITS_ONE
            self.ser.timeout = 0.2
            self.ser.write_timeout = 1.0
            # Explicitly prevent DTR/RTS pulse so Arduino does NOT reset into midpoint mode
            self.ser.dtr = False
            self.ser.rts = False
            self.ser.open()
            time.sleep(0.1)
            self._running = True
            self._rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
            self._rx_thread.start()

            msg = f"Connected to {self.port} at {self.baudrate} baud"
            self.log("SYS", msg)
            if self.on_connection_changed:
                self.on_connection_changed(True, msg)
            return True, msg
        except Exception as ex:
            self.ser = None
            msg = f"Failed to connect to {self.port}: {ex}"
            self.log("ERR", msg)
            if self.on_connection_changed:
                self.on_connection_changed(False, msg)
            return False, msg

    def disconnect(self) -> None:
        """Close serial connection."""
        self._running = False
        self.stop_sequence()
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.log("SYS", "Disconnected")
        if self.on_connection_changed:
            self.on_connection_changed(False, "Disconnected")

    def is_connected(self) -> bool:
        """Check if connected (or running in simulation)."""
        if self.simulation_mode:
            return True
        return self.ser is not None and self.ser.is_open

    # =========================================================================
    # Packet Builders & Protocol Framing
    # =========================================================================

    @staticmethod
    def calc_uhand_checksum(func: int, length: int, data: bytes) -> int:
        """Calculate uHand UNO checksum: 0xFF - (sum & 0xFF)."""
        total = (func + length + sum(data)) & 0xFF
        return (0xFF - total) & 0xFF

    @classmethod
    def build_uhand_packet(cls, func: int, data: Union[bytes, List[int]]) -> bytes:
        """Build a native uHand UNO packet: 0xAA 0x77 <func> <len> <data...> <check>."""
        if isinstance(data, list):
            data = bytes(data)
        length = len(data)
        checksum = cls.calc_uhand_checksum(func, length, data)
        return bytes([0xAA, 0x77, func, length]) + data + bytes([checksum])

    @classmethod
    def build_lobot_packet(cls, cmd: int, params: List[int]) -> bytes:
        """Build Lobot / Hiwonder Bus packet: 0x55 0x55 <len> <cmd> <params...>."""
        length = len(params) + 2
        return bytes([0x55, 0x55, length, cmd]) + bytes(params)

    # =========================================================================
    # Angle Transformation & Clamping
    # =========================================================================

    def to_hardware_angle(self, channel_idx: int, logical_angle: int) -> int:
        """Apply inversion, limits, and trim to calculate raw hardware angle (0-180)."""
        # Clamp to configured limits
        min_lim = self.min_limits[channel_idx]
        max_lim = self.max_limits[channel_idx]
        angle = max(min_lim, min(max_lim, logical_angle))

        # Invert if required
        if self.inverted[channel_idx]:
            angle = 180 - angle

        # Apply calibration trim
        angle += self.trims[channel_idx]
        return max(0, min(180, int(angle)))

    def get_hardware_angles(self, logical_angles: List[int]) -> List[int]:
        """Convert list of 6 logical angles to hardware angles."""
        return [self.to_hardware_angle(i, a) for i, a in enumerate(logical_angles)]

    # =========================================================================
    # Actuation Commands
    # =========================================================================

    def send_angles(self, angles: List[int]) -> None:
        """
        Send all 6 servo angles to hardware immediately.
        angles: List of 6 integers (0-180 degrees).
        """
        assert len(angles) == self.NUM_SERVOS, "Must supply exactly 6 servo angles"
        self.target_angles = [max(0, min(180, int(a))) for a in angles]
        self.current_angles = list(self.target_angles)

        hw_angles = self.get_hardware_angles(self.current_angles)

        if self.protocol == ProtocolType.UHAND_UNO:
            packet = self.build_uhand_packet(0x01, hw_angles)
            desc = f"FUNC_SET_SERVO: {hw_angles}"
        else:
            # Lobot protocol: CMD_MULT_SERVO_MOVE = 0x03
            # Pulse width 500-2500 us (500 + angle * 2000 // 180)
            time_ms = 200
            params = [
                self.NUM_SERVOS,
                time_ms & 0xFF, (time_ms >> 8) & 0xFF
            ]
            for idx, a in enumerate(hw_angles, start=1):
                pulse = 500 + (a * 2000 // 180)
                params.extend([idx, pulse & 0xFF, (pulse >> 8) & 0xFF])
            packet = self.build_lobot_packet(0x03, params)
            desc = f"CMD_MULT_SERVO_MOVE: {hw_angles}"

        self._send_raw(packet, desc)

        if self.on_angles_updated:
            self.on_angles_updated(list(self.current_angles))

    def set_servo_angle(self, servo_idx: int, angle: int) -> None:
        """Set a single servo angle (0-indexed: 0=Thumb .. 5=Wrist)."""
        if 0 <= servo_idx < self.NUM_SERVOS:
            angles = list(self.current_angles)
            angles[servo_idx] = angle
            self.send_angles(angles)

    def set_buzzer(self, freq_hz: int = 1000, duration_ms: int = 200) -> None:
        """Trigger onboard buzzer with frequency and duration."""
        self.last_buzzer = (freq_hz, duration_ms)
        if self.protocol == ProtocolType.UHAND_UNO:
            # 0x02 FUNC_SET_BUZZER (len=4): freq_lo, freq_hi, time_lo, time_hi
            data = [
                freq_hz & 0xFF, (freq_hz >> 8) & 0xFF,
                duration_ms & 0xFF, (duration_ms >> 8) & 0xFF
            ]
            packet = self.build_uhand_packet(0x02, data)
            self._send_raw(packet, f"FUNC_SET_BUZZER: {freq_hz}Hz, {duration_ms}ms")
        else:
            self.log("SYS", f"Buzzer simulated ({freq_hz}Hz, {duration_ms}ms)")

    def set_rgb(self, r: int, g: int, b: int) -> None:
        """Set onboard RGB LED color (0-255 each)."""
        r = max(0, min(255, int(r)))
        g = max(0, min(255, int(g)))
        b = max(0, min(255, int(b)))
        self.rgb_color = (r, g, b)

        if self.protocol == ProtocolType.UHAND_UNO:
            packet = self.build_uhand_packet(0x03, [r, g, b])
            self._send_raw(packet, f"FUNC_SET_RGB: R={r} G={g} B={b}")
        else:
            self.log("SYS", f"RGB simulated: R={r} G={g} B={b}")

    def query_angles(self) -> None:
        """Request current hardware servo angles from uHand UNO."""
        if self.protocol == ProtocolType.UHAND_UNO:
            # 0x11 FUNC_READ_ANGLE (len=0): AA 77 11 00 EE
            packet = self.build_uhand_packet(0x11, [])
            self._send_raw(packet, "FUNC_READ_ANGLE query")
        else:
            self.log("SYS", "Query not supported by active protocol")

    # =========================================================================
    # Smooth Motion Interpolation
    # =========================================================================

    def move_smooth(
        self,
        target_angles: List[int],
        duration_ms: int = 500,
        steps: int = 20
    ) -> None:
        """
        Interpolate smoothly from current angles to target angles.
        Blocks the calling thread (or runs inside sequence worker).
        """
        start_angles = list(self.current_angles)
        target_angles = [max(0, min(180, int(a))) for a in target_angles]
        step_delay = (duration_ms / 1000.0) / max(1, steps)

        for step in range(1, steps + 1):
            if self._seq_stop_event.is_set():
                break
            alpha = step / float(steps)
            # Smooth step curve (cosine easing)
            ease = 0.5 * (1.0 - math.cos(alpha * math.pi))
            interp = [
                int(round(start + (target - start) * ease))
                for start, target in zip(start_angles, target_angles)
            ]
            self.send_angles(interp)
            time.sleep(step_delay)

    # =========================================================================
    # Sequence Player Engine
    # =========================================================================

    def play_sequence(
        self,
        keyframes: List[Tuple[Tuple[int, int, int, int, int, int], int]],
        loop: bool = False,
        speed_factor: float = 1.0,
        on_complete: Optional[Callable[[], None]] = None
    ) -> None:
        """
        Play a list of keyframes asynchronously in background.
        Each keyframe: ((s1, s2, s3, s4, s5, s6), duration_ms)
        """
        self.stop_sequence()
        self._seq_stop_event.clear()
        self._seq_pause_event.set()
        self.is_playing_sequence = True

        def _worker():
            try:
                iteration = 0
                while not self._seq_stop_event.is_set():
                    total_frames = len(keyframes)
                    for idx, (pose, dur_ms) in enumerate(keyframes):
                        if self._seq_stop_event.is_set():
                            break
                        self._seq_pause_event.wait()

                        scaled_dur = max(50, int(dur_ms / max(0.1, speed_factor)))
                        if self.on_sequence_step:
                            self.on_sequence_step(idx + 1, total_frames)

                        # Smoothly move to keyframe
                        steps = max(5, int(scaled_dur / 25))
                        self.move_smooth(list(pose), duration_ms=scaled_dur, steps=steps)

                    iteration += 1
                    if not loop or self._seq_stop_event.is_set():
                        break
            finally:
                self.is_playing_sequence = False
                if on_complete:
                    try:
                        on_complete()
                    except Exception:
                        pass

        self._seq_thread = threading.Thread(target=_worker, daemon=True)
        self._seq_thread.start()

    def pause_sequence(self) -> None:
        """Pause currently running sequence."""
        self._seq_pause_event.clear()

    def resume_sequence(self) -> None:
        """Resume paused sequence."""
        self._seq_pause_event.set()

    def stop_sequence(self) -> None:
        """Stop any playing sequence."""
        self._seq_stop_event.set()
        self._seq_pause_event.set()
        if self._seq_thread and self._seq_thread.is_alive():
            self._seq_thread.join(timeout=1.0)
        self.is_playing_sequence = False

    # =========================================================================
    # Raw Packet Transmission & Reception
    # =========================================================================

    def send_raw_hex(self, hex_str: str) -> bool:
        """Send raw hex string (e.g. 'AA 77 01 06 5A 5A 5A 5A 5A 5A DC')."""
        try:
            cleaned = hex_str.replace("0x", "").replace(" ", "").replace(",", "").strip()
            data = bytes.fromhex(cleaned)
            self._send_raw(data, f"RAW HEX: {data.hex(' ')}")
            return True
        except Exception as e:
            self.log("ERR", f"Invalid hex string: {e}")
            return False

    def _send_raw(self, packet: bytes, description: str = "") -> None:
        """Send byte array over serial link."""
        hex_dump = packet.hex(" ").upper()
        self.log("TX", f"{hex_dump}  ({description})")

        if self.simulation_mode:
            # Handle simulated responses if this was a query
            if len(packet) >= 4 and packet[0] == 0xAA and packet[1] == 0x77 and packet[2] == 0x11:
                # Simulate response
                resp_data = bytes(self.current_angles)
                resp_pkt = self.build_uhand_packet(0x11, resp_data)
                self.log("RX", f"{resp_pkt.hex(' ').upper()}  (SIMULATED FEEDBACK)")
            return

        if self.ser and self.ser.is_open:
            with self._lock:
                try:
                    self.ser.write(packet)
                    self.ser.flush()
                except Exception as ex:
                    self.log("ERR", f"Write error: {ex}")

    def _rx_worker(self) -> None:
        """Background thread listening for incoming serial data frames."""
        buffer = bytearray()
        while self._running and self.ser and self.ser.is_open:
            try:
                waiting = self.ser.in_waiting
                if waiting > 0:
                    chunk = self.ser.read(waiting)
                    buffer.extend(chunk)

                    # Parse packets: looking for 0xAA 0x77
                    while len(buffer) >= 4:
                        if buffer[0] == 0xAA and buffer[1] == 0x77:
                            func = buffer[2]
                            data_len = buffer[3]
                            total_len = 4 + data_len + 1  # header(2) + func + len + data + check
                            if len(buffer) >= total_len:
                                packet = bytes(buffer[:total_len])
                                buffer = buffer[total_len:]
                                self._handle_incoming_packet(packet, func, data_len)
                            else:
                                break
                        elif buffer[0] == 0x55 and buffer[1] == 0x55:
                            length = buffer[2]
                            total_len = 2 + 1 + length
                            if len(buffer) >= total_len:
                                packet = bytes(buffer[:total_len])
                                buffer = buffer[total_len:]
                                self._handle_incoming_lobot(packet)
                            else:
                                break
                        else:
                            # Drop invalid leading byte
                            buffer.pop(0)
                else:
                    time.sleep(0.02)
            except Exception as e:
                if self._running:
                    self.log("ERR", f"RX error: {e}")
                break

    def _handle_incoming_packet(self, packet: bytes, func: int, data_len: int) -> None:
        """Process incoming verified uHand UNO packet."""
        data = packet[4:4 + data_len]
        check = packet[-1]
        expected_check = self.calc_uhand_checksum(func, data_len, data)
        valid = (check == expected_check)

        hex_dump = packet.hex(" ").upper()
        status = "OK" if valid else f"CHECKSUM_MISMATCH (exp: {expected_check:02X})"
        self.log("RX", f"{hex_dump}  (func=0x{func:02X}, len={data_len}, {status})")

        if valid and func == 0x11 and data_len == self.NUM_SERVOS:
            # Angle feedback
            reported_angles = list(data)
            self.log("SYS", f"Received hardware angles: {reported_angles}")
            self.current_angles = reported_angles
            if self.on_angles_updated:
                self.on_angles_updated(list(self.current_angles))

    def _handle_incoming_lobot(self, packet: bytes) -> None:
        """Process incoming Lobot packet."""
        hex_dump = packet.hex(" ").upper()
        self.log("RX", f"{hex_dump}  (LOBOT PACKET)")

    # =========================================================================
    # Configuration Persistence
    # =========================================================================

    def save_calibration(self, filepath: str) -> None:
        """Save trims, inversions, and limits to a JSON file."""
        data = {
            "trims": self.trims,
            "inverted": self.inverted,
            "min_limits": self.min_limits,
            "max_limits": self.max_limits
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.log("SYS", f"Saved calibration to {filepath}")

    def load_calibration(self, filepath: str) -> bool:
        """Load trims, inversions, and limits from a JSON file."""
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.trims = data.get("trims", self.trims)
            self.inverted = data.get("inverted", self.inverted)
            self.min_limits = data.get("min_limits", self.min_limits)
            self.max_limits = data.get("max_limits", self.max_limits)
            self.log("SYS", f"Loaded calibration from {filepath}")
            return True
        except Exception as e:
            self.log("ERR", f"Failed loading calibration: {e}")
            return False

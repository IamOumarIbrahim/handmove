"""
Core Hardware Controller for Hiwonder uHand UNO and compatible robotic hands.
Handles Hiwonder BLE and serial communications, protocol framing, calibration,
kinematics state, preset sequences, and peripheral actuators (Buzzer, RGB LED).
"""

from __future__ import annotations

import enum
import asyncio
import json
import logging
import math
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple, Union

from connection_settings import (
    is_arduino_usb_port,
    load_connection_settings,
    save_verified_ble_connection,
    save_verified_serial_connection,
)

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

try:
    from bleak import BleakClient, BleakScanner
    BLE_AVAILABLE = True
except ImportError:
    BleakClient = None
    BleakScanner = None
    BLE_AVAILABLE = False


class ProtocolType(enum.Enum):
    UHAND_UNO = "uHand UNO (0xAA 0x77)"
    LOBOT_BUS = "Lobot / Hiwonder Bus (0x55 0x55)"


class HandController:
    """
    High-level controller for the uHand UNO robotic hand.
    Supports the Wonderbot-compatible BLE UART, the wired uHand UNO UART, and offline simulation.
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
        port: str = "",
        baudrate: int = 9600,
        protocol: ProtocolType = ProtocolType.UHAND_UNO,
        simulation_mode: bool = False,
        transport: Optional[str] = None,
        ble_name: Optional[str] = None,
        ble_address: Optional[str] = None,
    ):
        defaults = load_connection_settings()
        self.transport = (transport or defaults["transport"]).lower()
        self.port = port
        self.baudrate = baudrate
        self.protocol = protocol
        self.simulation_mode = simulation_mode
        self.ble_name = ble_name or defaults["ble_name"]
        self.ble_address = ble_address or defaults["ble_address"]
        self.ble_service_uuid = defaults["ble_service_uuid"]
        self.ble_characteristic_uuid = defaults["ble_characteristic_uuid"]

        self.ser: Optional[serial.Serial] = None
        self._ble_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ble_loop_thread: Optional[threading.Thread] = None
        self._ble_loop_ready = threading.Event()
        self._ble_client = None
        self._ble_characteristic = None
        self._ble_write_response = False
        self._ble_connected = False
        self._ble_lock = asyncio.Lock()
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
        self._hardware_response = threading.Event()

    # =========================================================================
    # Connection Management
    # =========================================================================

    def log(self, direction: str, text: str) -> None:
        """Log transport or internal events."""
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

        if self.transport == "ble":
            return self._connect_ble()

        if self.transport != "serial":
            self.transport = "ble"
            return self._connect_ble()

        if not SERIAL_AVAILABLE:
            msg = "pyserial is not installed; hardware connection is unavailable. Enable Simulation Mode explicitly to run offline."
            self.log("ERR", msg)
            if self.on_connection_changed:
                self.on_connection_changed(False, msg)
            return False, msg

        if not self.port.strip():
            msg = (
                "No serial port selected. Connect a USB-to-TTL adapter to the uHand UNO UART, "
                "then select its COM port (9600 baud, 8N1)."
            )
            self.log("ERR", msg)
            if self.on_connection_changed:
                self.on_connection_changed(False, msg)
            return False, msg

        if is_arduino_usb_port(self.port):
            msg = (
                f"{self.port} is the Arduino Uno USB interface, not the uHand UNO command UART. "
                "Use a USB-to-TTL adapter on the hand's 4-pin UART: adapter RXD to IO12 (hand TX), "
                "adapter TXD to IO10 (hand RX), and GND to GND. Select the adapter's COM port."
            )
            self.log("ERR", msg)
            if self.on_connection_changed:
                self.on_connection_changed(False, msg)
            return False, msg

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
            self._hardware_response.clear()
            self._running = True
            self._rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
            self._rx_thread.start()

            if self.protocol == ProtocolType.UHAND_UNO:
                query = self.build_uhand_packet(0x11, [])
                self._send_raw(query, "uHand UNO connection check: FUNC_READ_ANGLE")
                if not self._hardware_response.wait(timeout=1.5):
                    self._running = False
                    if self.ser and self.ser.is_open:
                        self.ser.close()
                    self.ser = None
                    if self._rx_thread and self._rx_thread.is_alive():
                        self._rx_thread.join(timeout=0.3)
                    msg = (
                        f"Opened {self.port} at {self.baudrate} baud, but the uHand UNO did not answer "
                        "the angle query. Check that this is the USB-to-TTL adapter connected to IO12/IO10, "
                        "that TX/RX are crossed with common GND, and that the hand is powered."
                    )
                    self.log("ERR", msg)
                    if self.on_connection_changed:
                        self.on_connection_changed(False, msg)
                    return False, msg

            msg = f"Connected to {self.port} at {self.baudrate} baud"
            if self.protocol == ProtocolType.UHAND_UNO:
                try:
                    save_verified_serial_connection(self.port, self.baudrate, self.protocol.value)
                    self.log("SYS", "Saved serial connection as default.")
                except OSError as ex:
                    self.log("WARN", f"Connected, but could not save default settings: {ex}")
            self.log("SYS", msg)
            if self.on_connection_changed:
                self.on_connection_changed(True, msg)
            return True, msg
        except Exception as ex:
            self._running = False
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None
            msg = f"Failed to connect to {self.port}: {ex}"
            self.log("ERR", msg)
            if self.on_connection_changed:
                self.on_connection_changed(False, msg)
            return False, msg

    def disconnect(self) -> None:
        """Close the active serial or BLE connection."""
        self._running = False
        self.stop_sequence()
        if self._ble_loop and self._ble_connected:
            try:
                future = asyncio.run_coroutine_threadsafe(self._disconnect_ble_async(), self._ble_loop)
                future.result(timeout=5)
            except Exception as ex:
                self.log("WARN", f"BLE disconnect cleanup: {ex}")
        self._ble_connected = False
        self._ble_characteristic = None
        self._ble_client = None
        if self._ble_loop:
            self._ble_loop.call_soon_threadsafe(self._ble_loop.stop)
        if self._ble_loop_thread and self._ble_loop_thread.is_alive():
            self._ble_loop_thread.join(timeout=2)
        self._ble_loop = None
        self._ble_loop_thread = None
        self._ble_loop_ready.clear()
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
        if self.transport == "ble":
            return self._ble_connected
        return self.ser is not None and self.ser.is_open

    def _connect_ble(self) -> Tuple[bool, str]:
        """Connect to the Hiwonder BLE UART and select its transparent serial characteristic."""
        if not BLE_AVAILABLE:
            msg = "Bluetooth support requires bleak. Install dependencies with: python -m pip install -r requirements.txt"
            self.log("ERR", msg)
            if self.on_connection_changed:
                self.on_connection_changed(False, msg)
            return False, msg

        try:
            self._start_ble_loop()
            future = asyncio.run_coroutine_threadsafe(self._connect_ble_async(), self._ble_loop)
            name, address, service_uuid, characteristic_uuid = future.result(timeout=20)
            self.ble_name = name
            self.ble_address = address
            self.ble_service_uuid = service_uuid
            self.ble_characteristic_uuid = characteristic_uuid
            self._ble_connected = True
            saved = False
            try:
                save_verified_ble_connection(name, address, service_uuid, characteristic_uuid)
                saved = True
            except OSError as save_error:
                self.log("WARN", f"BLE is connected, but default settings could not be saved: {save_error}")
            message = f"Connected to {name} ({address}) over BLE; Hiwonder app-control protocol ready"
            self.log("SYS", message)
            self.log("SYS", f"BLE UART: service {service_uuid}, characteristic {characteristic_uuid}")
            if saved:
                self.log("SYS", "Saved BLE connection as default.")
            if self.on_connection_changed:
                self.on_connection_changed(True, message)
            return True, message
        except Exception as ex:
            self._ble_connected = False
            self._ble_client = None
            self._ble_characteristic = None
            msg = f"Could not connect to the Hiwonder BLE device: {ex}"
            self.log("ERR", msg)
            if self.on_connection_changed:
                self.on_connection_changed(False, msg)
            return False, msg

    def _start_ble_loop(self) -> None:
        if self._ble_loop and self._ble_loop.is_running():
            return
        self._ble_loop_ready.clear()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._ble_lock = asyncio.Lock()
            self._ble_loop = loop
            self._ble_loop_ready.set()
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

        self._ble_loop_thread = threading.Thread(target=run_loop, name="uHand-BLE", daemon=True)
        self._ble_loop_thread.start()
        if not self._ble_loop_ready.wait(timeout=3):
            raise RuntimeError("BLE event loop did not start")

    async def _connect_ble_async(self) -> Tuple[str, str, str, str]:
        devices = await BleakScanner.discover(timeout=5.0)
        device = None
        if self.ble_address:
            device = next((d for d in devices if d.address.casefold() == self.ble_address.casefold()), None)
        if device is None and self.ble_name:
            target = self.ble_name.casefold()
            device = next(
                (d for d in devices if d.address.casefold() == target),
                None,
            )
            if device is None:
                device = next((d for d in devices if d.name and target in d.name.casefold()), None)
        if device is None:
            found = ", ".join(f"{d.name or 'Unknown'} ({d.address})" for d in devices)
            raise RuntimeError(
                f"'{self.ble_name or 'Hiwonder'}' is not advertising. Check that the hand is powered and nearby; "
                "disconnect Wonderbot or another phone from the hand before connecting the PC. "
                f"Nearby BLE devices: {found or 'none'}"
            )

        client = BleakClient(device)
        await client.connect()
        if not client.is_connected:
            raise RuntimeError(f"BLE connection to {device.name or device.address} did not complete")

        candidates = []
        preferred_services = tuple(dict.fromkeys((
            self.ble_service_uuid.casefold(),
            "0000fff0-0000-1000-8000-00805f9b34fb",
            "0000ffe0-0000-1000-8000-00805f9b34fb",
        )))
        for service in client.services:
            for char in service.characteristics:
                props = {p.casefold() for p in char.properties}
                if "write" in props or "write-without-response" in props:
                    candidates.append((service.uuid.casefold(), char, props))

        selected = None
        for preferred_service in preferred_services:
            selected = next(
                (item for item in candidates
                 if item[0] == preferred_service and item[1].uuid.casefold() == self.ble_characteristic_uuid.casefold()),
                None,
            )
            if selected:
                break
        if selected is None:
            selected = next(
                (item for item in candidates if item[1].uuid.casefold() == self.ble_characteristic_uuid.casefold()),
                None,
            )
        if selected is None:
            await client.disconnect()
            raise RuntimeError("The connected BLE device has no writable Hiwonder UART characteristic")

        service_uuid, characteristic, properties = selected
        self._ble_client = client
        self._ble_characteristic = characteristic
        self._ble_write_response = "write" in properties
        self.ble_service_uuid = service_uuid
        self.ble_characteristic_uuid = characteristic.uuid

        if "notify" in properties:
            try:
                await client.start_notify(characteristic, self._on_ble_notification)
            except Exception as ex:
                self.log("WARN", f"BLE notifications unavailable: {ex}")
        return device.name or self.ble_name or "Hiwonder", device.address, service_uuid, characteristic.uuid

    async def _disconnect_ble_async(self) -> None:
        if self._ble_client and self._ble_client.is_connected:
            try:
                if self._ble_characteristic and "notify" in self._ble_characteristic.properties:
                    await self._ble_client.stop_notify(self._ble_characteristic)
            except Exception:
                pass
            await self._ble_client.disconnect()

    def _on_ble_notification(self, sender, data: bytearray) -> None:
        text = bytes(data).decode("utf-8", errors="replace").strip()
        if text:
            self.log("RX", f"BLE: {text}")

    def _queue_ble_commands(self, commands: List[str], description: str = "") -> None:
        if not self._ble_connected or not self._ble_loop or not self._ble_characteristic:
            self.log("ERR", "BLE command not sent: connect to the Hiwonder device first")
            return
        for command in commands:
            self.log("TX", f"BLE {command} ({description})")
        future = asyncio.run_coroutine_threadsafe(self._write_ble_commands(commands), self._ble_loop)

        def report_error(completed) -> None:
            try:
                completed.result()
            except Exception as ex:
                self.log("ERR", f"BLE write error: {ex}")
                self._ble_connected = False
                if self.on_connection_changed:
                    self.on_connection_changed(False, f"BLE write failed: {ex}")

        future.add_done_callback(report_error)

    async def _write_ble_commands(self, commands: List[str]) -> None:
        async with self._ble_lock:
            if not self._ble_client or not self._ble_client.is_connected or not self._ble_characteristic:
                raise RuntimeError("BLE connection closed before command was written")
            for command in commands:
                await self._ble_client.write_gatt_char(
                    self._ble_characteristic, command.encode("ascii"), response=self._ble_write_response
                )

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

    def send_angles(self, angles: List[int], force: bool = False) -> None:
        """
        Send all 6 servo angles to hardware immediately.
        angles: List of 6 integers (0-180 degrees).
        """
        assert len(angles) == self.NUM_SERVOS, "Must supply exactly 6 servo angles"
        previous_angles = list(self.current_angles)
        self.target_angles = [max(0, min(180, int(a))) for a in angles]
        self.current_angles = list(self.target_angles)

        hw_angles = self.get_hardware_angles(self.current_angles)

        if self.transport == "ble" and not self.simulation_mode:
            commands = [
                f"{chr(ord('A') + i)}{angle}$"
                for i, angle in enumerate(hw_angles)
                if force or self.current_angles[i] != previous_angles[i]
            ]
            if not commands:
                return
            self._queue_ble_commands(commands, "Hiwonder app servo angles")
            if self.on_angles_updated:
                self.on_angles_updated(list(self.current_angles))
            return

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
            if self.transport == "ble" and not self.simulation_mode:
                self.current_angles[servo_idx] = max(0, min(180, int(angle)))
                self.target_angles[servo_idx] = self.current_angles[servo_idx]
                app_angle = self.to_hardware_angle(servo_idx, self.current_angles[servo_idx])
                command = f"{chr(ord('A') + servo_idx)}{app_angle}$"
                self._queue_ble_commands([command], f"{self.SERVO_NAMES[servo_idx]} angle")
                if self.on_angles_updated:
                    self.on_angles_updated(list(self.current_angles))
                return
            angles = list(self.current_angles)
            angles[servo_idx] = angle
            self.send_angles(angles)

    def set_buzzer(self, freq_hz: int = 1000, duration_ms: int = 200) -> None:
        """Trigger onboard buzzer with frequency and duration."""
        self.last_buzzer = (freq_hz, duration_ms)
        if self.transport == "ble" and not self.simulation_mode:
            # The official firmware exposes a fixed app tone via Z1/Z0, not arbitrary frequency.
            self._queue_ble_commands(["Z1$"], "Hiwonder buzzer on")
            if duration_ms > 0:
                timer = threading.Timer(duration_ms / 1000.0, lambda: self._queue_ble_commands(["Z0$"], "Hiwonder buzzer off"))
                timer.daemon = True
                timer.start()
            return
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

        if self.transport == "ble" and not self.simulation_mode:
            self._queue_ble_commands([f"G{r}$", f"H{g}$", f"I{b}$", "J$"], "Hiwonder RGB LED")
            return

        if self.protocol == ProtocolType.UHAND_UNO:
            packet = self.build_uhand_packet(0x03, [r, g, b])
            self._send_raw(packet, f"FUNC_SET_RGB: R={r} G={g} B={b}")
        else:
            self.log("SYS", f"RGB simulated: R={r} G={g} B={b}")

    def query_angles(self) -> None:
        """Request current hardware servo angles from uHand UNO."""
        if self.transport == "ble" and not self.simulation_mode:
            self.log("WARN", "The Hiwonder BLE app protocol does not provide angle feedback; BLE angle queries are unavailable.")
            return
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
        if self.transport == "ble" and not self.simulation_mode:
            self.log("ERR", "Raw AA 77 hex packets are for serial UART. BLE uses Hiwonder ASCII commands such as A90$.")
            return False
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
        else:
            self.log("ERR", "Packet not sent: connect the selected hardware transport or enable simulation explicitly.")

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
            self._hardware_response.set()
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

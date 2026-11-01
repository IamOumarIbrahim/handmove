#   HANDMOVE - uHand UNO Controller (hardware controller)
#        Oumar Ibrahim U22200741

# controller for the hiwonder uHand UNO robotic hand
# does the BLE and serial connection, building the packets, calibration,
# the angles, sequences and the buzzer / rgb led

import enum
import asyncio
import json
import logging
import math
import os
import threading
import time

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


# talks to the uHand UNO over the BLE uart (same as the Wonderbot app),
# the wired uart or a simulation with no hardware
class HandController:
    NUM_SERVOS = 6
    SERVO_NAMES = [
        "Thumb",
        "Index",
        "Middle",
        "Ring",
        "Pinky",
        "Wrist / Base"
    ]

    def __init__(self, port="", baudrate=9600, protocol=ProtocolType.UHAND_UNO, simulation_mode=False,
                 transport=None, ble_name=None, ble_address=None):
        defaults = load_connection_settings()
        if transport:
            self.transport = transport.lower()
        else:
            self.transport = defaults["transport"].lower()
        self.port = port
        self.baudrate = baudrate
        self.protocol = protocol
        self.simulation_mode = simulation_mode
        if ble_name:
            self.ble_name = ble_name
        else:
            self.ble_name = defaults["ble_name"]
        if ble_address:
            self.ble_address = ble_address
        else:
            self.ble_address = defaults["ble_address"]
        self.ble_service_uuid = defaults["ble_service_uuid"]
        self.ble_characteristic_uuid = defaults["ble_characteristic_uuid"]

        self.ser = None
        self._ble_loop = None
        self._ble_loop_thread = None
        self._ble_loop_ready = threading.Event()
        self._ble_client = None
        self._ble_characteristic = None
        self._ble_write_response = False
        self._ble_connected = False
        self._ble_lock = asyncio.Lock()
        self._lock = threading.Lock()
        self._running = False
        self._rx_thread = None

        # angles (0 - 180 degrees)
        self.current_angles = [90, 90, 90, 90, 90, 90]
        self.target_angles = [90, 90, 90, 90, 90, 90]

        # calibration: trim (-45 to +45 deg), invert and limits for each servo
        self.trims = [0, 0, 0, 0, 0, 0]
        self.inverted = [False, False, False, False, False, False]
        self.min_limits = [0, 0, 0, 0, 0, 0]
        self.max_limits = [180, 180, 180, 180, 180, 180]

        # buzzer and led
        self.rgb_color = (0, 0, 0)
        self.last_buzzer = (0, 0)

        # sequence player
        self._seq_thread = None
        self._seq_stop_event = threading.Event()
        self._seq_pause_event = threading.Event()
        self._seq_pause_event.set()
        self.is_playing_sequence = False

        # callbacks for the gui
        self.on_log = None  # (direction, text)
        self.on_angles_updated = None  # (angles)
        self.on_connection_changed = None  # (connected, message)
        self.on_sequence_step = None  # (step, total)
        self._hardware_response = threading.Event()

    #==========================================================================
    # connecting

    def log(self, direction, text):
        if self.on_log:
            try:
                self.on_log(direction, text)
            except Exception:
                pass

    # tells the gui the connection failed and returns (False, msg)
    def _fail(self, msg):
        self.log("ERR", msg)
        if self.on_connection_changed:
            self.on_connection_changed(False, msg)
        return False, msg

    def connect(self):
        if self.simulation_mode:
            self.log("SYS", "Connected in Simulation Mode (Virtual uHand UNO)")
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
            return self._fail(msg)

        if not self.port.strip():
            msg = (
                "No serial port selected. Connect a USB-to-TTL adapter to the uHand UNO UART, "
                "then select its COM port (9600 baud, 8N1)."
            )
            return self._fail(msg)

        if is_arduino_usb_port(self.port):
            msg = (
                f"{self.port} is the Arduino Uno USB interface, not the uHand UNO command UART. "
                "Use a USB-to-TTL adapter on the hand's 4-pin UART: adapter RXD to IO12 (hand TX), "
                "adapter TXD to IO10 (hand RX), and GND to GND. Select the adapter's COM port."
            )
            return self._fail(msg)

        try:
            self.ser = serial.Serial()
            self.ser.port = self.port
            self.ser.baudrate = self.baudrate
            self.ser.bytesize = serial.EIGHTBITS
            self.ser.parity = serial.PARITY_NONE
            self.ser.stopbits = serial.STOPBITS_ONE
            self.ser.timeout = 0.2
            self.ser.write_timeout = 1.0
            # no DTR/RTS pulse so the arduino does not reset into midpoint mode
            self.ser.dtr = False
            self.ser.rts = False
            self.ser.open()
            self._hardware_response.clear()
            self._running = True
            self._rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
            self._rx_thread.start()

            if self.protocol == ProtocolType.UHAND_UNO:
                # ask for the angles to check the hand is realy there
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
                    return self._fail(msg)

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
            return self._fail(msg)

    def disconnect(self):
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

    # simulation always counts as connected
    def is_connected(self):
        if self.simulation_mode:
            return True
        if self.transport == "ble":
            return self._ble_connected
        return self.ser is not None and self.ser.is_open

    # connects to the hiwonder ble uart and picks its serial characteristic
    def _connect_ble(self):
        if not BLE_AVAILABLE:
            msg = "Bluetooth support requires bleak. Install dependencies with: python -m pip install -r requirements.txt"
            return self._fail(msg)

        try:
            self._start_ble_loop()
            future = asyncio.run_coroutine_threadsafe(self._connect_ble_async(), self._ble_loop)
            result = future.result(timeout=20)
            name = result[0]
            address = result[1]
            service_uuid = result[2]
            characteristic_uuid = result[3]
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
            return self._fail(msg)

    # bleak needs an asyncio loop, it runs on its own thread
    def _start_ble_loop(self):
        if self._ble_loop and self._ble_loop.is_running():
            return
        self._ble_loop_ready.clear()

        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._ble_lock = asyncio.Lock()
            self._ble_loop = loop
            self._ble_loop_ready.set()
            loop.run_forever()
            # loop was stopped, cancel what is left
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

    async def _connect_ble_async(self):
        devices = await BleakScanner.discover(timeout=5.0)
        device = None
        # first look for the saved address
        if self.ble_address:
            for d in devices:
                if d.address.casefold() == self.ble_address.casefold():
                    device = d
                    break
        # then the name (it can also be an address)
        if device is None and self.ble_name:
            target = self.ble_name.casefold()
            for d in devices:
                if d.address.casefold() == target:
                    device = d
                    break
            if device is None:
                for d in devices:
                    if d.name and target in d.name.casefold():
                        device = d
                        break
        if device is None:
            found_list = []
            for d in devices:
                if d.name:
                    found_list.append(f"{d.name} ({d.address})")
                else:
                    found_list.append(f"Unknown ({d.address})")
            found = ", ".join(found_list)
            if not found:
                found = "none"
            wanted = self.ble_name
            if not wanted:
                wanted = "Hiwonder"
            raise RuntimeError(
                f"'{wanted}' is not advertising. Check that the hand is powered and nearby; "
                "disconnect Wonderbot or another phone from the hand before connecting the PC. "
                f"Nearby BLE devices: {found}"
            )

        client = BleakClient(device)
        await client.connect()
        if not client.is_connected:
            if device.name:
                shown = device.name
            else:
                shown = device.address
            raise RuntimeError(f"BLE connection to {shown} did not complete")

        # every characteristic we can write to
        candidates = []
        preferred_services = []
        for uuid in [self.ble_service_uuid.casefold(),
                     "0000fff0-0000-1000-8000-00805f9b34fb",
                     "0000ffe0-0000-1000-8000-00805f9b34fb"]:
            if uuid not in preferred_services:
                preferred_services.append(uuid)
        for service in client.services:
            for char in service.characteristics:
                props = []
                for p in char.properties:
                    props.append(p.casefold())
                if "write" in props or "write-without-response" in props:
                    candidates.append((service.uuid.casefold(), char, props))

        wanted_char = self.ble_characteristic_uuid.casefold()
        selected = None
        for preferred_service in preferred_services:
            for item in candidates:
                if item[0] == preferred_service and item[1].uuid.casefold() == wanted_char:
                    selected = item
                    break
            if selected:
                break
        if selected is None:
            for item in candidates:
                if item[1].uuid.casefold() == wanted_char:
                    selected = item
                    break
        if selected is None:
            await client.disconnect()
            raise RuntimeError("The connected BLE device has no writable Hiwonder UART characteristic")

        service_uuid = selected[0]
        characteristic = selected[1]
        properties = selected[2]
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
        name = device.name
        if not name:
            name = self.ble_name
        if not name:
            name = "Hiwonder"
        return name, device.address, service_uuid, characteristic.uuid

    async def _disconnect_ble_async(self):
        if self._ble_client and self._ble_client.is_connected:
            try:
                if self._ble_characteristic and "notify" in self._ble_characteristic.properties:
                    await self._ble_client.stop_notify(self._ble_characteristic)
            except Exception:
                pass
            await self._ble_client.disconnect()

    def _on_ble_notification(self, sender, data):
        text = bytes(data).decode("utf-8", errors="replace").strip()
        if text:
            self.log("RX", f"BLE: {text}")

    def _queue_ble_commands(self, commands, description=""):
        if not self._ble_connected or not self._ble_loop or not self._ble_characteristic:
            self.log("ERR", "BLE command not sent: connect to the Hiwonder device first")
            return
        for command in commands:
            self.log("TX", f"BLE {command} ({description})")
        future = asyncio.run_coroutine_threadsafe(self._write_ble_commands(commands), self._ble_loop)

        def report_error(completed):
            try:
                completed.result()
            except Exception as ex:
                self.log("ERR", f"BLE write error: {ex}")
                self._ble_connected = False
                if self.on_connection_changed:
                    self.on_connection_changed(False, f"BLE write failed: {ex}")

        future.add_done_callback(report_error)

    async def _write_ble_commands(self, commands):
        async with self._ble_lock:
            if not self._ble_client or not self._ble_client.is_connected or not self._ble_characteristic:
                raise RuntimeError("BLE connection closed before command was written")
            for command in commands:
                await self._ble_client.write_gatt_char(
                    self._ble_characteristic, command.encode("ascii"), response=self._ble_write_response
                )

    #==========================================================================
    # packets

    # uHand checksum = 0xFF - (sum & 0xFF)
    @staticmethod
    def calc_uhand_checksum(func, length, data):
        total = func + length
        for b in data:
            total = total + b
        total = total & 0xFF
        return (0xFF - total) & 0xFF

    # uHand packet: 0xAA 0x77 <func> <len> <data...> <check>
    @staticmethod
    def build_uhand_packet(func, data):
        if isinstance(data, list):
            data = bytes(data)
        length = len(data)
        checksum = HandController.calc_uhand_checksum(func, length, data)
        return bytes([0xAA, 0x77, func, length]) + data + bytes([checksum])

    # lobot / hiwonder bus packet: 0x55 0x55 <len> <cmd> <params...>
    @staticmethod
    def build_lobot_packet(cmd, params):
        length = len(params) + 2
        return bytes([0x55, 0x55, length, cmd]) + bytes(params)

    #==========================================================================
    # angles

    # limits, invert and trim give the real angle for the servo (0-180)
    def to_hardware_angle(self, channel_idx, logical_angle):
        min_lim = self.min_limits[channel_idx]
        max_lim = self.max_limits[channel_idx]
        angle = logical_angle
        if angle > max_lim:
            angle = max_lim
        if angle < min_lim:
            angle = min_lim

        if self.inverted[channel_idx]:
            angle = 180 - angle

        angle += self.trims[channel_idx]
        angle = int(angle)
        if angle > 180:
            angle = 180
        if angle < 0:
            angle = 0
        return angle

    def get_hardware_angles(self, logical_angles):
        hw = []
        for i in range(len(logical_angles)):
            hw.append(self.to_hardware_angle(i, logical_angles[i]))
        return hw

    #==========================================================================
    # moving the servos

    # sends all 6 angles (0-180) right away
    def send_angles(self, angles, force=False):
        assert len(angles) == self.NUM_SERVOS, "Must supply exactly 6 servo angles"
        previous_angles = list(self.current_angles)
        new_target = []
        for a in angles:
            new_target.append(clamp(int(a), 0, 180))
        self.target_angles = new_target
        self.current_angles = list(self.target_angles)

        hw_angles = self.get_hardware_angles(self.current_angles)

        if self.transport == "ble" and not self.simulation_mode:
            # only the servos that changed (or all of them with force)
            commands = []
            for i in range(len(hw_angles)):
                if force or self.current_angles[i] != previous_angles[i]:
                    letter = chr(ord("A") + i)
                    commands.append(f"{letter}{hw_angles[i]}$")
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
            # lobot CMD_MULT_SERVO_MOVE = 0x03
            # pulse is 500-2500 us (500 + angle * 2000 // 180)
            time_ms = 200
            params = [self.NUM_SERVOS, time_ms & 0xFF, (time_ms >> 8) & 0xFF]
            for idx in range(len(hw_angles)):
                a = hw_angles[idx]
                pulse = 500 + (a * 2000 // 180)
                params.append(idx + 1)
                params.append(pulse & 0xFF)
                params.append((pulse >> 8) & 0xFF)
            packet = self.build_lobot_packet(0x03, params)
            desc = f"CMD_MULT_SERVO_MOVE: {hw_angles}"

        self._send_raw(packet, desc)

        if self.on_angles_updated:
            self.on_angles_updated(list(self.current_angles))

    # one servo (0 = thumb .. 5 = wrist)
    def set_servo_angle(self, servo_idx, angle):
        if servo_idx >= 0 and servo_idx < self.NUM_SERVOS:
            if self.transport == "ble" and not self.simulation_mode:
                self.current_angles[servo_idx] = clamp(int(angle), 0, 180)
                self.target_angles[servo_idx] = self.current_angles[servo_idx]
                app_angle = self.to_hardware_angle(servo_idx, self.current_angles[servo_idx])
                letter = chr(ord("A") + servo_idx)
                command = f"{letter}{app_angle}$"
                self._queue_ble_commands([command], f"{self.SERVO_NAMES[servo_idx]} angle")
                if self.on_angles_updated:
                    self.on_angles_updated(list(self.current_angles))
                return
            angles = list(self.current_angles)
            angles[servo_idx] = angle
            self.send_angles(angles)

    def _buzzer_off(self):
        self._queue_ble_commands(["Z0$"], "Hiwonder buzzer off")

    def set_buzzer(self, freq_hz=1000, duration_ms=200):
        self.last_buzzer = (freq_hz, duration_ms)
        if self.transport == "ble" and not self.simulation_mode:
            # the firmware only has one fixed tone over Z1/Z0, no frequency
            self._queue_ble_commands(["Z1$"], "Hiwonder buzzer on")
            if duration_ms > 0:
                timer = threading.Timer(duration_ms / 1000.0, self._buzzer_off)
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

    # rgb led colour (0-255 each)
    def set_rgb(self, r, g, b):
        r = clamp(int(r), 0, 255)
        g = clamp(int(g), 0, 255)
        b = clamp(int(b), 0, 255)
        self.rgb_color = (r, g, b)

        if self.transport == "ble" and not self.simulation_mode:
            self._queue_ble_commands([f"G{r}$", f"H{g}$", f"I{b}$", "J$"], "Hiwonder RGB LED")
            return

        if self.protocol == ProtocolType.UHAND_UNO:
            packet = self.build_uhand_packet(0x03, [r, g, b])
            self._send_raw(packet, f"FUNC_SET_RGB: R={r} G={g} B={b}")
        else:
            self.log("SYS", f"RGB simulated: R={r} G={g} B={b}")

    # asks the hand for its servo angles
    def query_angles(self):
        if self.transport == "ble" and not self.simulation_mode:
            self.log("WARN", "The Hiwonder BLE app protocol does not provide angle feedback; BLE angle queries are unavailable.")
            return
        if self.protocol == ProtocolType.UHAND_UNO:
            # 0x11 FUNC_READ_ANGLE (len=0): AA 77 11 00 EE
            packet = self.build_uhand_packet(0x11, [])
            self._send_raw(packet, "FUNC_READ_ANGLE query")
        else:
            self.log("SYS", "Query not supported by active protocol")

    #==========================================================================
    # smooth movement

    # goes from the current angles to target_angles in small steps
    # this blocks so call it from a thread (the sequence player does)
    def move_smooth(self, target_angles, duration_ms=500, steps=20):
        start_angles = list(self.current_angles)
        targets = []
        for a in target_angles:
            targets.append(clamp(int(a), 0, 180))
        n_steps = steps
        if n_steps < 1:
            n_steps = 1
        step_delay = (duration_ms / 1000.0) / n_steps

        for step in range(1, steps + 1):
            if self._seq_stop_event.is_set():
                break
            alpha = step / float(steps)
            # cosine easing so it starts and stops slow
            ease = 0.5 * (1.0 - math.cos(alpha * math.pi))
            interp = []
            for i in range(min(len(start_angles), len(targets))):
                start = start_angles[i]
                interp.append(int(round(start + (targets[i] - start) * ease)))
            self.send_angles(interp)
            time.sleep(step_delay)

    #==========================================================================
    # sequence player

    # plays the keyframes on a background thread
    # each keyframe is ((s1, s2, s3, s4, s5, s6), duration_ms)
    def play_sequence(self, keyframes, loop=False, speed_factor=1.0, on_complete=None):
        self.stop_sequence()
        self._seq_stop_event.clear()
        self._seq_pause_event.set()
        self.is_playing_sequence = True

        def worker():
            try:
                iteration = 0
                while not self._seq_stop_event.is_set():
                    total_frames = len(keyframes)
                    for idx in range(total_frames):
                        pose = keyframes[idx][0]
                        dur_ms = keyframes[idx][1]
                        if self._seq_stop_event.is_set():
                            break
                        self._seq_pause_event.wait()

                        speed = speed_factor
                        if speed < 0.1:
                            speed = 0.1
                        scaled_dur = int(dur_ms / speed)
                        if scaled_dur < 50:
                            scaled_dur = 50
                        if self.on_sequence_step:
                            self.on_sequence_step(idx + 1, total_frames)

                        # move smooth to the keyframe
                        steps = int(scaled_dur / 25)
                        if steps < 5:
                            steps = 5
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

        self._seq_thread = threading.Thread(target=worker, daemon=True)
        self._seq_thread.start()

    def pause_sequence(self):
        self._seq_pause_event.clear()

    def resume_sequence(self):
        self._seq_pause_event.set()

    def stop_sequence(self):
        self._seq_stop_event.set()
        self._seq_pause_event.set()
        if self._seq_thread and self._seq_thread.is_alive():
            self._seq_thread.join(timeout=1.0)
        self.is_playing_sequence = False

    #==========================================================================
    # sending and reciving raw packets

    # sends a hex string like 'AA 77 01 06 5A 5A 5A 5A 5A 5A DC'
    def send_raw_hex(self, hex_str):
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

    def _send_raw(self, packet, description=""):
        hex_dump = packet.hex(" ").upper()
        self.log("TX", f"{hex_dump}  ({description})")

        if self.simulation_mode:
            # fake answer if it was a angle query
            if len(packet) >= 4 and packet[0] == 0xAA and packet[1] == 0x77 and packet[2] == 0x11:
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

    # background thread that reads the serial port and finds the packets
    def _rx_worker(self):
        buffer = bytearray()
        while self._running and self.ser and self.ser.is_open:
            try:
                waiting = self.ser.in_waiting
                if waiting > 0:
                    chunk = self.ser.read(waiting)
                    buffer.extend(chunk)

                    # look for 0xAA 0x77 (uHand) or 0x55 0x55 (lobot)
                    while len(buffer) >= 4:
                        if buffer[0] == 0xAA and buffer[1] == 0x77:
                            func = buffer[2]
                            data_len = buffer[3]
                            # header(2) + func + len + data + check
                            total_len = 4 + data_len + 1
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
                            # not a header, drop the first byte
                            buffer.pop(0)
                else:
                    time.sleep(0.02)
            except Exception as e:
                if self._running:
                    self.log("ERR", f"RX error: {e}")
                break

    def _handle_incoming_packet(self, packet, func, data_len):
        data = packet[4:4 + data_len]
        check = packet[-1]
        expected_check = self.calc_uhand_checksum(func, data_len, data)
        valid = check == expected_check

        hex_dump = packet.hex(" ").upper()
        if valid:
            status = "OK"
        else:
            status = f"CHECKSUM_MISMATCH (exp: {expected_check:02X})"
        self.log("RX", f"{hex_dump}  (func=0x{func:02X}, len={data_len}, {status})")

        if valid and func == 0x11 and data_len == self.NUM_SERVOS:
            # the angles from the hand
            reported_angles = list(data)
            self._hardware_response.set()
            self.log("SYS", f"Received hardware angles: {reported_angles}")
            self.current_angles = reported_angles
            if self.on_angles_updated:
                self.on_angles_updated(list(self.current_angles))

    def _handle_incoming_lobot(self, packet):
        hex_dump = packet.hex(" ").upper()
        self.log("RX", f"{hex_dump}  (LOBOT PACKET)")

    #==========================================================================
    # saving the calibration

    def save_calibration(self, filepath):
        data = {
            "trims": self.trims,
            "inverted": self.inverted,
            "min_limits": self.min_limits,
            "max_limits": self.max_limits
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.log("SYS", f"Saved calibration to {filepath}")

    def load_calibration(self, filepath):
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


# keeps x between lo and hi
def clamp(x, lo, hi):
    if x > hi:
        return hi
    if x < lo:
        return lo
    return x

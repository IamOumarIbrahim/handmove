"""Persistent connection defaults and discovery helpers for the uHand UNO."""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    import serial.tools.list_ports
except ImportError:
    serial = None

try:
    from bleak import BleakScanner
except ImportError:
    BleakScanner = None


SETTINGS_PATH = Path(__file__).resolve().with_name("settings.json")
DEFAULT_CONNECTION_SETTINGS: Dict[str, Any] = {
    "transport": "ble",
    "ble_name": "Hiwonder",
    "ble_address": "48:87:2D:82:90:58",
    "ble_service_uuid": "0000fff0-0000-1000-8000-00805f9b34fb",
    "ble_characteristic_uuid": "0000ffe1-0000-1000-8000-00805f9b34fb",
    "port": "",
    "baudrate": 9600,
    "protocol": "Hiwonder BLE app protocol (ASCII A-F angle $)",
    "bytesize": 8,
    "parity": "N",
    "stopbits": 1,
    "dtr": False,
    "rts": False,
    "verified": False,
}


def load_connection_settings() -> Dict[str, Any]:
    """Load saved defaults, falling back field-by-field to the BLE profile."""
    settings = dict(DEFAULT_CONNECTION_SETTINGS)
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        connection = saved.get("connection", {})
        if isinstance(connection, dict):
            for key in settings:
                if key in connection:
                    settings[key] = connection[key]
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    if settings["transport"] not in ("ble", "serial"):
        settings["transport"] = "ble"
    for key in ("ble_name", "ble_address", "ble_service_uuid", "ble_characteristic_uuid", "port"):
        if not isinstance(settings[key], str):
            settings[key] = DEFAULT_CONNECTION_SETTINGS[key]
    if not isinstance(settings["baudrate"], int) or isinstance(settings["baudrate"], bool):
        settings["baudrate"] = DEFAULT_CONNECTION_SETTINGS["baudrate"]
    return settings


def _save_settings(connection: Dict[str, Any], source: str) -> None:
    settings = {
        "connection": {**DEFAULT_CONNECTION_SETTINGS, **connection},
        "mark_color": "red",
        "source": source,
    }
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def save_verified_ble_connection(name: str, address: str, service_uuid: str, characteristic_uuid: str) -> None:
    """Save a GATT connection only after the Hiwonder BLE UART has connected."""
    _save_settings(
        {
            "transport": "ble",
            "ble_name": name or "Hiwonder",
            "ble_address": address,
            "ble_service_uuid": service_uuid,
            "ble_characteristic_uuid": characteristic_uuid,
            "verified": True,
        },
        "Saved after the Hiwonder BLE GATT UART connected; servo movement uses the documented A-F angle commands.",
    )


def save_verified_serial_connection(port: str, baudrate: int, protocol: str) -> None:
    """Save a serial connection after it receives a valid hardware response."""
    _save_settings(
        {"transport": "serial", "port": port, "baudrate": baudrate, "protocol": protocol, "verified": True},
        "Saved after receiving a valid uHand UNO angle response over serial.",
    )


def list_serial_ports() -> List[Dict[str, str]]:
    """Return serial ports currently available on this computer."""
    if serial is None:
        return []
    try:
        return [
            {"device": p.device, "description": p.description or "Serial device", "hwid": p.hwid or ""}
            for p in serial.tools.list_ports.comports()
        ]
    except Exception:
        return []


def list_ble_devices(timeout: float = 4.0) -> List[Dict[str, str]]:
    """Scan nearby BLE devices for the GUI's Bluetooth target selector."""
    if BleakScanner is None:
        return []
    try:
        devices = asyncio.run(BleakScanner.discover(timeout=timeout))
        return [
            {"name": d.name or "Unknown BLE device", "address": d.address}
            for d in devices
        ]
    except Exception:
        return []


def is_arduino_usb_port(port_name: str) -> bool:
    """Detect the Arduino Uno USB programming interface, not the hand UART."""
    normalized = port_name.casefold()
    return any(
        item["device"].casefold() == normalized and "VID:PID=2341:0043" in item["hwid"].upper()
        for item in list_serial_ports()
    )

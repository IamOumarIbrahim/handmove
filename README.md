# HANDMOVE — uHand UNO Controller

Python desktop controls for the Hiwonder uHand UNO robotic hand. The default connection is the hand's installed Bluetooth LE module, so the PC can control the same Bluetooth app interface as Wonderbot without turning the shield knobs or adding wires.

## Bluetooth control

The app scans for the saved `Hiwonder` device, connects to its BLE UART GATT service (`FFF0`) and writes characteristic (`FFE1`), then sends the manufacturer's app commands:

| Channel | Command |
| --- | --- |
| Thumb | `A<angle>$` |
| Index | `B<angle>$` |
| Middle | `C<angle>$` |
| Ring | `D<angle>$` |
| Pinky | `E<angle>$` |
| Wrist / base | `F<angle>$` |

Angles range from 0 to 180 degrees. The app sends channel changes directly and sends all six values for a grouped pose. The device enters app-control mode when it receives these commands. Bluetooth angle readback is not part of the documented app protocol, so the GUI's angle display reflects the requested positions.

The red defaults are saved in `settings.json`: Bluetooth LE, Hiwonder device identity, GATT service and characteristic UUIDs, and the app command format. The desktop app also saves a newly selected Hiwonder GATT connection after it connects successfully.

## Run

Install the runtime dependencies once:

```powershell
python -m pip install -r requirements.txt
```

Launch the GUI or terminal controller:

```powershell
python main.py --gui
python main.py --cli
```

Use serial UART only if you intentionally want the secondary wired transport:

```powershell
python main.py --gui --transport serial --port COM5
```

The serial transport uses the documented `AA 77` frame format at 9600 baud, 8N1. On that transport, the hand UART is on IO12/IO10. The Arduino Uno USB programming port is not the hand-control UART.

## App features

- Six channel sliders, spinboxes, and nudge controls.
- Preset poses and motion sequences.
- RGB LED control and the app's fixed buzzer tone.
- Optional calibration trims, limits, and simulated mode.

`ref_uhand/` contains the uHandPi Raspberry Pi reference, which uses a different board and SDK. The Hiwonder uHand UNO app-control source and command format are documented in the official uHand UNO secondary-development guide.

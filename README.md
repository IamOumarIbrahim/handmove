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

Connection defaults are saved in `settings.json`: Bluetooth LE, Hiwonder device identity, GATT service and characteristic UUIDs, and the app command format. The desktop app also saves a newly selected Hiwonder GATT connection after it connects successfully.

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

The Hiwonder uHand UNO app-control source and command format are documented in the official uHand UNO secondary-development guide.


## 3D hand view

The GUI's centre pane shows a 3D model of the uHand UNO (right hand) on its base, tower, wrist servo, Arduino and battery box. It follows every slider, preset and sequence, eases between poses at roughly LFD-01 servo speed, and briefly highlights the finger whose control you move.

- Left-drag orbits, right-drag pans, the mouse wheel zooms, and a double-click resets the camera.
- The Iso, Back, Palm, Side and Top buttons jump to preset views.
- The 2D/3D switch in the pane's title bar brings back the original schematic. The GUI also falls back to 2D on its own if `numpy`, `PyOpenGL` or `pyopengltk` is missing or OpenGL cannot start.

The model lives in `hand_model/`. `kinematics.py` holds the dimensions and the servo-to-joint mapping (180 degrees open, 0 degrees closed, wrist 90 degrees centred), `scene.py` builds the parts, and `gl_view.py` renders them. Hiwonder publishes no CAD for this hand, so the dimensions are estimates from the published specs (hand 165 x 90 mm, LFD-01 servos) and the official assembly renders. Adjust `FINGERS` and the palm constants in `kinematics.py` to match measurements of your hand.

## EEG control

`python main.py --gui --eeg` opens the EEG Bridge next to the GUI so an 8 or 16 electrode EEG headset (OpenBCI via BrainFlow, any LSL device, or replayed recordings) can drive the hand. Install `requirements-eeg.txt` first. See [docs/EEG_BRIDGE.md](docs/EEG_BRIDGE.md).

## Windows download

[Download the HANDMOVE v1.3 setup](https://github.com/IamOumarIbrahim/handmove/releases/download/v1.3/HANDMOVE-Setup-v1.3.exe).

The setup downloads the v1.3 repository archive from GitHub and extracts the source files to the selected folder. It does not install Python or the project dependencies; follow the Run instructions above to start HANDMOVE.

To rebuild the setup, install [Inno Setup](https://jrsoftware.org/isdl.php), then run `installer/build-release.ps1` from PowerShell.

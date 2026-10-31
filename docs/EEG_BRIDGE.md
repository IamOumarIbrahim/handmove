# EEG Bridge

The EEG Bridge connects an 8 or 16 electrode EEG headset to HANDMOVE. It decodes imagined finger movements and drives the uHand through the same `HandController` that the GUI uses. It lives in the `eeg/` package and `eeg_app.py`. `gui_legacy.py` is not modified.

```
EEG source ─► filters (CAR, notch, 8-13 Hz and 13-30 Hz) ─► 1 s sliding window ─► CSP + band power ─► LDA
          ─► IntentMapper (smoothing, confidence threshold, hold time, speed limit, 10 Hz max) ─► HandController.send_angles
```

## Install and run

```powershell
python -m pip install -r requirements.txt -r requirements-eeg.txt
python main.py --gui --eeg          # GUI + EEG panel (also in the new "EEG" menu)
python -m eeg --sim                 # EEG panel alone with a simulated hand
```

The main window's **E-STOP** also stops EEG control.

## Sources

| Source | Use it for |
| --- | --- |
| Synthetic EEG | Trying everything with no hardware. The simulated user follows the calibration cues. |
| Replay recording | Kaya 2018 5F `.mat` files (`data/kaya5F`) or your own `.npz` recordings. You can pick 8 or 16 electrodes to emulate your headset. |
| OpenBCI / BrainFlow | OpenBCI Cyton (8 ch, 250 Hz) and Cyton + Daisy (16 ch, 125 Hz) through the USB dongle's COM port, plus the WiFi shield, Ganglion, and BrainFlow's synthetic board. |
| Lab Streaming Layer | Any headset or app that publishes an LSL `EEG` stream: OpenBCI GUI (Networking widget, LSL), Emotiv, g.tec Unicorn, Muse (muselsl), BrainVision, Neurosity, and others. |

### Identifying an unknown headset

- An **OpenBCI** board is a bare circuit board, often in a 3D-printed "Ultracortex" helmet, with a USB dongle. Choose OpenBCI / BrainFlow and enter the dongle's COM port from Device Manager.
- For **other brands**, find the model name on the amplifier or in its software. If the vendor app has an LSL output, choose Lab Streaming Layer. Otherwise check BrainFlow's supported boards list.

## Workflow

1. Connect a source and check the signal view. Green channel names have a good amplitude (2-60 uV). Orange is noisy, and red is flat or railed.
2. Pick the classes. Start with **Rest vs Thumb** or **Thumb vs Pinky**.
3. Click **Start calibration** and follow the cues. Each cue says "Imagine: THUMB" and similar, and the default is 15 trials per class.
4. Click **Train model**. The panel shows the balanced cross-validated accuracy and chance level. Save the model so you can reuse it.
5. Click **Start driving hand**. Raise the confidence threshold or the hold time if the hand twitches.

**Train on labelled file...** trains directly from a Kaya `.mat` file or a saved `.npz`. If that is the file being replayed, it trains on the first two thirds and replays the unseen last third.

## External decoders (UDP)

Tick **Accept UDP commands** and send JSON to `127.0.0.1:5005`:

```python
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({"class": "index"}).encode(), ("127.0.0.1", 5005))
s.sendto(json.dumps({"probs": {"rest": 0.2, "thumb": 0.8}}).encode(), ("127.0.0.1", 5005))
s.sendto(json.dumps({"angles": [180, 0, 180, 180, 180, 90]}).encode(), ("127.0.0.1", 5005))
```

This lets OpenViBE, BCI2000, MATLAB, or your own model control the hand.

## What accuracy to expect

These are balanced accuracies on the Kaya 5F data (200 Hz files) with this decoder, trained on the first two thirds of a session and tested on the last third:

| Task | Subject A, 8 ch | Subject A, 16 ch | Subject C, 8 ch | Subject C, 16 ch | Chance |
| --- | --- | --- | --- | --- | --- |
| Rest vs Thumb | 56 % | 68 % | 78 % | 82 % | 50 % |
| Thumb vs Pinky | 62 % | 80 % | 66 % | 70 % | 50 % |
| Rest / Thumb / Index | 40 % | 52 % | 57 % | 60 % | 33 % |
| 5 fingers (CV) | 25 % | 46 % | 36 % | 40 % | 20 % |

Separating individual fingers with scalp EEG is hard, and results vary a lot between people. Two classes are usable, and three are marginal. Results also improve with practice and with electrodes over the motor cortex (C3, Cz, C4).

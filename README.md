# uHand UNO Robotic Hand Controller Suite (HANDMOVE)

Comprehensive Python-based control suite for the **Hiwonder uHand UNO** bionic robotic hand and **UNO 6CH Knob Shield V1.1**.

Includes:
1. **Legacy Tkinter Graphical Interface** with classic engineering styling and a real-time 2D animated robotic hand visualizer.
2. **Menu-Based Interactive Terminal** for keyboard-driven and scripted operation.
3. **Hardware Protocol Driver** implementing native `0xAA 0x77` uHand UNO frames, checksums, and optional `0x55 0x55` Lobot bus compatibility.
4. **Offline Simulation Mode** for development and test execution without hardware attached.

---

## Hardware Architecture & Pinout Reference

| Servo Channel | Anatomical Joint | Arduino Pin | Knob Potentiometer | Angle Range |
| :--- | :--- | :--- | :--- | :--- |
| **Channel 1 (S1)** | **Thumb** | D11 (PWM) | A0 | 0° – 180° |
| **Channel 2 (S2)** | **Index Finger** | D10 (PWM) | A1 | 0° – 180° |
| **Channel 3 (S3)** | **Middle Finger** | D9 (PWM) | A2 | 0° – 180° |
| **Channel 4 (S4)** | **Ring Finger** | D6 (PWM) | A3 | 0° – 180° |
| **Channel 5 (S5)** | **Pinky Finger** | D5 (PWM) | A4 | 0° – 180° |
| **Channel 6 (S6)** | **Wrist / Base** (LFD-06) | D3 (PWM) | A5 | 0° – 180° |

### Onboard Peripherals & Controls
* **Buttons:**
  * `K1` (Red Button): Triggers prompt tones / calibration mode.
  * `K2` (Yellow Button): Mode switcher.
* **RGB LED:** WS2812 addressable RGB LED (`FUNC_SET_RGB = 0x03`).
* **Buzzer:** Active buzzer driven via frequency and duration (`FUNC_SET_BUZZER = 0x02`).
* **Power Supply:** 6.0V – 8.4V DC input (battery pack or 7.4V adapter).

---

## Serial Protocol Specification (`0xAA 0x77`)

Communication operates over UART (default **COM3** at **9600 baud, 8N1**).

### Packet Framing
$$\text{Packet} = [\texttt{0xAA}, \texttt{0x77}, \text{func}, \text{len}, \text{data}_1, \dots, \text{data}_N, \text{checksum}]$$

* **Header:** `0xAA 0x77` (2 bytes)
* **Function (`func`):** 1 byte command identifier
* **Length (`len`):** 1 byte payload length ($N$)
* **Data:** $N$ payload parameter bytes
* **Checksum:** $\text{checksum} = (0\text{xFF} - (\sum(\text{func} + \text{len} + \text{data}) \ \& \ 0\text{xFF})) \ \& \ 0\text{xFF}$

### Supported Commands

| Command | Function Code | Data Length | Payload Format | Description |
| :--- | :--- | :--- | :--- | :--- |
| **`FUNC_SET_SERVO`** | `0x01` | 6 | `[S1, S2, S3, S4, S5, S6]` (angles 0–180°) | Move all 6 servos to specified degrees |
| **`FUNC_SET_BUZZER`** | `0x02` | 4 | `[Freq_Lo, Freq_Hi, Time_Lo, Time_Hi]` | Sound buzzer at Hz for ms duration |
| **`FUNC_SET_RGB`** | `0x03` | 3 | `[R, G, B]` (0–255 each) | Set addressable RGB LED color |
| **`FUNC_READ_ANGLE`**| `0x11` | 0 | *(Empty)* | Query current angles from hardware |

#### Protocol Packet Examples
* **Move all servos to 90° (Neutral):**  
  `AA 77 01 06 5A 5A 5A 5A 5A 5A DC`
* **Open all fingers (180°), wrist centered (90°):**  
  `AA 77 01 06 B4 B4 B4 B4 B4 5A A2`
* **Close hand into a fist (0°):**  
  `AA 77 01 06 00 00 00 00 00 5A 9E`
* **Buzzer at 532 Hz for 1000 ms:**  
  `AA 77 02 04 14 02 E8 03 F8`
* **Set RGB LED to Solid Red:**  
  `AA 77 03 03 FF 00 00 00`
* **Query Angles Request:**  
  `AA 77 11 00 EE`  
  *Response format:* `AA 77 11 06 <S1> <S2> <S3> <S4> <S5> <S6> <Check>`

---

## Launching the Applications

### 1. Legacy Tkinter Graphical Interface
```bash
python main.py --gui
# Or double-click:
run_gui.bat
```
* **Features:**
  * 6 Channel control cards with sliders, spinboxes, and nudge buttons (`-10`, `-5`, `0°`, `90°`, `180°`, `+5`, `+10`).
  * Live technical 2D canvas displaying finger articulation and wrist rotation in real time.
  * Preset gestures grid (Open, Fist, Thumbs Up, Peace, Point, OK, Horns, Spock, Count 1–5).
  * Sequence recorder, loop playback, and JSON export/import.
  * RGB color palette and buzzer frequency/duration player.
  * Real-time bidirectional packet traffic monitor with hex packet injection.

### 2. Menu-Based Interactive Terminal
```bash
python main.py --cli
# Or double-click:
run_cli.bat
```
* **Features:**
  * ANSI color-coded text interface with ASCII banner and live hardware telemetry.
  * Individual servo angle adjustment and live keyboard nudge tuning.
  * Preset animations: Wave, Strum/Dance, Counting 1–5, Grab & Release, Rock-Paper-Scissors.
  * Calibration offsets, axis inversion, and safety angle clamping.
  * Raw hex packet transmitter for reverse engineering.

### 3. Custom COM Port or Simulation Mode
```bash
# Specify COM port explicitly (default: COM3)
python main.py --gui --port COM3

# Run in offline simulation mode (no hardware required)
python main.py --cli --sim
```

---

## Running Automated Tests
```bash
python -m unittest discover -s HANDMOVE/tests
```
Verifies packet generation, official document checksum vectors, angle clamping, trims, and preset structures.
# handmove

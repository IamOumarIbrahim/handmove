"""
Menu-based terminal interface for uHand UNO robot hand control.
Provides maximum interactive control over COM3 with full diagnostics,
presets, calibration, sequence recording, and peripheral testing.
"""

import os
import sys
import time
from typing import List, Optional

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from controller import HandController, ProtocolType
import gestures


# ANSI color codes for terminal display
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"
    END = "\033[0m"


def clear_screen() -> None:
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


class TerminalMenuApp:
    def __init__(self, port: str = "COM3", baudrate: int = 9600, simulation: bool = False):
        self.ctrl = HandController(
            port=port,
            baudrate=baudrate,
            protocol=ProtocolType.UHAND_UNO,
            simulation_mode=simulation
        )
        self.log_history: List[str] = []
        self.ctrl.on_log = self._handle_log
        self.custom_sequence: List = []

    def _handle_log(self, direction: str, text: str) -> None:
        prefix = {
            "TX": f"{Colors.CYAN}[TX >>]{Colors.END}",
            "RX": f"{Colors.GREEN}[RX <<]{Colors.END}",
            "SYS": f"{Colors.BLUE}[SYS]{Colors.END}",
            "WARN": f"{Colors.YELLOW}[WARN]{Colors.END}",
            "ERR": f"{Colors.RED}[ERR]{Colors.END}",
        }.get(direction, f"[{direction}]")
        self.log_history.append(f"{prefix} {text}")
        if len(self.log_history) > 8:
            self.log_history.pop(0)

    def print_header(self) -> None:
        """Render ASCII robotic hand banner and current hardware status."""
        banner = rf"""{Colors.CYAN}{Colors.BOLD}
  _   _                 _   __  __ _____     ______ 
 | | | |               | | |  \/  |  _  \   |  ____|
 | |_| |__ _ _ __   __| | | \  / | | | | |  | |__   
 |  _  / _` | '_ \ / _` | | |\/| | | | | |  |  __|  
 | | | | (_| | | | | (_| | | |  | | |_| |__| |____ 
 \_| |_/\__,_|_| |_|\__,_| |_|  |_|____/|________| 
            --- MAXIMUM ROBOTIC HAND CONTROL ---{Colors.END}
"""
        print(banner)

        # Connection status block
        status_color = Colors.GREEN if self.ctrl.is_connected() else Colors.RED
        mode_str = "SIMULATION" if self.ctrl.simulation_mode else f"SERIAL ({self.ctrl.port} @ {self.ctrl.baudrate}bps)"
        conn_str = f"{status_color}{'CONNECTED' if self.ctrl.is_connected() else 'DISCONNECTED'} [{mode_str}]{Colors.END}"
        proto_str = f"{Colors.YELLOW}{self.ctrl.protocol.value}{Colors.END}"
        print(f" Status:   {conn_str} | Protocol: {proto_str}")

        # Current angles visualization
        names = ["Thumb", "Index", "Mid", "Ring", "Pinky", "Wrist"]
        angles = self.ctrl.current_angles
        angle_chips = []
        for n, a, i in zip(names, angles, range(6)):
            trim = self.ctrl.trims[i]
            inv = "!" if self.ctrl.inverted[i] else ""
            trim_str = f"({trim:+d})" if trim != 0 else ""
            angle_chips.append(f"{Colors.BOLD}{n}{Colors.END}:{inv}{a}°{trim_str}")
        print(" Servos:   " + " | ".join(angle_chips))

        # RGB and Buzzer status
        r, g, b = self.ctrl.rgb_color
        print(f" RGB LED:  (R:{r}, G:{g}, B:{b}) | Last Buzzer: {self.ctrl.last_buzzer[0]}Hz, {self.ctrl.last_buzzer[1]}ms")
        print(f"{Colors.DIM}{'=' * 72}{Colors.END}")

        # Recent log stream
        if self.log_history:
            print(f"{Colors.DIM}Recent Log Output:{Colors.END}")
            for line in self.log_history[-3:]:
                print(f"  {line}")
            print(f"{Colors.DIM}{'-' * 72}{Colors.END}")

    def run(self) -> None:
        """Main application lifecycle loop."""
        clear_screen()
        print(f"{Colors.BLUE}[INIT] Initializing uHand UNO on {self.ctrl.port}...{Colors.END}")
        success, msg = self.ctrl.connect()
        if not success:
            print(f"{Colors.YELLOW}[NOTICE] {msg}{Colors.END}")
            print("Defaulting to Simulation Mode for full offline control test.")
            self.ctrl.simulation_mode = True
            self.ctrl.connect()

        time.sleep(0.5)

        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}MAIN MENU:{Colors.END}")
            print(f"  {Colors.GREEN}[1]{Colors.END} Preset Gestures (Fist, Peace, Gun, Thumbs Up, etc.)")
            print(f"  {Colors.GREEN}[2]{Colors.END} Manual Servo Control (Fine Adjust Individual Angles)")
            print(f"  {Colors.GREEN}[3]{Colors.END} Interactive Live Nudge Mode (Live Keyboard Tuning)")
            print(f"  {Colors.GREEN}[4]{Colors.END} Built-in Animations (Wave, Count 1-5, Dance, Grab)")
            print(f"  {Colors.GREEN}[5]{Colors.END} Sequence Recorder & Keyframe Editor")
            print(f"  {Colors.GREEN}[6]{Colors.END} Peripheral Controls (Buzzer & RGB LED)")
            print(f"  {Colors.GREEN}[7]{Colors.END} Calibration & Trims (Hardware Inversion & Limits)")
            print(f"  {Colors.GREEN}[8]{Colors.END} Raw Hex Packet Tool (Reverse Engineering & Sniffing)")
            print(f"  {Colors.GREEN}[9]{Colors.END} Serial Connection Settings (COM Port / Baud / Simulation)")
            print(f"  {Colors.RED}[0]{Colors.END} Exit Program")
            print()

            choice = input(f"{Colors.BOLD}Select an option [0-9]: {Colors.END}").strip()

            if choice == "1":
                self.menu_presets()
            elif choice == "2":
                self.menu_manual_servos()
            elif choice == "3":
                self.menu_live_nudge()
            elif choice == "4":
                self.menu_animations()
            elif choice == "5":
                self.menu_sequencer()
            elif choice == "6":
                self.menu_peripherals()
            elif choice == "7":
                self.menu_calibration()
            elif choice == "8":
                self.menu_raw_packet()
            elif choice == "9":
                self.menu_connection()
            elif choice in ("0", "q", "exit"):
                print(f"{Colors.CYAN}Shutting down controller and closing port...{Colors.END}")
                self.ctrl.disconnect()
                print("Goodbye!")
                break
            else:
                input(f"{Colors.RED}Invalid option. Press Enter to continue...{Colors.END}")

    # =========================================================================
    # Submenus
    # =========================================================================

    def menu_presets(self) -> None:
        """Display and execute preset poses."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}PRESET GESTURES & POSES:{Colors.END}")
            preset_items = list(gestures.PRESET_POSES.items())
            for idx, (name, pose) in enumerate(preset_items, 1):
                print(f"  {Colors.GREEN}[{idx:2d}]{Colors.END} {name:<22} -> {pose}")
            print(f"  {Colors.YELLOW}[ S]{Colors.END} Toggle Smooth Transition Mode")
            print(f"  {Colors.RED}[ 0]{Colors.END} Back to Main Menu")
            print()

            cmd = input(f"Select preset [1-{len(preset_items)} or 0]: ").strip().lower()
            if cmd in ("0", "b", ""):
                break

            if cmd.isdigit() and 1 <= int(cmd) <= len(preset_items):
                name, pose = preset_items[int(cmd) - 1]
                print(f"Applying pose '{name}'...")
                self.ctrl.send_angles(list(pose))
                time.sleep(0.3)
            else:
                input("Invalid option. Press Enter...")

    def menu_manual_servos(self) -> None:
        """Fine control for each individual servo."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}MANUAL SERVO ANGLE CONTROL:{Colors.END}")
            for idx, name in enumerate(HandController.SERVO_NAMES):
                print(f"  [{idx + 1}] {name:<14} : Current = {self.ctrl.current_angles[idx]}° (Limits: {self.ctrl.min_limits[idx]}-{self.ctrl.max_limits[idx]}°)")
            print(f"  [A] Set ALL 6 servos simultaneously (e.g. '90,90,90,90,90,90')")
            print(f"  [O] Open all fingers (180°)")
            print(f"  [C] Close all fingers (0°)")
            print(f"  [N] Neutral position (90°)")
            print(f"  [0] Back to Main Menu")
            print()

            choice = input("Select channel [1-6, A, O, C, N, 0]: ").strip().upper()
            if choice == "0":
                break
            elif choice in ("O", "ALL OPEN"):
                self.ctrl.send_angles([180, 180, 180, 180, 180, 90])
            elif choice in ("C", "ALL CLOSE"):
                self.ctrl.send_angles([0, 0, 0, 0, 0, 90])
            elif choice in ("N", "NEUTRAL"):
                self.ctrl.send_angles([90, 90, 90, 90, 90, 90])
            elif choice == "A":
                raw = input("Enter 6 comma-separated angles (0-180): ").strip()
                try:
                    vals = [int(x.strip()) for x in raw.split(",")]
                    if len(vals) == 6:
                        self.ctrl.send_angles(vals)
                    else:
                        print(f"{Colors.RED}Must specify exactly 6 angles!{Colors.END}")
                        time.sleep(1)
                except ValueError:
                    print(f"{Colors.RED}Invalid integer values!{Colors.END}")
                    time.sleep(1)
            elif choice.isdigit() and 1 <= int(choice) <= 6:
                ch_idx = int(choice) - 1
                name = HandController.SERVO_NAMES[ch_idx]
                val_str = input(f"Enter new angle for {name} (0-180) or +/- delta (e.g. '+10', '-5'): ").strip()
                try:
                    if val_str.startswith("+") or val_str.startswith("-"):
                        delta = int(val_str)
                        new_ang = self.ctrl.current_angles[ch_idx] + delta
                    else:
                        new_ang = int(val_str)
                    new_ang = max(0, min(180, new_ang))
                    self.ctrl.set_servo_angle(ch_idx, new_ang)
                except ValueError:
                    print(f"{Colors.RED}Invalid input!{Colors.END}")
                    time.sleep(1)

    def menu_live_nudge(self) -> None:
        """Continuous live single-key tuning."""
        clear_screen()
        print(f"{Colors.BOLD}{Colors.CYAN}LIVE KEYBOARD NUDGE MODE:{Colors.END}")
        print("Keys: [1-6] select servo, [+] or [=] add 5°, [-] subtract 5°, [0] reset to 90°")
        print("Type 'q' to return to menu.")
        selected = 0

        while True:
            cur_name = HandController.SERVO_NAMES[selected]
            cur_ang = self.ctrl.current_angles[selected]
            print(f"\rActive: [{selected + 1}] {cur_name:<12} = {cur_ang:3d}°  | Cmd: ", end="", flush=True)

            cmd = input().strip()
            if cmd.lower() in ("q", "quit", "exit"):
                break
            elif cmd in ("1", "2", "3", "4", "5", "6"):
                selected = int(cmd) - 1
            elif cmd in ("+", "="):
                self.ctrl.set_servo_angle(selected, cur_ang + 5)
            elif cmd in ("-", "_"):
                self.ctrl.set_servo_angle(selected, cur_ang - 5)
            elif cmd == "++":
                self.ctrl.set_servo_angle(selected, cur_ang + 15)
            elif cmd == "--":
                self.ctrl.set_servo_angle(selected, cur_ang - 15)
            elif cmd == "0":
                self.ctrl.set_servo_angle(selected, 90)

    def menu_animations(self) -> None:
        """Play built-in animation sequences."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}BUILT-IN ANIMATION SEQUENCES:{Colors.END}")
            seq_items = list(gestures.PRESET_SEQUENCES.items())
            for idx, (name, frames) in enumerate(seq_items, 1):
                total_dur = sum(d for _, d in frames)
                print(f"  {Colors.GREEN}[{idx}]{Colors.END} {name:<22} ({len(frames)} frames, ~{total_dur}ms)")
            print(f"  {Colors.RED}[0]{Colors.END} Back to Main Menu")
            print()

            choice = input(f"Select animation to play [1-{len(seq_items)}, 0]: ").strip()
            if choice == "0":
                break
            if choice.isdigit() and 1 <= int(choice) <= len(seq_items):
                name, frames = seq_items[int(choice) - 1]
                loop_input = input("Loop continuously? [y/N]: ").strip().lower()
                loop = (loop_input == "y")
                speed_str = input("Speed factor (e.g. 1.0, 1.5, 0.8) [Default: 1.0]: ").strip()
                try:
                    speed = float(speed_str) if speed_str else 1.0
                except ValueError:
                    speed = 1.0

                print(f"Playing sequence '{name}'... Press Ctrl+C or Enter to stop.")
                self.ctrl.play_sequence(frames, loop=loop, speed_factor=speed)
                try:
                    while self.ctrl.is_playing_sequence:
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    print("\nStopping sequence...")
                    self.ctrl.stop_sequence()

    def menu_sequencer(self) -> None:
        """Custom keyframe sequence builder."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}SEQUENCE RECORDER & EDITOR:{Colors.END}")
            print(f"Current Buffer: {len(self.custom_sequence)} keyframe(s)")
            for idx, (pose, dur) in enumerate(self.custom_sequence, 1):
                print(f"  Frame #{idx:2d}: Angles={pose} | Duration={dur}ms")
            print()
            print("  [C] Capture CURRENT pose as new keyframe")
            print("  [M] Manually type keyframe angles")
            print("  [P] Play recorded sequence")
            print("  [D] Delete last keyframe")
            print("  [X] Clear all keyframes")
            print("  [S] Save to JSON file")
            print("  [L] Load from JSON file")
            print("  [0] Back to Main Menu")
            print()

            action = input("Select action: ").strip().upper()
            if action == "0":
                break
            elif action == "C":
                dur_str = input("Keyframe duration in ms [Default 400]: ").strip()
                dur = int(dur_str) if dur_str.isdigit() else 400
                self.custom_sequence.append((tuple(self.ctrl.current_angles), dur))
                print(f"{Colors.GREEN}Captured frame!{Colors.END}")
                time.sleep(0.5)
            elif action == "P":
                if not self.custom_sequence:
                    input("Buffer is empty! Press Enter...")
                    continue
                print("Playing custom sequence...")
                self.ctrl.play_sequence(self.custom_sequence, loop=False)
                while self.ctrl.is_playing_sequence:
                    time.sleep(0.1)
            elif action == "D":
                if self.custom_sequence:
                    self.custom_sequence.pop()
            elif action == "X":
                self.custom_sequence.clear()
            elif action == "S":
                fname = input("Filename to save (e.g. sequence.json): ").strip()
                if not fname:
                    fname = "sequence.json"
                try:
                    import json
                    with open(fname, "w", encoding="utf-8") as f:
                        json.dump(self.custom_sequence, f, indent=2)
                    input(f"{Colors.GREEN}Saved successfully to {fname}. Press Enter...{Colors.END}")
                except Exception as e:
                    input(f"{Colors.RED}Save failed: {e}. Press Enter...{Colors.END}")
            elif action == "L":
                fname = input("Filename to load: ").strip()
                try:
                    import json
                    with open(fname, "r", encoding="utf-8") as f:
                        self.custom_sequence = [
                            (tuple(item[0]), item[1]) for item in json.load(f)
                        ]
                    input(f"{Colors.GREEN}Loaded {len(self.custom_sequence)} frames! Press Enter...{Colors.END}")
                except Exception as e:
                    input(f"{Colors.RED}Load failed: {e}. Press Enter...{Colors.END}")

    def menu_peripherals(self) -> None:
        """Actuate Buzzer and RGB LED on shield."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}PERIPHERAL ACTUATORS (BUZZER & RGB LED):{Colors.END}")
            print("  [1] Short Prompt Beep (1000 Hz, 150 ms)")
            print("  [2] High Pitch Alert (2500 Hz, 300 ms)")
            print("  [3] Custom Buzzer Tone (Frequency & Duration)")
            print("  [4] RGB: Red")
            print("  [5] RGB: Green")
            print("  [6] RGB: Blue")
            print("  [7] RGB: Yellow")
            print("  [8] RGB: White")
            print("  [9] RGB: OFF")
            print("  [R] Rainbow Cycle LED Effect")
            print("  [Q] Query Hardware Angles (FUNC_READ_ANGLE)")
            print("  [0] Back to Main Menu")
            print()

            ch = input("Select peripheral test: ").strip().upper()
            if ch == "0":
                break
            elif ch == "1":
                self.ctrl.set_buzzer(1000, 150)
            elif ch == "2":
                self.ctrl.set_buzzer(2500, 300)
            elif ch == "3":
                f_str = input("Frequency in Hz (100-5000): ").strip()
                d_str = input("Duration in ms (50-2000): ").strip()
                try:
                    self.ctrl.set_buzzer(int(f_str), int(d_str))
                except ValueError:
                    print("Invalid numbers")
                    time.sleep(1)
            elif ch == "4":
                self.ctrl.set_rgb(255, 0, 0)
            elif ch == "5":
                self.ctrl.set_rgb(0, 255, 0)
            elif ch == "6":
                self.ctrl.set_rgb(0, 0, 255)
            elif ch == "7":
                self.ctrl.set_rgb(255, 255, 0)
            elif ch == "8":
                self.ctrl.set_rgb(255, 255, 255)
            elif ch == "9":
                self.ctrl.set_rgb(0, 0, 0)
            elif ch == "R":
                print("Running rainbow cycle...")
                colors = [
                    (255, 0, 0), (255, 127, 0), (255, 255, 0),
                    (0, 255, 0), (0, 0, 255), (75, 0, 130), (148, 0, 211)
                ]
                for c in colors:
                    self.ctrl.set_rgb(*c)
                    time.sleep(0.2)
                self.ctrl.set_rgb(0, 0, 0)
            elif ch == "Q":
                self.ctrl.query_angles()
                time.sleep(0.3)

    def menu_calibration(self) -> None:
        """Configure trims, limits, and axis inversions."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}HARDWARE CALIBRATION & LIMITS:{Colors.END}")
            for idx, name in enumerate(HandController.SERVO_NAMES):
                inv = "INVERTED" if self.ctrl.inverted[idx] else "NORMAL"
                trim = self.ctrl.trims[idx]
                lim = f"{self.ctrl.min_limits[idx]}-{self.ctrl.max_limits[idx]}°"
                print(f"  [{idx + 1}] {name:<14} | Trim: {trim:+3d}° | Direction: {inv:<8} | Limits: {lim}")
            print()
            print("  [T] Adjust Trim Offset for a Servo")
            print("  [I] Toggle Invert Direction for a Servo")
            print("  [L] Set Min/Max Clamping Limits for a Servo")
            print("  [S] Save Calibration to disk (calibration.json)")
            print("  [R] Reset Calibration to Factory Defaults")
            print("  [0] Back to Main Menu")
            print()

            action = input("Select action: ").strip().upper()
            if action == "0":
                break
            elif action == "T":
                ch = input("Select servo [1-6]: ").strip()
                if ch.isdigit() and 1 <= int(ch) <= 6:
                    val = input("Enter trim offset in degrees (-45 to +45): ").strip()
                    try:
                        self.ctrl.trims[int(ch) - 1] = int(val)
                    except ValueError:
                        pass
            elif action == "I":
                ch = input("Select servo to toggle invert [1-6]: ").strip()
                if ch.isdigit() and 1 <= int(ch) <= 6:
                    idx = int(ch) - 1
                    self.ctrl.inverted[idx] = not self.ctrl.inverted[idx]
            elif action == "S":
                self.ctrl.save_calibration("calibration.json")
                input("Saved calibration.json. Press Enter...")
            elif action == "R":
                self.ctrl.trims = [0, 0, 0, 0, 0, 0]
                self.ctrl.inverted = [False, False, False, False, False, False]
                self.ctrl.min_limits = [0, 0, 0, 0, 0, 0]
                self.ctrl.max_limits = [180, 180, 180, 180, 180, 180]
                input("Reset to factory defaults. Press Enter...")

    def menu_raw_packet(self) -> None:
        """Hex packet injector for reverse engineering and testing."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}RAW HEX PACKET INJECTOR:{Colors.END}")
            print("Common examples:")
            print("  AA 77 01 06 5A 5A 5A 5A 5A 5A DC  -> Move all servos to 90°")
            print("  AA 77 01 06 B4 B4 B4 B4 B4 5A A2  -> Open fingers (180°), Wrist 90°")
            print("  AA 77 02 04 14 02 E8 03 F8        -> Buzzer 532Hz, 1000ms")
            print("  AA 77 03 03 FF 00 00 00           -> RGB Red (255, 0, 0)")
            print("  AA 77 11 00 EE                    -> Query servo angles")
            print("  [0] Back to Main Menu")
            print()

            raw = input("Enter hex string to transmit: ").strip()
            if raw == "0":
                break
            if raw:
                self.ctrl.send_raw_hex(raw)
                time.sleep(0.3)

    def menu_connection(self) -> None:
        """Port and communication protocol configuration."""
        while True:
            clear_screen()
            self.print_header()
            print(f"{Colors.BOLD}COMMUNICATION SETTINGS:{Colors.END}")
            print(f"  Current Port:       {self.ctrl.port}")
            print(f"  Current Baud Rate:  {self.ctrl.baudrate}")
            print(f"  Simulation Mode:    {self.ctrl.simulation_mode}")
            print(f"  Protocol:           {self.ctrl.protocol.value}")
            print()
            print("  [1] Change COM Port (Default: COM3)")
            print("  [2] Change Baud Rate (9600, 115200)")
            print("  [3] Toggle Simulation Mode (Virtual Hand)")
            print("  [4] Toggle Protocol (uHand UNO vs Lobot Bus)")
            print("  [5] Reconnect / Reset Port")
            print("  [6] Disconnect Port")
            print("  [0] Back to Main Menu")
            print()

            opt = input("Select setting [1-6, 0]: ").strip()
            if opt == "0":
                break
            elif opt == "1":
                new_port = input(f"Enter port name [Default: COM3]: ").strip().upper()
                if new_port:
                    self.ctrl.port = new_port
            elif opt == "2":
                new_baud = input("Enter baud rate (9600 / 115200): ").strip()
                if new_baud.isdigit():
                    self.ctrl.baudrate = int(new_baud)
            elif opt == "3":
                self.ctrl.simulation_mode = not self.ctrl.simulation_mode
                self.ctrl.connect()
            elif opt == "4":
                if self.ctrl.protocol == ProtocolType.UHAND_UNO:
                    self.ctrl.protocol = ProtocolType.LOBOT_BUS
                else:
                    self.ctrl.protocol = ProtocolType.UHAND_UNO
            elif opt == "5":
                self.ctrl.disconnect()
                time.sleep(0.5)
                self.ctrl.connect()
            elif opt == "6":
                self.ctrl.disconnect()


if __name__ == "__main__":
    app = TerminalMenuApp(port="COM3", baudrate=9600)
    app.run()

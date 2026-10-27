"""
Legacy Tkinter Graphical Interface for uHand UNO serial control.
Provides maximum interactive control, real-time 2D animated hand visualization,
fine servo calibration, preset gestures, sequence recording, peripherals,
and raw bidirectional packet sniffing/injection.
"""

import json
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from typing import Dict, List, Optional, Tuple, Union

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from controller import HandController, ProtocolType
from connection_settings import list_ble_devices, list_serial_ports, load_connection_settings
import gestures


class LegacyHandGUI:
    """
    Classic/Legacy Engineering GUI for the uHand UNO robotic hand.
    Styled with classic workstation aesthetics (sunken/raised bevels, tactile controls).
    """

    BG_COLOR = "#ECE9D8"       # Classic Windows / System gray
    PANEL_BG = "#E0DFD3"
    ACCENT_COLOR = "#0A246A"   # Classic Win32 navy title
    CANVAS_BG = "#1A2228"      # Technical dark slate blueprint for hand rendering
    BONE_COLOR = "#61AFEF"
    JOINT_COLOR = "#E5C07B"
    PALM_COLOR = "#2C3E50"
    DEFAULT_MARK_COLOR = "#C00000"

    def __init__(self, root: tk.Tk, default_port: str = "", default_baud: int = 9600):
        self.root = root
        self.root.title("uHand UNO Controller - Maximum Control Console")
        self.root.geometry("1280x850")
        self.root.minsize(1100, 750)
        self.root.configure(bg=self.BG_COLOR)
        self.root.protocol("WM_DELETE_WINDOW", self._close_application)

        # Core controller
        self.ctrl = HandController(
            port=default_port,
            baudrate=default_baud,
            protocol=ProtocolType.UHAND_UNO,
            simulation_mode=False
        )

        # Thread-safe UI queue
        self.ctrl.on_log = self._on_controller_log
        self.ctrl.on_angles_updated = self._on_controller_angles_updated
        self.ctrl.on_connection_changed = self._on_controller_connection_changed
        self.ctrl.on_sequence_step = self._on_sequence_step

        # Internal state
        self.channel_vars: List[tk.IntVar] = []
        self.channel_spin_vars: List[tk.IntVar] = []
        self.invert_vars: List[tk.BooleanVar] = []
        self.trim_vars: List[tk.IntVar] = []
        self.auto_scroll_var = tk.BooleanVar(value=True)
        self.smooth_move_var = tk.BooleanVar(value=False)
        self.smooth_dur_var = tk.IntVar(value=300)
        self.sequence_frames: List[Tuple[Tuple[int, int, int, int, int, int], int]] = []
        self.selected_finger_drag: Optional[int] = None

        # Build UI
        self._build_styles()
        self._build_menu()
        self._build_top_connection_bar()
        self._build_main_panes()
        self._build_bottom_packet_console()
        self._build_status_bar()

        # Initial canvas render
        self.root.after(100, self._render_hand_canvas)

        # Attempt auto-connect to a previously verified adapter port after UI shows
        self.root.after(300, self._auto_connect)

    # =========================================================================
    # UI Styling & Menu Bar
    # =========================================================================

    def _build_styles(self) -> None:
        """Apply classic/legacy Tk styling."""
        style = ttk.Style()
        try:
            style.theme_use("winnative" if os.name == "nt" else "classic")
        except Exception:
            pass
        style.configure("MarkedDefault.TCombobox", foreground=self.DEFAULT_MARK_COLOR)

    def _build_menu(self) -> None:
        """Top menu bar."""
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Calibration...", command=self._save_calibration)
        file_menu.add_command(label="Load Calibration...", command=self._load_calibration)
        file_menu.add_separator()
        file_menu.add_command(label="Save Sequence...", command=self._save_sequence)
        file_menu.add_command(label="Load Sequence...", command=self._load_sequence)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close_application)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="All Servos Neutral (90°)", command=lambda: self._apply_pose([90]*6, force=True))
        tools_menu.add_command(label="All Servos Open (180°)", command=lambda: self._apply_pose([180, 180, 180, 180, 180, 90]))
        tools_menu.add_command(label="All Servos Closed (0°)", command=lambda: self._apply_pose([0, 0, 0, 0, 0, 90]))
        tools_menu.add_separator()
        tools_menu.add_command(label="Query Hardware Angles", command=self.ctrl.query_angles)
        menubar.add_cascade(label="Quick Actions", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Hardware & Wiring Pinout", command=self._show_pinout_help)
        help_menu.add_command(label="Serial Protocol Specification", command=self._show_protocol_help)
        help_menu.add_separator()
        help_menu.add_command(label="About uHand UNO Controller", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    # =========================================================================
    # Top Connection Toolbar
    # =========================================================================

    def _build_top_connection_bar(self) -> None:
        """Top bar for serial communication, port, baud, and connect controls."""
        bar = tk.Frame(self.root, bg=self.BG_COLOR, bd=2, relief=tk.GROOVE)
        bar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=3)

        # Connection Lamp
        self.conn_lamp = tk.Canvas(bar, width=18, height=18, bg=self.BG_COLOR, highlightthickness=0)
        self.conn_lamp.pack(side=tk.LEFT, padx=6)
        self._draw_lamp("red")

        # The Hiwonder Bluetooth UART is the default PC control path.
        tk.Label(bar, text="Transport (RED default):", font=("Tahoma", 9, "bold"), fg=self.DEFAULT_MARK_COLOR, bg=self.BG_COLOR).pack(side=tk.LEFT, padx=(4, 2))
        self.transport_var = tk.StringVar(value="Bluetooth LE" if self.ctrl.transport == "ble" else "Serial UART")
        self.transport_combo = ttk.Combobox(bar, textvariable=self.transport_var, width=14, state="readonly", values=["Bluetooth LE", "Serial UART"], style="MarkedDefault.TCombobox")
        self.transport_combo.pack(side=tk.LEFT, padx=2)
        self.transport_combo.bind("<<ComboboxSelected>>", self._on_transport_changed)

        self.ble_label = tk.Label(bar, text="BLE device:", font=("Tahoma", 9, "bold"), fg=self.DEFAULT_MARK_COLOR, bg=self.BG_COLOR)
        self.ble_label.pack(side=tk.LEFT, padx=(6, 2))
        self.ble_target_var = tk.StringVar(value=self._format_ble_target(self.ctrl.ble_name, self.ctrl.ble_address))
        self.ble_target_combo = ttk.Combobox(bar, textvariable=self.ble_target_var, width=22, values=[self.ble_target_var.get()], style="MarkedDefault.TCombobox")
        self.ble_target_combo.pack(side=tk.LEFT, padx=2)
        self.btn_refresh_ble = tk.Button(bar, text="Find", font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._refresh_ble_devices)
        self.btn_refresh_ble.pack(side=tk.LEFT, padx=2)

        # Serial UART remains available as a secondary transport.
        self.port_label = tk.Label(bar, text="COM port:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        self.port_label.pack(side=tk.LEFT, padx=(8, 2))
        self.port_var = tk.StringVar(value=self.ctrl.port)
        port_values = [port["device"] for port in list_serial_ports()]
        self.port_combo = ttk.Combobox(
            bar, textvariable=self.port_var, width=10,
            values=port_values, style="MarkedDefault.TCombobox"
        )
        self.port_combo.pack(side=tk.LEFT, padx=2)
        self.btn_refresh_serial = tk.Button(
            bar, text="Refresh", font=("Tahoma", 8), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._refresh_serial_ports
        )
        self.btn_refresh_serial.pack(side=tk.LEFT, padx=2)

        # Baud selection
        self.baud_label = tk.Label(bar, text="Baud:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        self.baud_label.pack(side=tk.LEFT, padx=(8, 2))
        self.baud_var = tk.StringVar(value=str(self.ctrl.baudrate))
        self.baud_combo = ttk.Combobox(bar, textvariable=self.baud_var, width=8, values=["9600", "115200", "57600", "19200", "38400"], style="MarkedDefault.TCombobox")
        self.baud_combo.pack(side=tk.LEFT, padx=2)

        # Protocol selection
        self.protocol_label = tk.Label(bar, text="Protocol:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        self.protocol_label.pack(side=tk.LEFT, padx=(8, 2))
        self.proto_var = tk.StringVar(value=self.ctrl.protocol.value)
        self.proto_combo = ttk.Combobox(bar, textvariable=self.proto_var, width=28, values=[p.value for p in ProtocolType], style="MarkedDefault.TCombobox")
        self.proto_combo.pack(side=tk.LEFT, padx=2)
        self.proto_combo.bind("<<ComboboxSelected>>", self._on_protocol_changed)
        self._on_transport_changed()

        # Simulation mode checkbox
        self.sim_var = tk.BooleanVar(value=self.ctrl.simulation_mode)
        self.sim_check = tk.Checkbutton(
            bar, text="Simulation Mode", variable=self.sim_var,
            bg=self.BG_COLOR, font=("Tahoma", 9), command=self._on_sim_toggled
        )
        self.sim_check.pack(side=tk.LEFT, padx=8)

        # Connect / Disconnect Buttons
        self.btn_connect = tk.Button(
            bar, text="Connect", font=("Tahoma", 9, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=10, command=self._on_connect_clicked
        )
        self.btn_connect.pack(side=tk.LEFT, padx=4)

        self.btn_disconnect = tk.Button(
            bar, text="Disconnect", font=("Tahoma", 9), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=8, state=tk.DISABLED, command=self._on_disconnect_clicked
        )
        self.btn_disconnect.pack(side=tk.LEFT, padx=2)

        # Query Angles Button
        self.btn_query = tk.Button(
            bar, text="Read Angles", font=("Tahoma", 9), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=6, command=self.ctrl.query_angles
        )
        self.btn_query.pack(side=tk.LEFT, padx=6)

        # Emergency Stop / Neutral
        self.btn_estop = tk.Button(
            bar, text="E-STOP / NEUTRAL", font=("Tahoma", 9, "bold"), fg="red", bg="#FFE4E1",
            relief=tk.RAISED, bd=2, padx=8, command=self._on_estop_clicked
        )
        self.btn_estop.pack(side=tk.RIGHT, padx=6)
        self._on_transport_changed()

        tk.Label(
            self.root,
            text="RED = Hiwonder BLE UART defaults. Servo commands use the same A-F angle format as Wonderbot; no hand-side wiring is needed.",
            font=("Tahoma", 8, "bold"), fg=self.DEFAULT_MARK_COLOR, bg=self.BG_COLOR, anchor=tk.W
        ).pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 2))

    def _refresh_serial_ports(self) -> None:
        """Refresh the port selector from ports currently present on this computer."""
        ports = list_serial_ports()
        values = [port["device"] for port in ports]
        self.port_combo.configure(values=values)
        self.ctrl.log("SYS", "Available serial ports: " + (", ".join(values) if values else "none found"))

    @staticmethod
    def _format_ble_target(name: str, address: str) -> str:
        return f"{name or 'Hiwonder'} — {address}" if address else (name or "Hiwonder")

    @staticmethod
    def _parse_ble_target(value: str) -> Tuple[str, str]:
        if " — " in value:
            name, address = value.rsplit(" — ", 1)
            return name.strip(), address.strip()
        return value.strip() or "Hiwonder", ""

    def _refresh_ble_devices(self) -> None:
        self.status_bar.config(text="Searching for nearby Bluetooth LE devices…")
        devices = list_ble_devices(timeout=4.0)
        values = [self._format_ble_target(item["name"], item["address"]) for item in devices]
        self.ble_target_combo.configure(values=values or [self.ble_target_var.get()])
        self.ctrl.log("SYS", "Nearby BLE devices: " + (", ".join(values) if values else "none found"))
        self.status_bar.config(text=f"Bluetooth scan complete: {len(values)} device(s) found")

    def _draw_lamp(self, color: str) -> None:
        """Update connection indicator circle."""
        self.conn_lamp.delete("all")
        self.conn_lamp.create_oval(2, 2, 16, 16, fill=color, outline="#333333", width=1.5)

    # =========================================================================
    # Main Panes (Left: Servos, Center: Canvas, Right: Tabs)
    # =========================================================================

    def _build_main_panes(self) -> None:
        """Build the tripartite main workspace."""
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=self.BG_COLOR, bd=2, relief=tk.GROOVE, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # 1. Left Frame: Servo Control Sliders
        left_frame = tk.Frame(paned, bg=self.BG_COLOR, bd=2, relief=tk.SUNKEN)
        paned.add(left_frame, minsize=380, width=420)
        self._build_servo_controls(left_frame)

        # 2. Center Frame: 2D Visual Robotic Hand Canvas
        center_frame = tk.Frame(paned, bg=self.BG_COLOR, bd=2, relief=tk.SUNKEN)
        paned.add(center_frame, minsize=320, width=380)
        self._build_hand_canvas(center_frame)

        # 3. Right Frame: Tabbed Notebook (Presets, Sequencer, Peripherals, Calibration)
        right_frame = tk.Frame(paned, bg=self.BG_COLOR, bd=2, relief=tk.SUNKEN)
        paned.add(right_frame, minsize=380, width=460)
        self._build_notebook_tabs(right_frame)

    # =========================================================================
    # Left Pane: 6 Servo Channels (Maximum Fine Control)
    # =========================================================================

    def _build_servo_controls(self, parent: tk.Frame) -> None:
        """Build the 6 servo channel sliders, spinboxes, and nudge buttons."""
        title_bar = tk.Frame(parent, bg=self.ACCENT_COLOR, bd=1, relief=tk.RAISED)
        title_bar.pack(fill=tk.X, padx=2, pady=2)
        tk.Label(
            title_bar, text="SERVO CHANNELS (0 - 180°)", fg="white", bg=self.ACCENT_COLOR,
            font=("Tahoma", 10, "bold"), anchor="w", padx=6
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        scroll_canvas = tk.Canvas(parent, bg=self.BG_COLOR, highlightthickness=0)
        scrollbar = tk.Scrollbar(parent, orient=tk.VERTICAL, command=scroll_canvas.yview)
        scroll_content = tk.Frame(scroll_canvas, bg=self.BG_COLOR)

        scroll_content.bind(
            "<Configure>", lambda e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
        )
        scroll_canvas.create_window((0, 0), window=scroll_content, anchor="nw")
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 6 Servo cards
        for idx, name in enumerate(HandController.SERVO_NAMES):
            card = tk.LabelFrame(
                scroll_content, text=f"Channel {idx + 1}: {name}",
                font=("Tahoma", 9, "bold"), bg=self.BG_COLOR, bd=2, relief=tk.GROOVE
            )
            card.pack(fill=tk.X, padx=4, pady=3)

            # Row 1: Slider and Spinbox
            r1 = tk.Frame(card, bg=self.BG_COLOR)
            r1.pack(fill=tk.X, padx=4, pady=2)

            var = tk.IntVar(value=90)
            self.channel_vars.append(var)

            slider = tk.Scale(
                r1, from_=0, to=180, orient=tk.HORIZONTAL, variable=var,
                bg=self.BG_COLOR, highlightthickness=0, length=200,
                command=lambda val, ch=idx: self._on_slider_moved(ch, val)
            )
            slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

            spin = tk.Spinbox(
                r1, from_=0, to=180, width=4, font=("Tahoma", 10),
                textvariable=var,
                command=lambda ch=idx: self._on_spin_changed(ch)
            )
            spin.pack(side=tk.RIGHT, padx=2)
            spin.bind("<Return>", lambda e, ch=idx: self._on_spin_changed(ch))

            # Row 2: Nudge buttons
            r2 = tk.Frame(card, bg=self.BG_COLOR)
            r2.pack(fill=tk.X, padx=4, pady=2)

            nudges = [
                ("-10", -10), ("-5", -5), ("0°", "0"), ("90°", "90"), ("180°", "180"), ("+5", 5), ("+10", 10)
            ]
            for label, val in nudges:
                btn = tk.Button(
                    r2, text=label, font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED, bd=1, padx=2,
                    command=lambda ch=idx, v=val: self._on_nudge_clicked(ch, v)
                )
                btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

            # Row 3: Trim & Invert
            r3 = tk.Frame(card, bg=self.BG_COLOR)
            r3.pack(fill=tk.X, padx=4, pady=(1, 3))

            inv_var = tk.BooleanVar(value=False)
            self.invert_vars.append(inv_var)
            chk_inv = tk.Checkbutton(
                r3, text="Invert", variable=inv_var, bg=self.BG_COLOR, font=("Tahoma", 8),
                command=lambda ch=idx: self._on_invert_toggled(ch)
            )
            chk_inv.pack(side=tk.LEFT)

            tk.Label(r3, text="Trim:", bg=self.BG_COLOR, font=("Tahoma", 8)).pack(side=tk.LEFT, padx=(8, 2))
            trim_var = tk.IntVar(value=0)
            self.trim_vars.append(trim_var)
            spin_trim = tk.Spinbox(
                r3, from_=-45, to=45, width=4, font=("Tahoma", 8),
                textvariable=trim_var,
                command=lambda ch=idx: self._on_trim_changed(ch)
            )
            spin_trim.pack(side=tk.LEFT, padx=2)

        # Master Buttons
        master_box = tk.LabelFrame(scroll_content, text="Master Actions", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        master_box.pack(fill=tk.X, padx=4, pady=6)

        m_row = tk.Frame(master_box, bg=self.BG_COLOR)
        m_row.pack(fill=tk.X, padx=4, pady=4)

        tk.Button(
            m_row, text="All Open (180°)", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=lambda: self._apply_pose([180, 180, 180, 180, 180, 90])
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        tk.Button(
            m_row, text="Neutral (90°)", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=lambda: self._apply_pose([90]*6, force=True)
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        tk.Button(
            m_row, text="All Closed (0°)", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=lambda: self._apply_pose([0, 0, 0, 0, 0, 90])
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # Smooth Motion Options
        sm_row = tk.Frame(master_box, bg=self.BG_COLOR)
        sm_row.pack(fill=tk.X, padx=4, pady=(2, 4))
        tk.Checkbutton(
            sm_row, text="Smooth Interpolation", variable=self.smooth_move_var,
            bg=self.BG_COLOR, font=("Tahoma", 8)
        ).pack(side=tk.LEFT)
        tk.Label(sm_row, text="Duration (ms):", bg=self.BG_COLOR, font=("Tahoma", 8)).pack(side=tk.LEFT, padx=(6, 2))
        tk.Spinbox(sm_row, from_=50, to=3000, increment=50, width=5, textvariable=self.smooth_dur_var, font=("Tahoma", 8)).pack(side=tk.LEFT)

    # =========================================================================
    # Center Pane: 2D Visual Robotic Hand Canvas
    # =========================================================================

    def _build_hand_canvas(self, parent: tk.Frame) -> None:
        """Center canvas drawing the robotic hand and joints in real time."""
        title_bar = tk.Frame(parent, bg=self.ACCENT_COLOR, bd=1, relief=tk.RAISED)
        title_bar.pack(fill=tk.X, padx=2, pady=2)
        tk.Label(
            title_bar, text="ROBOTIC HAND SCHEMATIC VISUALIZER", fg="white", bg=self.ACCENT_COLOR,
            font=("Tahoma", 10, "bold"), anchor="w", padx=6
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.canvas = tk.Canvas(parent, bg=self.CANVAS_BG, bd=2, relief=tk.SUNKEN, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.canvas.bind("<Configure>", lambda e: self._render_hand_canvas())

        # Subtext legend
        legend_frame = tk.Frame(parent, bg=self.BG_COLOR)
        legend_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        tk.Label(
            legend_frame, text="Interactive: Visual posture updates with angles. Wrist: S6 rotates base.",
            font=("Tahoma", 8, "italic"), bg=self.BG_COLOR, fg="#555555"
        ).pack(side=tk.LEFT, padx=4)

    def _render_hand_canvas(self) -> None:
        """Draw the robotic hand geometry on the canvas reflecting current angles."""
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 50 or h < 50:
            w, h = 380, 500

        # Draw grid background
        grid_step = 25
        for x in range(0, w, grid_step):
            self.canvas.create_line(x, 0, x, h, fill="#232C33", width=1)
        for y in range(0, h, grid_step):
            self.canvas.create_line(0, y, w, y, fill="#232C33", width=1)

        angles = self.ctrl.current_angles
        wrist_angle = angles[5]  # 0 to 180, 90 is straight

        # Center reference point for palm base
        cx = w / 2.0
        cy = h * 0.72

        # Rotate entire hand slightly based on wrist angle
        # 90° = 0 rad, 0° = -35 deg, 180° = +35 deg
        wrist_rot_rad = math.radians((wrist_angle - 90) * 0.4)

        # Helper to rotate and translate points around (cx, cy)
        def transform(px, py):
            dx = px - cx
            dy = py - cy
            rx = dx * math.cos(wrist_rot_rad) - dy * math.sin(wrist_rot_rad)
            ry = dx * math.sin(wrist_rot_rad) + dy * math.cos(wrist_rot_rad)
            return cx + rx, cy + ry

        # 1. Draw Wrist Mount Base / Turntable
        base_w = 90
        base_h = 45
        b_p1 = transform(cx - base_w/2, cy + 30)
        b_p2 = transform(cx + base_w/2, cy + 30)
        b_p3 = transform(cx + base_w/2, cy + 30 + base_h)
        b_p4 = transform(cx - base_w/2, cy + 30 + base_h)
        self.canvas.create_polygon([b_p1, b_p2, b_p3, b_p4], fill="#1E2A38", outline="#4A6572", width=2)
        self.canvas.create_text(
            *transform(cx, cy + 50), text=f"WRIST S6: {wrist_angle}°",
            fill="#E5C07B", font=("Tahoma", 8, "bold")
        )

        # 2. Draw Palm
        palm_w = 110
        palm_h = 80
        p_bl = transform(cx - palm_w/2, cy + 15)
        p_br = transform(cx + palm_w/2, cy + 15)
        p_tr = transform(cx + palm_w/2 - 10, cy - palm_h)
        p_tl = transform(cx - palm_w/2 - 10, cy - palm_h + 15)
        self.canvas.create_polygon([p_bl, p_br, p_tr, p_tl], fill=self.PALM_COLOR, outline="#61AFEF", width=2)

        # Palm center label
        self.canvas.create_text(
            *transform(cx, cy - 25), text="uHand UNO", fill="#ABB2BF", font=("Tahoma", 9, "bold")
        )

        # 3. Draw 5 Fingers
        # Finger root coordinates relative to palm before rotation
        finger_configs = [
            # (channel_idx, name, root_x, root_y, base_angle_offset_deg, segment_lengths)
            (0, "Thumb", cx - 48, cy - 10, -65, [28, 24, 20]),
            (1, "Index", cx - 35, cy - palm_h + 10, -15, [36, 26, 20]),
            (2, "Middle", cx - 10, cy - palm_h + 5, -3, [40, 30, 22]),
            (3, "Ring", cx + 15, cy - palm_h + 10, 8, [36, 26, 20]),
            (4, "Pinky", cx + 38, cy - palm_h + 20, 22, [28, 22, 16]),
        ]

        for ch, fname, rx, ry, base_ang, seg_lens in finger_configs:
            angle = angles[ch]  # 0 to 180 degrees
            # When angle=180: finger extended straight along base_ang
            # When angle=0: finger curls inward (each joint bends ~45-50 degrees)
            curl_factor = (180.0 - angle) / 180.0  # 0.0 when 180° (open), 1.0 when 0° (curled)
            joint_curl_deg = curl_factor * 52.0  # progressive bend per segment

            # Start joint
            curr_x, curr_y = rx, ry
            curr_ang_deg = -90 + base_ang  # -90 is pointing straight up

            # Transform root joint
            t_root = transform(curr_x, curr_y)
            self.canvas.create_oval(
                t_root[0] - 4, t_root[1] - 4, t_root[0] + 4, t_root[1] + 4,
                fill=self.JOINT_COLOR, outline="#FFFFFF", width=1
            )

            # Draw segments
            prev_pt = t_root
            for seg_idx, seg_len in enumerate(seg_lens):
                # Bend segment
                curr_ang_deg += joint_curl_deg
                rad = math.radians(curr_ang_deg)
                curr_x += seg_len * math.cos(rad)
                curr_y += seg_len * math.sin(rad)

                t_next = transform(curr_x, curr_y)

                # Segment line
                thickness = 6 - seg_idx
                self.canvas.create_line(
                    prev_pt[0], prev_pt[1], t_next[0], t_next[1],
                    fill=self.BONE_COLOR, width=thickness, capstyle=tk.ROUND
                )

                # Joint circle
                self.canvas.create_oval(
                    t_next[0] - 3, t_next[1] - 3, t_next[0] + 3, t_next[1] + 3,
                    fill=self.JOINT_COLOR, outline="#333333", width=1
                )
                prev_pt = t_next

            # Label finger tip with channel & current angle
            self.canvas.create_text(
                prev_pt[0], prev_pt[1] - 12,
                text=f"{fname[:3]}:{angle}°", fill="#98C379", font=("Tahoma", 7, "bold")
            )

    # =========================================================================
    # Right Pane: Notebook Tabs (Presets, Sequencer, Peripherals, Calibration)
    # =========================================================================

    def _build_notebook_tabs(self, parent: tk.Frame) -> None:
        """Right pane notebook containing presets, sequencer, peripherals, and calibration."""
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Tab 1: Preset Gestures
        tab_presets = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_presets, text=" Gestures & Poses ")
        self._build_tab_presets(tab_presets)

        # Tab 2: Sequence Recorder & Player
        tab_seq = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_seq, text=" Sequence Recorder ")
        self._build_tab_sequencer(tab_seq)

        # Tab 3: Peripherals (Buzzer & RGB LED)
        tab_periph = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_periph, text=" Peripherals ")
        self._build_tab_peripherals(tab_periph)

        # Tab 4: Calibration & Limits
        tab_calib = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_calib, text=" Calibration ")
        self._build_tab_calibration(tab_calib)

    def _build_tab_presets(self, parent: tk.Frame) -> None:
        """Tab with grid of buttons for all preset gestures."""
        top_lbl = tk.Label(
            parent, text="CLICK ANY PRESET GESTURE TO ACTUATE IMMEDIATELY:",
            font=("Tahoma", 9, "bold"), bg=self.BG_COLOR, fg=self.ACCENT_COLOR
        )
        top_lbl.pack(anchor="w", padx=6, pady=6)

        # Scrollable button grid
        c = tk.Canvas(parent, bg=self.BG_COLOR, highlightthickness=0)
        sb = tk.Scrollbar(parent, orient=tk.VERTICAL, command=c.yview)
        grid_frame = tk.Frame(c, bg=self.BG_COLOR)

        grid_frame.bind("<Configure>", lambda e: c.configure(scrollregion=c.bbox("all")))
        c.create_window((0, 0), window=grid_frame, anchor="nw")
        c.configure(yscrollcommand=sb.set)

        c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        cols = 2
        for idx, (name, pose) in enumerate(gestures.PRESET_POSES.items()):
            btn = tk.Button(
                grid_frame, text=f"{name}\n{pose}", font=("Tahoma", 8, "bold"),
                bg="#D4D0C8", relief=tk.RAISED, bd=2, width=22, height=2,
                command=lambda p=pose: self._apply_pose(list(p))
            )
            btn.grid(row=idx // cols, column=idx % cols, padx=4, pady=3, sticky="nsew")

    def _build_tab_sequencer(self, parent: tk.Frame) -> None:
        """Tab with sequence recording, keyframe list, and player."""
        ctrl_frame = tk.Frame(parent, bg=self.BG_COLOR)
        ctrl_frame.pack(fill=tk.X, padx=4, pady=4)

        tk.Button(
            ctrl_frame, text="+ Capture Current Pose", font=("Tahoma", 8, "bold"),
            bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._capture_frame
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            ctrl_frame, text="Delete Frame", font=("Tahoma", 8),
            bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._delete_frame
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            ctrl_frame, text="Clear All", font=("Tahoma", 8),
            bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._clear_frames
        ).pack(side=tk.LEFT, padx=2)

        # Keyframe Listbox
        list_frame = tk.Frame(parent, bg=self.BG_COLOR)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self.seq_listbox = tk.Listbox(
            list_frame, font=("Courier New", 9), selectmode=tk.SINGLE,
            bg="white", bd=2, relief=tk.SUNKEN
        )
        seq_sb = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.seq_listbox.yview)
        self.seq_listbox.configure(yscrollcommand=seq_sb.set)
        self.seq_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        seq_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Playback controls
        play_frame = tk.LabelFrame(parent, text="Playback Engine", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        play_frame.pack(fill=tk.X, padx=4, pady=4)

        p1 = tk.Frame(play_frame, bg=self.BG_COLOR)
        p1.pack(fill=tk.X, padx=4, pady=2)

        self.btn_play_seq = tk.Button(
            p1, text="Play Sequence", font=("Tahoma", 9, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=8, command=self._play_custom_sequence
        )
        self.btn_play_seq.pack(side=tk.LEFT, padx=2)

        self.btn_stop_seq = tk.Button(
            p1, text="Stop", font=("Tahoma", 9), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=6, command=self.ctrl.stop_sequence
        )
        self.btn_stop_seq.pack(side=tk.LEFT, padx=2)

        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(p1, text="Loop", variable=self.loop_var, bg=self.BG_COLOR, font=("Tahoma", 8)).pack(side=tk.LEFT, padx=4)

        tk.Label(p1, text="Speed:", bg=self.BG_COLOR, font=("Tahoma", 8)).pack(side=tk.LEFT, padx=(6, 2))
        self.speed_var = tk.DoubleVar(value=1.0)
        tk.Spinbox(p1, from_=0.25, to=3.0, increment=0.25, width=4, textvariable=self.speed_var, font=("Tahoma", 8)).pack(side=tk.LEFT)

        # Preset sequences
        p2 = tk.Frame(play_frame, bg=self.BG_COLOR)
        p2.pack(fill=tk.X, padx=4, pady=4)
        tk.Label(p2, text="Load Preset Animation:", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=2)

        for sname in ["Wave", "Counting 1-5", "Finger Dance / Strum", "Grab & Release"]:
            btn = tk.Button(
                p2, text=sname, font=("Tahoma", 7), bg="#D4D0C8", relief=tk.RAISED, bd=1,
                command=lambda n=sname: self._load_preset_sequence(n)
            )
            btn.pack(side=tk.LEFT, padx=2)

    def _build_tab_peripherals(self, parent: tk.Frame) -> None:
        """Buzzer and RGB LED controls on the expansion shield."""
        # RGB LED Box
        rgb_box = tk.LabelFrame(parent, text="RGB LED (WS2812 / 0x03 FUNC_SET_RGB)", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        rgb_box.pack(fill=tk.X, padx=4, pady=4)

        # Color presets
        pal_frame = tk.Frame(rgb_box, bg=self.BG_COLOR)
        pal_frame.pack(fill=tk.X, padx=4, pady=2)

        colors = [
            ("Red", (255, 0, 0), "#FF0000", "white"),
            ("Green", (0, 255, 0), "#00FF00", "black"),
            ("Blue", (0, 0, 255), "#0000FF", "white"),
            ("Yellow", (255, 255, 0), "#FFFF00", "black"),
            ("Cyan", (0, 255, 255), "#00FFFF", "black"),
            ("Magenta", (255, 0, 255), "#FF00FF", "white"),
            ("White", (255, 255, 255), "#FFFFFF", "black"),
            ("OFF", (0, 0, 0), "#000000", "white"),
        ]

        for name, rgb, hexcode, fg in colors:
            btn = tk.Button(
                pal_frame, text=name, bg=hexcode, fg=fg, font=("Tahoma", 7, "bold"),
                width=6, relief=tk.RAISED, bd=2,
                command=lambda c=rgb: self._apply_rgb(*c)
            )
            btn.pack(side=tk.LEFT, expand=True, padx=1)

        # RGB Sliders
        sl_frame = tk.Frame(rgb_box, bg=self.BG_COLOR)
        sl_frame.pack(fill=tk.X, padx=4, pady=4)

        self.r_var = tk.IntVar(value=0)
        self.g_var = tk.IntVar(value=0)
        self.b_var = tk.IntVar(value=0)

        for label, var in [("R", self.r_var), ("G", self.g_var), ("B", self.b_var)]:
            tk.Label(sl_frame, text=label+":", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=(4, 1))
            tk.Scale(
                sl_frame, from_=0, to=255, orient=tk.HORIZONTAL, variable=var,
                bg=self.BG_COLOR, highlightthickness=0, length=70,
                command=lambda v: self._update_rgb_swatch()
            ).pack(side=tk.LEFT, padx=2)

        self.swatch = tk.Canvas(sl_frame, width=32, height=20, bg="#000000", bd=2, relief=tk.SUNKEN)
        self.swatch.pack(side=tk.LEFT, padx=6)

        tk.Button(
            sl_frame, text="Send RGB", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=lambda: self._apply_rgb(self.r_var.get(), self.g_var.get(), self.b_var.get())
        ).pack(side=tk.LEFT, padx=2)

        # Buzzer Box
        buz_box = tk.LabelFrame(parent, text="Buzzer (0x02 FUNC_SET_BUZZER)", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        buz_box.pack(fill=tk.X, padx=4, pady=6)

        b_row = tk.Frame(buz_box, bg=self.BG_COLOR)
        b_row.pack(fill=tk.X, padx=4, pady=4)

        tk.Label(b_row, text="Freq (Hz):", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=2)
        self.buz_freq_var = tk.IntVar(value=1000)
        tk.Spinbox(b_row, from_=100, to=5000, increment=50, width=6, textvariable=self.buz_freq_var, font=("Tahoma", 9)).pack(side=tk.LEFT, padx=2)

        tk.Label(b_row, text="Duration (ms):", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=(8, 2))
        self.buz_dur_var = tk.IntVar(value=200)
        tk.Spinbox(b_row, from_=50, to=3000, increment=50, width=6, textvariable=self.buz_dur_var, font=("Tahoma", 9)).pack(side=tk.LEFT, padx=2)

        tk.Button(
            b_row, text="BEEP!", font=("Tahoma", 9, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=8,
            command=lambda: self.ctrl.set_buzzer(self.buz_freq_var.get(), self.buz_dur_var.get())
        ).pack(side=tk.LEFT, padx=8)

        # Chimes
        c_row = tk.Frame(buz_box, bg=self.BG_COLOR)
        c_row.pack(fill=tk.X, padx=4, pady=(0, 4))
        for tone_name, freq in [("Low (440Hz)", 440), ("Mid (880Hz)", 880), ("High (1760Hz)", 1760), ("Alert (2500Hz)", 2500)]:
            tk.Button(
                c_row, text=tone_name, font=("Tahoma", 7), bg="#D4D0C8", relief=tk.RAISED, bd=1,
                command=lambda f=freq: self.ctrl.set_buzzer(f, 150)
            ).pack(side=tk.LEFT, expand=True, padx=1)

    def _build_tab_calibration(self, parent: tk.Frame) -> None:
        """Trims, hardware limits, and axis inversions."""
        tk.Label(
            parent, text="HARDWARE OFFSETS & LIMIT CALIBRATION:",
            font=("Tahoma", 9, "bold"), bg=self.BG_COLOR, fg=self.ACCENT_COLOR
        ).pack(anchor="w", padx=6, pady=4)

        box = tk.Frame(parent, bg=self.BG_COLOR)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # Header
        headers = ["Channel", "Trim (-45..+45°)", "Invert", "Min Limit", "Max Limit"]
        for col_idx, h in enumerate(headers):
            tk.Label(box, text=h, font=("Tahoma", 8, "bold"), bg="#D4D0C8", bd=1, relief=tk.GROOVE).grid(
                row=0, column=col_idx, sticky="ew", padx=1, pady=2
            )

        self.cal_min_vars = []
        self.cal_max_vars = []

        for ch in range(6):
            name = HandController.SERVO_NAMES[ch]
            tk.Label(box, text=f"S{ch+1}: {name}", font=("Tahoma", 8), bg=self.BG_COLOR).grid(row=ch+1, column=0, sticky="w", padx=2)

            # Trim
            spin_t = tk.Spinbox(
                box, from_=-45, to=45, width=5, font=("Tahoma", 8),
                textvariable=self.trim_vars[ch],
                command=lambda c=ch: self._on_trim_changed(c)
            )
            spin_t.grid(row=ch+1, column=1, padx=2, pady=1)

            # Invert
            chk_i = tk.Checkbutton(
                box, variable=self.invert_vars[ch], bg=self.BG_COLOR,
                command=lambda c=ch: self._on_invert_toggled(c)
            )
            chk_i.grid(row=ch+1, column=2, padx=2, pady=1)

            # Min limit
            min_v = tk.IntVar(value=self.ctrl.min_limits[ch])
            self.cal_min_vars.append(min_v)
            spin_min = tk.Spinbox(
                box, from_=0, to=180, width=5, font=("Tahoma", 8), textvariable=min_v,
                command=lambda c=ch: self._on_limit_changed(c)
            )
            spin_min.grid(row=ch+1, column=3, padx=2, pady=1)

            # Max limit
            max_v = tk.IntVar(value=self.ctrl.max_limits[ch])
            self.cal_max_vars.append(max_v)
            spin_max = tk.Spinbox(
                box, from_=0, to=180, width=5, font=("Tahoma", 8), textvariable=max_v,
                command=lambda c=ch: self._on_limit_changed(c)
            )
            spin_max.grid(row=ch+1, column=4, padx=2, pady=1)

        # Buttons
        b_frame = tk.Frame(parent, bg=self.BG_COLOR)
        b_frame.pack(fill=tk.X, padx=4, pady=6)
        tk.Button(b_frame, text="Save Calibration File", font=("Tahoma", 8, "bold"), bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._save_calibration).pack(side=tk.LEFT, padx=2)
        tk.Button(b_frame, text="Load Calibration File", font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._load_calibration).pack(side=tk.LEFT, padx=2)
        tk.Button(b_frame, text="Reset to Defaults", font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._reset_calibration).pack(side=tk.LEFT, padx=2)

    # =========================================================================
    # Bottom Pane: Serial Traffic & Reverse-Engineering Packet Console
    # =========================================================================

    def _build_bottom_packet_console(self) -> None:
        """Bottom console for bidirectional packet inspection and hex injection."""
        panel = tk.LabelFrame(
            self.root, text="Bidirectional Serial Packet Console & Reverse-Engineering Console",
            font=("Tahoma", 9, "bold"), bg=self.BG_COLOR, bd=2, relief=tk.GROOVE
        )
        panel.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=2)

        # Text Console
        txt_frame = tk.Frame(panel, bg=self.BG_COLOR)
        txt_frame.pack(fill=tk.X, padx=4, pady=2)

        self.console_txt = tk.Text(
            txt_frame, height=5, font=("Courier New", 9), bg="#101418", fg="#61AFEF",
            bd=2, relief=tk.SUNKEN
        )
        sb = tk.Scrollbar(txt_frame, orient=tk.VERTICAL, command=self.console_txt.yview)
        self.console_txt.configure(yscrollcommand=sb.set)
        self.console_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure color tags
        self.console_txt.tag_config("TX", foreground="#61AFEF")
        self.console_txt.tag_config("RX", foreground="#98C379")
        self.console_txt.tag_config("ERR", foreground="#E06C75")
        self.console_txt.tag_config("SYS", foreground="#E5C07B")

        # Bottom Input / Injection bar
        inj_bar = tk.Frame(panel, bg=self.BG_COLOR)
        inj_bar.pack(fill=tk.X, padx=4, pady=3)

        tk.Label(inj_bar, text="Raw UART packet (serial only):", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=2)
        self.hex_input_var = tk.StringVar(value="AA 77 01 06 5A 5A 5A 5A 5A 5A DC")
        self.hex_entry = tk.Entry(inj_bar, textvariable=self.hex_input_var, font=("Courier New", 9), width=42)
        self.hex_entry.pack(side=tk.LEFT, padx=2)
        self.hex_entry.bind("<Return>", lambda e: self._on_send_hex_clicked())

        self.hex_send_button = tk.Button(
            inj_bar, text="Send Hex", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._on_send_hex_clicked
        )
        self.hex_send_button.pack(side=tk.LEFT, padx=2)

        tk.Button(
            inj_bar, text="Clear Log", font=("Tahoma", 8), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=lambda: self.console_txt.delete("1.0", tk.END)
        ).pack(side=tk.LEFT, padx=6)

        tk.Checkbutton(
            inj_bar, text="Auto-Scroll", variable=self.auto_scroll_var,
            bg=self.BG_COLOR, font=("Tahoma", 8)
        ).pack(side=tk.LEFT, padx=2)

    def _build_status_bar(self) -> None:
        """Footer status bar."""
        self.status_bar = tk.Label(
            self.root, text="Ready | Hiwonder Bluetooth LE is the red default connection",
            bd=1, relief=tk.SUNKEN, anchor=tk.W, font=("Tahoma", 8), bg="#D4D0C8"
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # =========================================================================
    # Event Handlers & Callbacks
    # =========================================================================

    def _auto_connect(self) -> None:
        """Auto-connect to the saved Hiwonder BLE module, which is the default transport."""
        if self.transport_var.get() == "Bluetooth LE":
            self._on_connect_clicked(show_error=False)
            return
        self.ctrl.port = self.port_var.get()
        try:
            self.ctrl.baudrate = int(self.baud_var.get())
        except ValueError:
            self.ctrl.baudrate = 9600

        if not self.ctrl.port:
            self.status_bar.config(text="DISCONNECTED: Select the uHand UART COM port")
            return
        self._connect_in_background(show_error=False)

    def _on_transport_changed(self, event=None) -> None:
        """Show BLE device settings by default, or serial options when selected."""
        is_ble = self.transport_var.get() == "Bluetooth LE"
        next_transport = "ble" if is_ble else "serial"
        if self.ctrl.transport != next_transport and self.ctrl.is_connected():
            self.ctrl.disconnect()
        ble_widgets = (self.ble_label, self.ble_target_combo, self.btn_refresh_ble)
        serial_widgets = (
            self.port_label, self.port_combo, self.btn_refresh_serial,
            self.baud_label, self.baud_combo, self.protocol_label, self.proto_combo,
        )
        for widget in ble_widgets:
            if is_ble and not widget.winfo_manager():
                widget.pack(side=tk.LEFT, padx=2)
            elif not is_ble and widget.winfo_manager():
                widget.pack_forget()
        for widget in serial_widgets:
            if not is_ble and not widget.winfo_manager():
                widget.pack(side=tk.LEFT, padx=2)
            elif is_ble and widget.winfo_manager():
                widget.pack_forget()
        self.ctrl.transport = next_transport
        self.ctrl.log("SYS", f"Selected {'Hiwonder BLE app protocol' if is_ble else 'serial UART'} transport")
        if hasattr(self, "btn_query"):
            self.btn_query.config(
                state=tk.DISABLED if is_ble else tk.NORMAL,
                text="Angle feedback unavailable" if is_ble else "Read Angles (serial)",
            )
        if hasattr(self, "hex_send_button"):
            self.hex_entry.config(state=tk.DISABLED if is_ble else tk.NORMAL)
            self.hex_send_button.config(state=tk.DISABLED if is_ble else tk.NORMAL)

    def _on_connect_clicked(self, show_error: bool = True) -> None:
        """Start a hardware connection without blocking Tk while BLE scans."""
        self.ctrl.transport = "ble" if self.transport_var.get() == "Bluetooth LE" else "serial"
        if self.ctrl.transport == "ble":
            self.ctrl.ble_name, self.ctrl.ble_address = self._parse_ble_target(self.ble_target_var.get())
        else:
            self.ctrl.port = self.port_var.get()
            try:
                self.ctrl.baudrate = int(self.baud_var.get())
            except ValueError:
                self.ctrl.baudrate = 9600
            for p in ProtocolType:
                if p.value == self.proto_var.get():
                    self.ctrl.protocol = p
                    break
        self.ctrl.simulation_mode = self.sim_var.get()
        self._connect_in_background(show_error=show_error)

    def _connect_in_background(self, show_error: bool) -> None:
        self.btn_connect.config(state=tk.DISABLED)
        self.transport_combo.config(state=tk.DISABLED)
        self.ble_target_combo.config(state=tk.DISABLED)
        self.port_combo.config(state=tk.DISABLED)
        self.btn_refresh_ble.config(state=tk.DISABLED)
        self.btn_refresh_serial.config(state=tk.DISABLED)
        target = self.ctrl.ble_name if self.ctrl.transport == "ble" else self.ctrl.port
        self.status_bar.config(text=f"Connecting to {target or 'uHand'}…")

        def worker() -> None:
            success, msg = self.ctrl.connect()
            if not success:
                self.root.after(0, lambda: self.btn_connect.config(state=tk.NORMAL))
                if show_error:
                    self.root.after(0, lambda: messagebox.showwarning("Connection Failed", msg))

        threading.Thread(target=worker, name="uHand-connect", daemon=True).start()

    def _on_disconnect_clicked(self) -> None:
        """Disconnect trigger."""
        self.ctrl.disconnect()

    def _on_sim_toggled(self) -> None:
        """Toggle simulation mode."""
        was_connected = self.ctrl.is_connected()
        self.ctrl.simulation_mode = self.sim_var.get()
        if was_connected or self.ctrl.is_connected():
            self.ctrl.disconnect()
            self._connect_in_background(show_error=False)

    def _on_protocol_changed(self, event=None) -> None:
        """Switch communication protocol."""
        val = self.proto_var.get()
        for p in ProtocolType:
            if p.value == val:
                self.ctrl.protocol = p
                self.ctrl.log("SYS", f"Switched serial protocol to {p.value}")
                break

    def _on_estop_clicked(self) -> None:
        """Emergency neutral stop."""
        self.ctrl.stop_sequence()
        self._apply_pose([90]*6, force=True)
        self.ctrl.set_rgb(255, 0, 0)
        self.ctrl.set_buzzer(2000, 300)

    def _on_slider_moved(self, ch: int, val: str) -> None:
        """Called when a channel slider is dragged."""
        angle = int(float(val))
        angles = list(self.ctrl.current_angles)
        angles[ch] = angle

        if self.smooth_move_var.get():
            threading.Thread(
                target=lambda: self.ctrl.move_smooth(angles, duration_ms=self.smooth_dur_var.get()),
                daemon=True
            ).start()
        elif self.ctrl.transport == "ble" and not self.ctrl.simulation_mode:
            self.ctrl.set_servo_angle(ch, angle)
        else:
            self.ctrl.send_angles(angles)
        self._render_hand_canvas()

    def _on_spin_changed(self, ch: int) -> None:
        """Called when a spinbox value changes."""
        val = self.channel_vars[ch].get()
        self._on_slider_moved(ch, str(val))

    def _on_nudge_clicked(self, ch: int, val: Union[int, str]) -> None:
        """Nudge button clicked (+/- or direct pose)."""
        if isinstance(val, str):
            target = int(val)
        else:
            target = self.ctrl.current_angles[ch] + val
        target = max(0, min(180, target))
        self.channel_vars[ch].set(target)
        self._on_slider_moved(ch, str(target))

    def _on_invert_toggled(self, ch: int) -> None:
        """Toggle inversion on a channel."""
        self.ctrl.inverted[ch] = self.invert_vars[ch].get()
        # Resend current angle to update hardware
        self.ctrl.send_angles(self.ctrl.current_angles, force=True)

    def _on_trim_changed(self, ch: int) -> None:
        """Adjust trim on a channel."""
        self.ctrl.trims[ch] = self.trim_vars[ch].get()
        self.ctrl.send_angles(self.ctrl.current_angles, force=True)

    def _on_limit_changed(self, ch: int) -> None:
        """Update hardware angle limits."""
        self.ctrl.min_limits[ch] = self.cal_min_vars[ch].get()
        self.ctrl.max_limits[ch] = self.cal_max_vars[ch].get()

    def _apply_pose(self, angles: List[int], force: bool = False) -> None:
        """Apply a 6-angle pose to controls, canvas, and hardware."""
        for i, a in enumerate(angles):
            self.channel_vars[i].set(a)
        if self.smooth_move_var.get() and not force:
            threading.Thread(
                target=lambda: self.ctrl.move_smooth(angles, duration_ms=self.smooth_dur_var.get()),
                daemon=True
            ).start()
        else:
            self.ctrl.send_angles(angles, force=force)
        self._render_hand_canvas()

    def _apply_rgb(self, r: int, g: int, b: int) -> None:
        """Set RGB color."""
        self.r_var.set(r)
        self.g_var.set(g)
        self.b_var.set(b)
        self._update_rgb_swatch()
        self.ctrl.set_rgb(r, g, b)

    def _update_rgb_swatch(self) -> None:
        """Update swatch box color."""
        hex_c = f"#{self.r_var.get():02x}{self.g_var.get():02x}{self.b_var.get():02x}"
        self.swatch.configure(bg=hex_c)

    def _on_send_hex_clicked(self) -> None:
        """Transmit raw hex packet from console entry."""
        hex_str = self.hex_input_var.get()
        self.ctrl.send_raw_hex(hex_str)

    # =========================================================================
    # Sequencer Actions
    # =========================================================================

    def _capture_frame(self) -> None:
        """Add current pose to sequence listbox."""
        pose = tuple(self.ctrl.current_angles)
        dur = self.smooth_dur_var.get()
        self.sequence_frames.append((pose, dur))
        idx = len(self.sequence_frames)
        self.seq_listbox.insert(tk.END, f"#{idx:2d} | Pose: {pose} | {dur}ms")

    def _delete_frame(self) -> None:
        """Delete selected frame."""
        sel = self.seq_listbox.curselection()
        if sel:
            idx = sel[0]
            self.seq_listbox.delete(idx)
            self.sequence_frames.pop(idx)

    def _clear_frames(self) -> None:
        """Clear all frames."""
        self.seq_listbox.delete(0, tk.END)
        self.sequence_frames.clear()

    def _play_custom_sequence(self) -> None:
        """Play current sequence list."""
        if not self.sequence_frames:
            messagebox.showinfo("Sequencer", "Sequence buffer is empty. Capture frames first!")
            return
        self.ctrl.play_sequence(
            self.sequence_frames,
            loop=self.loop_var.get(),
            speed_factor=self.speed_var.get(),
            on_complete=lambda: self.status_bar.config(text="Sequence playback completed")
        )

    def _load_preset_sequence(self, name: str) -> None:
        """Load built-in animation into sequence editor."""
        preset = gestures.PRESET_SEQUENCES.get(name)
        if preset:
            self._clear_frames()
            self.sequence_frames = list(preset)
            for idx, (pose, dur) in enumerate(self.sequence_frames, 1):
                self.seq_listbox.insert(tk.END, f"#{idx:2d} | Pose: {pose} | {dur}ms")
            self._play_custom_sequence()

    def _save_sequence(self) -> None:
        """Export sequence to JSON."""
        try:
            with open("sequence.json", "w", encoding="utf-8") as f:
                json.dump(self.sequence_frames, f, indent=2)
            messagebox.showinfo("Export", "Saved sequence to sequence.json")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def _load_sequence(self) -> None:
        """Import sequence from JSON."""
        if not os.path.exists("sequence.json"):
            messagebox.showwarning("Load", "sequence.json not found")
            return
        try:
            with open("sequence.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            self._clear_frames()
            self.sequence_frames = [(tuple(item[0]), item[1]) for item in data]
            for idx, (pose, dur) in enumerate(self.sequence_frames, 1):
                self.seq_listbox.insert(tk.END, f"#{idx:2d} | Pose: {pose} | {dur}ms")
            messagebox.showinfo("Import", f"Loaded {len(self.sequence_frames)} frames!")
        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    def _save_calibration(self) -> None:
        """Save calibration to file."""
        self.ctrl.save_calibration("calibration.json")
        messagebox.showinfo("Calibration", "Saved calibration.json")

    def _load_calibration(self) -> None:
        """Load calibration from file."""
        if self.ctrl.load_calibration("calibration.json"):
            for i in range(6):
                self.trim_vars[i].set(self.ctrl.trims[i])
                self.invert_vars[i].set(self.ctrl.inverted[i])
                self.cal_min_vars[i].set(self.ctrl.min_limits[i])
                self.cal_max_vars[i].set(self.ctrl.max_limits[i])
            messagebox.showinfo("Calibration", "Loaded calibration.json")
        else:
            messagebox.showwarning("Calibration", "calibration.json not found")

    def _reset_calibration(self) -> None:
        """Reset calibration to zero."""
        for i in range(6):
            self.trim_vars[i].set(0)
            self.invert_vars[i].set(False)
            self.cal_min_vars[i].set(0)
            self.cal_max_vars[i].set(180)
            self._on_trim_changed(i)
            self._on_invert_toggled(i)
            self._on_limit_changed(i)

    # =========================================================================
    # Thread-Safe Controller Listeners
    # =========================================================================

    def _on_controller_log(self, direction: str, text: str) -> None:
        """Append log line to text widget (invoked via root.after)."""
        def _update():
            tag = direction if direction in ("TX", "RX", "ERR", "SYS") else "SYS"
            tstamp = time.strftime("%H:%M:%S")
            line = f"[{tstamp}] [{direction:<3}] {text}\n"
            self.console_txt.insert(tk.END, line, tag)
            if self.auto_scroll_var.get():
                self.console_txt.see(tk.END)
        self.root.after(0, _update)

    def _on_controller_angles_updated(self, angles: List[int]) -> None:
        """Reflect angle update from hardware (invoked via root.after)."""
        def _update():
            for i, a in enumerate(angles):
                self.channel_vars[i].set(a)
            self._render_hand_canvas()
        self.root.after(0, _update)

    def _on_controller_connection_changed(self, connected: bool, message: str) -> None:
        """Update connection lamps and status buttons."""
        def _update():
            if connected:
                if self.ctrl.transport == "ble":
                    self.ble_target_var.set(self._format_ble_target(self.ctrl.ble_name, self.ctrl.ble_address))
                    self.ble_target_combo.configure(values=[self.ble_target_var.get()])
                color = "#FF9900" if self.ctrl.simulation_mode else "#00FF00"
                self._draw_lamp(color)
                self.btn_connect.config(state=tk.DISABLED)
                self.btn_disconnect.config(state=tk.NORMAL)
                prefix = "SIMULATION" if self.ctrl.simulation_mode else "CONNECTED"
                self.status_bar.config(text=f"{prefix}: {message}")
            else:
                self._draw_lamp("red")
                self.btn_connect.config(state=tk.NORMAL)
                self.btn_disconnect.config(state=tk.DISABLED)
                self.status_bar.config(text=f"DISCONNECTED: {message}")
            self.transport_combo.config(state="readonly")
            self.ble_target_combo.config(state=tk.NORMAL)
            self.port_combo.config(state=tk.NORMAL)
            self.btn_refresh_ble.config(state=tk.NORMAL)
            self.btn_refresh_serial.config(state=tk.NORMAL)
        self.root.after(0, _update)

    def _close_application(self) -> None:
        """Release BLE/serial resources before closing the window."""
        try:
            self.ctrl.disconnect()
        finally:
            self.root.destroy()

    def _on_sequence_step(self, step: int, total: int) -> None:
        """Update status bar with active sequence step."""
        def _update():
            self.status_bar.config(text=f"Playing Sequence: Step {step}/{total}")
        self.root.after(0, _update)

    # =========================================================================
    # Help Dialogs
    # =========================================================================

    def _show_pinout_help(self) -> None:
        """Display connection guidance for BLE and the optional serial UART."""
        msg = (
            "Hiwonder uHand UNO / 6CH Knob Shield Wiring:\n\n"
            "• Microcontroller: Arduino UNO R3 (ATmega328P)\n"
            "• Shield: UNO 6CH Knob Shield V1.1\n"
            "• Default PC connection: built-in Hiwonder Bluetooth LE module; no extra wiring\n"
            "• BLE commands match Wonderbot: A-F + angle + $\n"
            "• Optional wired UART: USB-to-TTL RXD -> IO12, TXD -> IO10, GND -> GND\n"
            "• Optional serial defaults: 9600 baud, 8 data bits, no parity, 1 stop bit\n\n"
            "Servo Channels:\n"
            "  S1 = Thumb  (PWM Pin 11)\n"
            "  S2 = Index  (PWM Pin 10)\n"
            "  S3 = Middle (PWM Pin 9)\n"
            "  S4 = Ring   (PWM Pin 6)\n"
            "  S5 = Pinky  (PWM Pin 5)\n"
            "  S6 = Wrist  (PWM Pin 3 / LFD-06 Servo)\n\n"
            "Knob Potentiometers: Analog Pins A0 - A5\n"
            "Buttons: K1 (Red), K2 (Yellow)\n"
            "Peripherals: Active Buzzer + WS2812 RGB LED\n"
            "External Power: 6V - 8.4V DC Jack (Batteries / Power Adapter)"
        )
        messagebox.showinfo("Hardware & Wiring Guide", msg)

    def _show_protocol_help(self) -> None:
        """Display protocol documentation dialog."""
        msg = (
            "Default Bluetooth LE app protocol (Wonderbot compatible):\n"
            "  A<angle>$ = Thumb; B = Index; C = Middle; D = Ring; E = Pinky; F = Wrist\n"
            "  Angle range: 0-180 degrees. Each command ends with '$'.\n\n"
            "Optional wired serial protocol (0xAA 0x77):\n\n"
            "Frame Structure:\n"
            "  [Header (2B)] [Func (1B)] [Len (1B)] [Data (NB)] [Checksum (1B)]\n"
            "  Header: 0xAA 0x77\n"
            "  Checksum: 0xFF - (sum(Func + Len + Data) & 0xFF)\n\n"
            "Command Functions:\n"
            "  0x01: FUNC_SET_SERVO (Len=6)\n"
            "        Data: [S1, S2, S3, S4, S5, S6] angles (0-180 deg)\n"
            "  0x02: FUNC_SET_BUZZER (Len=4)\n"
            "        Data: [Freq_Lo, Freq_Hi, Dur_Lo, Dur_Hi]\n"
            "  0x03: FUNC_SET_RGB (Len=3)\n"
            "        Data: [Red, Green, Blue] (0-255)\n"
            "  0x11: FUNC_READ_ANGLE (Len=0)\n"
            "        Packet: AA 77 11 00 EE -> returns angles"
        )
        messagebox.showinfo("Protocol Specification", msg)

    def _show_about(self) -> None:
        """About box."""
        msg = (
            "uHand UNO Controller - Maximum Control Suite\n"
            "Version 1.0 (Reverse-Engineer-Anything)\n\n"
            "Developed for high-precision control of the Hiwonder uHand UNO bionic robotic hand.\n"
            "Includes Python Terminal Menu, Legacy Tkinter GUI, and Full Simulation Engine."
        )
        messagebox.showinfo("About uHand UNO Controller", msg)


def launch_gui(port: Optional[str] = None, baud: Optional[int] = None, transport: Optional[str] = None) -> None:
    """Entry point to launch the Tkinter GUI."""
    root = tk.Tk()
    defaults = load_connection_settings()
    app = LegacyHandGUI(
        root,
        default_port=defaults["port"] if port is None else port,
        default_baud=defaults["baudrate"] if baud is None else baud,
    )
    if transport in ("ble", "serial"):
        app.ctrl.transport = transport
        app.transport_var.set("Bluetooth LE" if transport == "ble" else "Serial UART")
        app._on_transport_changed()
    root.mainloop()


if __name__ == "__main__":
    launch_gui()

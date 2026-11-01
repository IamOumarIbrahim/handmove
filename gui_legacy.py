#   HANDMOVE - uHand UNO Controller (tkinter gui)
#        Oumar Ibrahim U22200741

# tkinter gui for the uHand UNO
# has the servo sliders, the hand view (3d or 2d), calibration, preset poses,
# sequence recorder, buzzer / rgb led and a console that shows the packets

import json
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

# add this folder to the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from controller import HandController, ProtocolType
from connection_settings import list_ble_devices, list_serial_ports, load_connection_settings
import gestures
import hand_model


# "name — address" for the device box
def format_ble_target(name, address):
    if not name:
        name = "Hiwonder"
    if address:
        return f"{name} — {address}"
    return name


# splits "name — address" back into the two parts
def parse_ble_target(value):
    if " — " in value:
        parts = value.rsplit(" — ", 1)
        return parts[0].strip(), parts[1].strip()
    name = value.strip()
    if not name:
        name = "Hiwonder"
    return name, ""


class LegacyHandGUI:
    # old windows style colours
    BG_COLOR = "#ECE9D8"  # system gray
    PANEL_BG = "#E0DFD3"
    ACCENT_COLOR = "#0A246A"  # navy title bars
    CANVAS_BG = "#1A2228"  # dark background for the hand drawing
    BONE_COLOR = "#61AFEF"
    JOINT_COLOR = "#E5C07B"
    PALM_COLOR = "#2C3E50"
    DEFAULT_MARK_COLOR = "#C00000"

    def __init__(self, root, default_port="", default_baud=9600):
        self.root = root
        self.root.title("uHand UNO Controller")
        self.root.geometry("1280x850")
        self.root.minsize(1100, 750)
        self.root.configure(bg=self.BG_COLOR)
        self.root.protocol("WM_DELETE_WINDOW", self._close_application)

        # the controller that talks to the hand
        self.ctrl = HandController(
            port=default_port,
            baudrate=default_baud,
            protocol=ProtocolType.UHAND_UNO,
            simulation_mode=False
        )

        # controller callbacks (they come from other threads)
        self.ctrl.on_log = self._on_controller_log
        self.ctrl.on_angles_updated = self._on_controller_angles_updated
        self.ctrl.on_connection_changed = self._on_controller_connection_changed
        self.ctrl.on_sequence_step = self._on_sequence_step

        self.channel_vars = []
        self.channel_spin_vars = []
        self.invert_vars = []
        self.trim_vars = []
        self.auto_scroll_var = tk.BooleanVar(value=True)
        self.smooth_move_var = tk.BooleanVar(value=False)
        self.smooth_dur_var = tk.IntVar(value=300)
        self.sequence_frames = []  # list of (pose, duration ms)
        self.selected_finger_drag = None

        # build the window
        self._build_styles()
        self._build_menu()
        self._build_top_connection_bar()
        self._build_main_panes()
        self._build_bottom_packet_console()
        self._build_status_bar()

        # first drawing of the hand
        self.root.after(100, self._render_hand_canvas)

        # try to connect to the saved device after the window shows up
        self.root.after(300, self._auto_connect)

    #==========================================================================
    # style and menu

    def _build_styles(self):
        style = ttk.Style()
        try:
            if os.name == "nt":
                style.theme_use("winnative")
            else:
                style.theme_use("classic")
        except Exception:
            pass
        style.configure("MarkedDefault.TCombobox", foreground=self.DEFAULT_MARK_COLOR)

    def _build_menu(self):
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
        tools_menu.add_command(label="Neutral (90°)", command=self._pose_neutral)
        tools_menu.add_command(label="Open All (180°)", command=self._pose_open)
        tools_menu.add_command(label="Close All (0°)", command=self._pose_close)
        tools_menu.add_separator()
        tools_menu.add_command(label="Read Angles", command=self.ctrl.query_angles)
        menubar.add_cascade(label="Quick Actions", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Wiring", command=self._show_pinout_help)
        help_menu.add_command(label="Protocol", command=self._show_protocol_help)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    # the 3 quick poses
    def _pose_neutral(self):
        self._apply_pose([90, 90, 90, 90, 90, 90], force=True)

    def _pose_open(self):
        self._apply_pose([180, 180, 180, 180, 180, 90])

    def _pose_close(self):
        self._apply_pose([0, 0, 0, 0, 0, 90])

    #==========================================================================
    # connection bar at the top

    def _build_top_connection_bar(self):
        bar = tk.Frame(self.root, bg=self.BG_COLOR, bd=2, relief=tk.GROOVE)
        bar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=3)

        # connection lamp
        self.conn_lamp = tk.Canvas(bar, width=18, height=18, bg=self.BG_COLOR, highlightthickness=0)
        self.conn_lamp.pack(side=tk.LEFT, padx=6)
        self._draw_lamp("red")

        # hiwonder bluetooth is the default way to connect
        tk.Label(bar, text="Link:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=(4, 2))
        if self.ctrl.transport == "ble":
            self.transport_var = tk.StringVar(value="Bluetooth LE")
        else:
            self.transport_var = tk.StringVar(value="Serial UART")
        self.transport_combo = ttk.Combobox(bar, textvariable=self.transport_var, width=14, state="readonly",
                                            values=["Bluetooth LE", "Serial UART"], style="MarkedDefault.TCombobox")
        self.transport_combo.pack(side=tk.LEFT, padx=2)
        self.transport_combo.bind("<<ComboboxSelected>>", self._on_transport_changed)

        self.ble_label = tk.Label(bar, text="Device:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        self.ble_label.pack(side=tk.LEFT, padx=(6, 2))
        self.ble_target_var = tk.StringVar(value=format_ble_target(self.ctrl.ble_name, self.ctrl.ble_address))
        self.ble_target_combo = ttk.Combobox(bar, textvariable=self.ble_target_var, width=22,
                                             values=[self.ble_target_var.get()], style="MarkedDefault.TCombobox")
        self.ble_target_combo.pack(side=tk.LEFT, padx=2)
        self.btn_refresh_ble = tk.Button(bar, text="Find", font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED,
                                         bd=2, command=self._refresh_ble_devices)
        self.btn_refresh_ble.pack(side=tk.LEFT, padx=2)

        # serial uart is still there as the second option
        self.port_label = tk.Label(bar, text="Port:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        self.port_label.pack(side=tk.LEFT, padx=(8, 2))
        self.port_var = tk.StringVar(value=self.ctrl.port)
        port_values = []
        for port in list_serial_ports():
            port_values.append(port["device"])
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

        # baud rate
        self.baud_label = tk.Label(bar, text="Baud:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        self.baud_label.pack(side=tk.LEFT, padx=(8, 2))
        self.baud_var = tk.StringVar(value=str(self.ctrl.baudrate))
        self.baud_combo = ttk.Combobox(bar, textvariable=self.baud_var, width=8,
                                       values=["9600", "115200", "57600", "19200", "38400"],
                                       style="MarkedDefault.TCombobox")
        self.baud_combo.pack(side=tk.LEFT, padx=2)

        # protocol
        self.protocol_label = tk.Label(bar, text="Protocol:", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        self.protocol_label.pack(side=tk.LEFT, padx=(8, 2))
        self.proto_var = tk.StringVar(value=self.ctrl.protocol.value)
        proto_values = []
        for p in ProtocolType:
            proto_values.append(p.value)
        self.proto_combo = ttk.Combobox(bar, textvariable=self.proto_var, width=28, values=proto_values,
                                        style="MarkedDefault.TCombobox")
        self.proto_combo.pack(side=tk.LEFT, padx=2)
        self.proto_combo.bind("<<ComboboxSelected>>", self._on_protocol_changed)
        self._on_transport_changed()

        # simulation check box
        self.sim_var = tk.BooleanVar(value=self.ctrl.simulation_mode)
        self.sim_check = tk.Checkbutton(
            bar, text="Simulate", variable=self.sim_var,
            bg=self.BG_COLOR, font=("Tahoma", 9), command=self._on_sim_toggled
        )
        self.sim_check.pack(side=tk.LEFT, padx=8)

        # connect / disconnect
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

        self.btn_query = tk.Button(
            bar, text="Read Angles", font=("Tahoma", 9), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=6, command=self.ctrl.query_angles
        )
        self.btn_query.pack(side=tk.LEFT, padx=6)

        # emergency stop (goes to neutral)
        self.btn_estop = tk.Button(
            bar, text="E-STOP", font=("Tahoma", 9, "bold"), fg="red", bg="#FFE4E1",
            relief=tk.RAISED, bd=2, padx=8, command=self._on_estop_clicked
        )
        self.btn_estop.pack(side=tk.RIGHT, padx=6)
        self._on_transport_changed()

    def _refresh_serial_ports(self):
        ports = list_serial_ports()
        values = []
        for port in ports:
            values.append(port["device"])
        self.port_combo.configure(values=values)
        if values:
            self.ctrl.log("SYS", "Available serial ports: " + ", ".join(values))
        else:
            self.ctrl.log("SYS", "Available serial ports: none found")

    def _refresh_ble_devices(self):
        self.status_bar.config(text="Scanning…")
        devices = list_ble_devices(timeout=4.0)
        values = []
        for item in devices:
            values.append(format_ble_target(item["name"], item["address"]))
        if values:
            self.ble_target_combo.configure(values=values)
            self.ctrl.log("SYS", "Nearby BLE devices: " + ", ".join(values))
        else:
            self.ble_target_combo.configure(values=[self.ble_target_var.get()])
            self.ctrl.log("SYS", "Nearby BLE devices: none found")
        self.status_bar.config(text=f"{len(values)} device(s) found")

    def _draw_lamp(self, color):
        self.conn_lamp.delete("all")
        self.conn_lamp.create_oval(2, 2, 16, 16, fill=color, outline="#333333", width=1.5)

    #==========================================================================
    # main area: servos on the left, hand in the middle, tabs on the right

    def _build_main_panes(self):
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=self.BG_COLOR, bd=2, relief=tk.GROOVE,
                               sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # 1. servo sliders
        left_frame = tk.Frame(paned, bg=self.BG_COLOR, bd=2, relief=tk.SUNKEN)
        paned.add(left_frame, minsize=380, width=420)
        self._build_servo_controls(left_frame)

        # 2. 3d hand (or the 2d drawing if there is no opengl)
        center_frame = tk.Frame(paned, bg=self.BG_COLOR, bd=2, relief=tk.SUNKEN)
        paned.add(center_frame, minsize=320, width=380)
        self._build_hand_canvas(center_frame)

        # 3. tabs (poses, sequence, peripherals, calibration)
        right_frame = tk.Frame(paned, bg=self.BG_COLOR, bd=2, relief=tk.SUNKEN)
        paned.add(right_frame, minsize=380, width=460)
        self._build_notebook_tabs(right_frame)

    # left side: the 6 servo channels

    def _build_servo_controls(self, parent):
        title_bar = tk.Frame(parent, bg=self.ACCENT_COLOR, bd=1, relief=tk.RAISED)
        title_bar.pack(fill=tk.X, padx=2, pady=2)
        tk.Label(
            title_bar, text="SERVOS", fg="white", bg=self.ACCENT_COLOR,
            font=("Tahoma", 10, "bold"), anchor="w", padx=6
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        scroll_canvas = tk.Canvas(parent, bg=self.BG_COLOR, highlightthickness=0)
        scrollbar = tk.Scrollbar(parent, orient=tk.VERTICAL, command=scroll_canvas.yview)
        scroll_content = tk.Frame(scroll_canvas, bg=self.BG_COLOR)

        def update_scroll(event):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        scroll_content.bind("<Configure>", update_scroll)
        scroll_canvas.create_window((0, 0), window=scroll_content, anchor="nw")
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # one box for each servo
        for idx in range(len(HandController.SERVO_NAMES)):
            name = HandController.SERVO_NAMES[idx]
            card = tk.LabelFrame(
                scroll_content, text=f"S{idx + 1} {name}",
                font=("Tahoma", 9, "bold"), bg=self.BG_COLOR, bd=2, relief=tk.GROOVE
            )
            card.pack(fill=tk.X, padx=4, pady=3)

            # row 1: slider and spinbox
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

            # row 2: nudge buttons, numbers move it and strings go to that angle
            r2 = tk.Frame(card, bg=self.BG_COLOR)
            r2.pack(fill=tk.X, padx=4, pady=2)

            nudges = [("-10", -10), ("-5", -5), ("0°", "0"), ("90°", "90"), ("180°", "180"), ("+5", 5), ("+10", 10)]
            for nudge in nudges:
                btn = tk.Button(
                    r2, text=nudge[0], font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED, bd=1, padx=2,
                    command=lambda ch=idx, v=nudge[1]: self._on_nudge_clicked(ch, v)
                )
                btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

            # row 3: trim and invert
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

        # buttons for all servos
        master_box = tk.LabelFrame(scroll_content, text="All", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        master_box.pack(fill=tk.X, padx=4, pady=6)

        m_row = tk.Frame(master_box, bg=self.BG_COLOR)
        m_row.pack(fill=tk.X, padx=4, pady=4)

        tk.Button(
            m_row, text="Open", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._pose_open
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        tk.Button(
            m_row, text="Neutral", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._pose_neutral
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        tk.Button(
            m_row, text="Close", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._pose_close
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # smooth movement
        sm_row = tk.Frame(master_box, bg=self.BG_COLOR)
        sm_row.pack(fill=tk.X, padx=4, pady=(2, 4))
        tk.Checkbutton(
            sm_row, text="Smooth", variable=self.smooth_move_var,
            bg=self.BG_COLOR, font=("Tahoma", 8)
        ).pack(side=tk.LEFT)
        tk.Label(sm_row, text="ms:", bg=self.BG_COLOR, font=("Tahoma", 8)).pack(side=tk.LEFT, padx=(6, 2))
        tk.Spinbox(sm_row, from_=50, to=3000, increment=50, width=5, textvariable=self.smooth_dur_var,
                   font=("Tahoma", 8)).pack(side=tk.LEFT)

    #==========================================================================
    # middle: the hand view

    # 3d opengl model of the hand, the 2d drawing is used if 3d doesnt work
    def _build_hand_canvas(self, parent):
        title_bar = tk.Frame(parent, bg=self.ACCENT_COLOR, bd=1, relief=tk.RAISED)
        title_bar.pack(fill=tk.X, padx=2, pady=2)
        tk.Label(
            title_bar, text="HAND", fg="white", bg=self.ACCENT_COLOR,
            font=("Tahoma", 10, "bold"), anchor="w", padx=6
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._view_title_bar = title_bar

        self.gl_view = None
        self.view_mode_var = tk.StringVar(value="3D")
        self.hand_view_host = tk.Frame(parent, bg=self.CANVAS_BG, bd=2, relief=tk.SUNKEN)
        self.hand_view_host.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.canvas = tk.Canvas(self.hand_view_host, bg=self.CANVAS_BG, highlightthickness=0)
        self.canvas.bind("<Configure>", self._canvas_resized)

        reason = hand_model.opengl_available()
        if not reason:
            try:
                from hand_model.gl_view import HandGLView
                self.gl_view = HandGLView(self.hand_view_host, width=380, height=480)
                self.gl_view.set_angles(self.ctrl.current_angles, immediate=True)
            except Exception as exc:
                # driver or context problem
                reason = f"{type(exc).__name__}: {exc}"
                self.gl_view = None
        self.gl_unavailable_reason = reason

        # view buttons
        toolbar = tk.Frame(parent, bg=self.BG_COLOR)
        toolbar.pack(fill=tk.X, padx=4, pady=(0, 2))
        if self.gl_view is not None:
            tk.Label(toolbar, text="View:", font=("Tahoma", 8), bg=self.BG_COLOR).pack(side=tk.LEFT)
            for name in ("Iso", "Back", "Palm", "Side", "Top"):
                tk.Button(toolbar, text=name, font=("Tahoma", 8), padx=4, pady=0,
                          command=lambda n=name: self.gl_view.set_view(n)).pack(side=tk.LEFT, padx=1)
            for mode in ("2D", "3D"):
                tk.Radiobutton(
                    self._view_title_bar, text=mode, value=mode, variable=self.view_mode_var,
                    command=self._show_hand_view, fg="white", bg=self.ACCENT_COLOR,
                    selectcolor=self.ACCENT_COLOR, activebackground=self.ACCENT_COLOR,
                    font=("Tahoma", 8, "bold")
                ).pack(side=tk.RIGHT)
            hint = "Drag orbit · Right-drag pan · Wheel zoom · Double-click reset"
        else:
            self.view_mode_var.set("2D")
            hint = "3D unavailable: pip install PyOpenGL pyopengltk numpy"
            if reason:
                print(f"[HANDMOVE] 3D view disabled: {reason}")

        legend_frame = tk.Frame(parent, bg=self.BG_COLOR)
        legend_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        tk.Label(
            legend_frame, text=hint, font=("Tahoma", 8, "italic"), bg=self.BG_COLOR, fg="#555555"
        ).pack(side=tk.LEFT, padx=4)
        self._show_hand_view()

    def _canvas_resized(self, event):
        self._render_hand_canvas()

    # switches between the 3d view and the 2d drawing
    def _show_hand_view(self):
        use_3d = self.gl_view is not None and self.view_mode_var.get() == "3D"
        if use_3d:
            self.canvas.pack_forget()
            self.gl_view.pack(fill=tk.BOTH, expand=True)
            self.gl_view.set_angles(self.ctrl.current_angles, immediate=True)
        else:
            if self.gl_view is not None:
                self.gl_view.pack_forget()
            self.canvas.pack(fill=tk.BOTH, expand=True)
            self.root.after_idle(self._render_hand_canvas)

    # colours the finger in the 3d view for a short time when its control is used
    def _highlight_channel(self, ch):
        if self.gl_view is None:
            return
        self.gl_view.highlight_channel = ch
        if getattr(self, "_highlight_job", None):
            self.root.after_cancel(self._highlight_job)

        def clear():
            self._highlight_job = None
            if self.gl_view is not None:
                self.gl_view.highlight_channel = None
                self.gl_view.request_redraw()

        self._highlight_job = self.root.after(700, clear)

    # draws the hand with the current angles (3d view or the 2d drawing)
    def _render_hand_canvas(self):
        if self.gl_view is not None and self.view_mode_var.get() == "3D":
            self.gl_view.set_angles(self.ctrl.current_angles)
            return
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 50 or h < 50:
            w = 380
            h = 500

        # grid in the backround
        grid_step = 25
        for x in range(0, w, grid_step):
            self.canvas.create_line(x, 0, x, h, fill="#232C33", width=1)
        for y in range(0, h, grid_step):
            self.canvas.create_line(0, y, w, y, fill="#232C33", width=1)

        angles = self.ctrl.current_angles
        wrist_angle = angles[5]  # 0 to 180, 90 is straight

        # middle of the palm base
        cx = w / 2.0
        cy = h * 0.72

        # the whole hand turns a bit with the wrist
        # 90 = 0 rad, 0 = -35 deg, 180 = +35 deg
        wrist_rot_rad = math.radians((wrist_angle - 90) * 0.4)

        # turns a point around (cx, cy)
        def transform(px, py):
            dx = px - cx
            dy = py - cy
            rx = dx * math.cos(wrist_rot_rad) - dy * math.sin(wrist_rot_rad)
            ry = dx * math.sin(wrist_rot_rad) + dy * math.cos(wrist_rot_rad)
            return cx + rx, cy + ry

        # 1. wrist base
        base_w = 90
        base_h = 45
        b_p1 = transform(cx - base_w / 2, cy + 30)
        b_p2 = transform(cx + base_w / 2, cy + 30)
        b_p3 = transform(cx + base_w / 2, cy + 30 + base_h)
        b_p4 = transform(cx - base_w / 2, cy + 30 + base_h)
        self.canvas.create_polygon([b_p1, b_p2, b_p3, b_p4], fill="#1E2A38", outline="#4A6572", width=2)
        wrist_txt = transform(cx, cy + 50)
        self.canvas.create_text(
            wrist_txt[0], wrist_txt[1], text=f"Wrist {wrist_angle}°",
            fill="#E5C07B", font=("Tahoma", 8, "bold")
        )

        # 2. palm
        palm_w = 110
        palm_h = 80
        p_bl = transform(cx - palm_w / 2, cy + 15)
        p_br = transform(cx + palm_w / 2, cy + 15)
        p_tr = transform(cx + palm_w / 2 - 10, cy - palm_h)
        p_tl = transform(cx - palm_w / 2 - 10, cy - palm_h + 15)
        self.canvas.create_polygon([p_bl, p_br, p_tr, p_tl], fill=self.PALM_COLOR, outline="#61AFEF", width=2)

        palm_txt = transform(cx, cy - 25)
        self.canvas.create_text(
            palm_txt[0], palm_txt[1], text="uHand UNO", fill="#ABB2BF", font=("Tahoma", 9, "bold")
        )

        # 3. the 5 fingers
        # (channel, name, root x, root y, start angle, segment lenghts)
        finger_configs = [
            (0, "Thumb", cx - 48, cy - 10, -65, [28, 24, 20]),
            (1, "Index", cx - 35, cy - palm_h + 10, -15, [36, 26, 20]),
            (2, "Middle", cx - 10, cy - palm_h + 5, -3, [40, 30, 22]),
            (3, "Ring", cx + 15, cy - palm_h + 10, 8, [36, 26, 20]),
            (4, "Pinky", cx + 38, cy - palm_h + 20, 22, [28, 22, 16]),
        ]

        for finger in finger_configs:
            ch = finger[0]
            fname = finger[1]
            rx = finger[2]
            ry = finger[3]
            base_ang = finger[4]
            seg_lens = finger[5]
            angle = angles[ch]  # 0 to 180
            # 180 = finger straight, 0 = curled (each joint bends about 50 deg)
            curl_factor = (180.0 - angle) / 180.0
            joint_curl_deg = curl_factor * 52.0

            curr_x = rx
            curr_y = ry
            curr_ang_deg = -90 + base_ang  # -90 is straight up

            t_root = transform(curr_x, curr_y)
            self.canvas.create_oval(
                t_root[0] - 4, t_root[1] - 4, t_root[0] + 4, t_root[1] + 4,
                fill=self.JOINT_COLOR, outline="#FFFFFF", width=1
            )

            prev_pt = t_root
            for seg_idx in range(len(seg_lens)):
                seg_len = seg_lens[seg_idx]
                # bend this segment
                curr_ang_deg += joint_curl_deg
                rad = math.radians(curr_ang_deg)
                curr_x += seg_len * math.cos(rad)
                curr_y += seg_len * math.sin(rad)

                t_next = transform(curr_x, curr_y)

                thickness = 6 - seg_idx
                self.canvas.create_line(
                    prev_pt[0], prev_pt[1], t_next[0], t_next[1],
                    fill=self.BONE_COLOR, width=thickness, capstyle=tk.ROUND
                )

                # joint
                self.canvas.create_oval(
                    t_next[0] - 3, t_next[1] - 3, t_next[0] + 3, t_next[1] + 3,
                    fill=self.JOINT_COLOR, outline="#333333", width=1
                )
                prev_pt = t_next

            # name and angle at the finger tip
            self.canvas.create_text(
                prev_pt[0], prev_pt[1] - 12,
                text=f"{fname[:3]}:{angle}°", fill="#98C379", font=("Tahoma", 7, "bold")
            )

    #==========================================================================
    # right side tabs

    def _build_notebook_tabs(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # tab 1 poses
        tab_presets = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_presets, text=" Poses ")
        self._build_tab_presets(tab_presets)

        # tab 2 sequence
        tab_seq = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_seq, text=" Sequence ")
        self._build_tab_sequencer(tab_seq)

        # tab 3 buzzer and rgb led
        tab_periph = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_periph, text=" Peripherals ")
        self._build_tab_peripherals(tab_periph)

        # tab 4 calibration
        tab_calib = tk.Frame(notebook, bg=self.BG_COLOR)
        notebook.add(tab_calib, text=" Calibration ")
        self._build_tab_calibration(tab_calib)

    # grid of buttons, one for each preset pose
    def _build_tab_presets(self, parent):
        c = tk.Canvas(parent, bg=self.BG_COLOR, highlightthickness=0)
        sb = tk.Scrollbar(parent, orient=tk.VERTICAL, command=c.yview)
        grid_frame = tk.Frame(c, bg=self.BG_COLOR)

        def update_scroll(event):
            c.configure(scrollregion=c.bbox("all"))

        grid_frame.bind("<Configure>", update_scroll)
        c.create_window((0, 0), window=grid_frame, anchor="nw")
        c.configure(yscrollcommand=sb.set)

        c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=2)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        cols = 2
        idx = 0
        for name in gestures.PRESET_POSES:
            pose = gestures.PRESET_POSES[name]
            btn = tk.Button(
                grid_frame, text=name, font=("Tahoma", 8, "bold"),
                bg="#D4D0C8", relief=tk.RAISED, bd=2, width=22, height=2,
                command=lambda p=pose: self._apply_pose(list(p))
            )
            btn.grid(row=idx // cols, column=idx % cols, padx=4, pady=3, sticky="nsew")
            idx = idx + 1

    # recording frames, the list of frames and playback
    def _build_tab_sequencer(self, parent):
        ctrl_frame = tk.Frame(parent, bg=self.BG_COLOR)
        ctrl_frame.pack(fill=tk.X, padx=4, pady=4)

        tk.Button(
            ctrl_frame, text="+ Capture", font=("Tahoma", 8, "bold"),
            bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._capture_frame
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            ctrl_frame, text="Delete", font=("Tahoma", 8),
            bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._delete_frame
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            ctrl_frame, text="Clear", font=("Tahoma", 8),
            bg="#D4D0C8", relief=tk.RAISED, bd=2, command=self._clear_frames
        ).pack(side=tk.LEFT, padx=2)

        # list of frames
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

        # playback
        play_frame = tk.LabelFrame(parent, text="Playback", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        play_frame.pack(fill=tk.X, padx=4, pady=4)

        p1 = tk.Frame(play_frame, bg=self.BG_COLOR)
        p1.pack(fill=tk.X, padx=4, pady=2)

        self.btn_play_seq = tk.Button(
            p1, text="Play", font=("Tahoma", 9, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=8, command=self._play_custom_sequence
        )
        self.btn_play_seq.pack(side=tk.LEFT, padx=2)

        self.btn_stop_seq = tk.Button(
            p1, text="Stop", font=("Tahoma", 9), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=6, command=self.ctrl.stop_sequence
        )
        self.btn_stop_seq.pack(side=tk.LEFT, padx=2)

        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(p1, text="Loop", variable=self.loop_var, bg=self.BG_COLOR,
                       font=("Tahoma", 8)).pack(side=tk.LEFT, padx=4)

        tk.Label(p1, text="Speed:", bg=self.BG_COLOR, font=("Tahoma", 8)).pack(side=tk.LEFT, padx=(6, 2))
        self.speed_var = tk.DoubleVar(value=1.0)
        tk.Spinbox(p1, from_=0.25, to=3.0, increment=0.25, width=4, textvariable=self.speed_var,
                   font=("Tahoma", 8)).pack(side=tk.LEFT)

        # built in sequences
        p2 = tk.Frame(play_frame, bg=self.BG_COLOR)
        p2.pack(fill=tk.X, padx=4, pady=4)
        tk.Label(p2, text="Presets:", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=2)

        for sname in ["Wave", "Counting 1-5", "Finger Dance / Strum", "Grab & Release"]:
            btn = tk.Button(
                p2, text=sname, font=("Tahoma", 7), bg="#D4D0C8", relief=tk.RAISED, bd=1,
                command=lambda n=sname: self._load_preset_sequence(n)
            )
            btn.pack(side=tk.LEFT, padx=2)

    # buzzer and rgb led on the shield
    def _build_tab_peripherals(self, parent):
        rgb_box = tk.LabelFrame(parent, text="RGB LED", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        rgb_box.pack(fill=tk.X, padx=4, pady=4)

        # colour buttons
        pal_frame = tk.Frame(rgb_box, bg=self.BG_COLOR)
        pal_frame.pack(fill=tk.X, padx=4, pady=2)

        # (name, rgb, button colour, text colour)
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

        for col in colors:
            btn = tk.Button(
                pal_frame, text=col[0], bg=col[2], fg=col[3], font=("Tahoma", 7, "bold"),
                width=6, relief=tk.RAISED, bd=2,
                command=lambda c=col[1]: self._apply_rgb(c[0], c[1], c[2])
            )
            btn.pack(side=tk.LEFT, expand=True, padx=1)

        # r g b sliders
        sl_frame = tk.Frame(rgb_box, bg=self.BG_COLOR)
        sl_frame.pack(fill=tk.X, padx=4, pady=4)

        self.r_var = tk.IntVar(value=0)
        self.g_var = tk.IntVar(value=0)
        self.b_var = tk.IntVar(value=0)

        for item in [("R", self.r_var), ("G", self.g_var), ("B", self.b_var)]:
            tk.Label(sl_frame, text=item[0] + ":", font=("Tahoma", 8, "bold"),
                     bg=self.BG_COLOR).pack(side=tk.LEFT, padx=(4, 1))
            tk.Scale(
                sl_frame, from_=0, to=255, orient=tk.HORIZONTAL, variable=item[1],
                bg=self.BG_COLOR, highlightthickness=0, length=70,
                command=self._rgb_slider_moved
            ).pack(side=tk.LEFT, padx=2)

        self.swatch = tk.Canvas(sl_frame, width=32, height=20, bg="#000000", bd=2, relief=tk.SUNKEN)
        self.swatch.pack(side=tk.LEFT, padx=6)

        tk.Button(
            sl_frame, text="Send", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._send_rgb_clicked
        ).pack(side=tk.LEFT, padx=2)

        # buzzer
        buz_box = tk.LabelFrame(parent, text="Buzzer", font=("Tahoma", 9, "bold"), bg=self.BG_COLOR)
        buz_box.pack(fill=tk.X, padx=4, pady=6)

        b_row = tk.Frame(buz_box, bg=self.BG_COLOR)
        b_row.pack(fill=tk.X, padx=4, pady=4)

        tk.Label(b_row, text="Hz:", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=2)
        self.buz_freq_var = tk.IntVar(value=1000)
        tk.Spinbox(b_row, from_=100, to=5000, increment=50, width=6, textvariable=self.buz_freq_var,
                   font=("Tahoma", 9)).pack(side=tk.LEFT, padx=2)

        tk.Label(b_row, text="ms:", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=(8, 2))
        self.buz_dur_var = tk.IntVar(value=200)
        tk.Spinbox(b_row, from_=50, to=3000, increment=50, width=6, textvariable=self.buz_dur_var,
                   font=("Tahoma", 9)).pack(side=tk.LEFT, padx=2)

        tk.Button(
            b_row, text="Beep", font=("Tahoma", 9, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, padx=8,
            command=self._beep_clicked
        ).pack(side=tk.LEFT, padx=8)

        # fixed tones
        c_row = tk.Frame(buz_box, bg=self.BG_COLOR)
        c_row.pack(fill=tk.X, padx=4, pady=(0, 4))
        for tone in [("440", 440), ("880", 880), ("1760", 1760), ("2500", 2500)]:
            tk.Button(
                c_row, text=tone[0], font=("Tahoma", 7), bg="#D4D0C8", relief=tk.RAISED, bd=1,
                command=lambda f=tone[1]: self.ctrl.set_buzzer(f, 150)
            ).pack(side=tk.LEFT, expand=True, padx=1)

    def _rgb_slider_moved(self, value):
        self._update_rgb_swatch()

    def _send_rgb_clicked(self):
        self._apply_rgb(self.r_var.get(), self.g_var.get(), self.b_var.get())

    def _beep_clicked(self):
        self.ctrl.set_buzzer(self.buz_freq_var.get(), self.buz_dur_var.get())

    # trims, limits and invert for every servo
    def _build_tab_calibration(self, parent):
        box = tk.Frame(parent, bg=self.BG_COLOR)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # header row
        headers = ["Servo", "Trim", "Invert", "Min", "Max"]
        for col_idx in range(len(headers)):
            tk.Label(box, text=headers[col_idx], font=("Tahoma", 8, "bold"), bg="#D4D0C8", bd=1,
                     relief=tk.GROOVE).grid(row=0, column=col_idx, sticky="ew", padx=1, pady=2)

        self.cal_min_vars = []
        self.cal_max_vars = []

        for ch in range(6):
            name = HandController.SERVO_NAMES[ch]
            tk.Label(box, text=f"S{ch + 1} {name}", font=("Tahoma", 8), bg=self.BG_COLOR).grid(
                row=ch + 1, column=0, sticky="w", padx=2)

            # trim
            spin_t = tk.Spinbox(
                box, from_=-45, to=45, width=5, font=("Tahoma", 8),
                textvariable=self.trim_vars[ch],
                command=lambda c=ch: self._on_trim_changed(c)
            )
            spin_t.grid(row=ch + 1, column=1, padx=2, pady=1)

            # invert
            chk_i = tk.Checkbutton(
                box, variable=self.invert_vars[ch], bg=self.BG_COLOR,
                command=lambda c=ch: self._on_invert_toggled(c)
            )
            chk_i.grid(row=ch + 1, column=2, padx=2, pady=1)

            # min limit
            min_v = tk.IntVar(value=self.ctrl.min_limits[ch])
            self.cal_min_vars.append(min_v)
            spin_min = tk.Spinbox(
                box, from_=0, to=180, width=5, font=("Tahoma", 8), textvariable=min_v,
                command=lambda c=ch: self._on_limit_changed(c)
            )
            spin_min.grid(row=ch + 1, column=3, padx=2, pady=1)

            # max limit
            max_v = tk.IntVar(value=self.ctrl.max_limits[ch])
            self.cal_max_vars.append(max_v)
            spin_max = tk.Spinbox(
                box, from_=0, to=180, width=5, font=("Tahoma", 8), textvariable=max_v,
                command=lambda c=ch: self._on_limit_changed(c)
            )
            spin_max.grid(row=ch + 1, column=4, padx=2, pady=1)

        b_frame = tk.Frame(parent, bg=self.BG_COLOR)
        b_frame.pack(fill=tk.X, padx=4, pady=6)
        tk.Button(b_frame, text="Save", font=("Tahoma", 8, "bold"), bg="#D4D0C8", relief=tk.RAISED, bd=2,
                  command=self._save_calibration).pack(side=tk.LEFT, padx=2)
        tk.Button(b_frame, text="Load", font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED, bd=2,
                  command=self._load_calibration).pack(side=tk.LEFT, padx=2)
        tk.Button(b_frame, text="Reset", font=("Tahoma", 8), bg="#D4D0C8", relief=tk.RAISED, bd=2,
                  command=self._reset_calibration).pack(side=tk.LEFT, padx=2)

    #==========================================================================
    # console at the bottom (shows packets and can send raw hex)

    def _build_bottom_packet_console(self):
        panel = tk.LabelFrame(
            self.root, text="Console",
            font=("Tahoma", 9, "bold"), bg=self.BG_COLOR, bd=2, relief=tk.GROOVE
        )
        panel.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=2)

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

        # colours for each kind of message
        self.console_txt.tag_config("TX", foreground="#61AFEF")
        self.console_txt.tag_config("RX", foreground="#98C379")
        self.console_txt.tag_config("ERR", foreground="#E06C75")
        self.console_txt.tag_config("SYS", foreground="#E5C07B")

        # hex input
        inj_bar = tk.Frame(panel, bg=self.BG_COLOR)
        inj_bar.pack(fill=tk.X, padx=4, pady=3)

        tk.Label(inj_bar, text="Hex:", font=("Tahoma", 8, "bold"), bg=self.BG_COLOR).pack(side=tk.LEFT, padx=2)
        self.hex_input_var = tk.StringVar(value="AA 77 01 06 5A 5A 5A 5A 5A 5A DC")
        self.hex_entry = tk.Entry(inj_bar, textvariable=self.hex_input_var, font=("Courier New", 9), width=42)
        self.hex_entry.pack(side=tk.LEFT, padx=2)
        self.hex_entry.bind("<Return>", self._hex_enter_pressed)

        self.hex_send_button = tk.Button(
            inj_bar, text="Send", font=("Tahoma", 8, "bold"), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._on_send_hex_clicked
        )
        self.hex_send_button.pack(side=tk.LEFT, padx=2)

        tk.Button(
            inj_bar, text="Clear", font=("Tahoma", 8), bg="#D4D0C8",
            relief=tk.RAISED, bd=2, command=self._clear_console
        ).pack(side=tk.LEFT, padx=6)

        tk.Checkbutton(
            inj_bar, text="Auto-Scroll", variable=self.auto_scroll_var,
            bg=self.BG_COLOR, font=("Tahoma", 8)
        ).pack(side=tk.LEFT, padx=2)

    def _hex_enter_pressed(self, event):
        self._on_send_hex_clicked()

    def _clear_console(self):
        self.console_txt.delete("1.0", tk.END)

    def _build_status_bar(self):
        self.status_bar = tk.Label(
            self.root, text="Ready",
            bd=1, relief=tk.SUNKEN, anchor=tk.W, font=("Tahoma", 8), bg="#D4D0C8"
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    #==========================================================================
    # button handlers

    # connects to the saved hiwonder ble module (the default)
    def _auto_connect(self):
        if self.transport_var.get() == "Bluetooth LE":
            self._on_connect_clicked(show_error=False)
            return
        self.ctrl.port = self.port_var.get()
        try:
            self.ctrl.baudrate = int(self.baud_var.get())
        except ValueError:
            self.ctrl.baudrate = 9600

        if not self.ctrl.port:
            self.status_bar.config(text="Disconnected: select a port")
            return
        self._connect_in_background(show_error=False)

    # shows the ble settings, or the serial ones if serial is picked
    def _on_transport_changed(self, event=None):
        is_ble = self.transport_var.get() == "Bluetooth LE"
        if is_ble:
            next_transport = "ble"
        else:
            next_transport = "serial"
        changed = self.ctrl.transport != next_transport
        if changed and self.ctrl.is_connected():
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
        if changed:
            if is_ble:
                self.ctrl.log("SYS", "Transport: BLE")
            else:
                self.ctrl.log("SYS", "Transport: serial")
        # ble has no angle readback and no raw hex
        if is_ble:
            new_state = tk.DISABLED
        else:
            new_state = tk.NORMAL
        if hasattr(self, "btn_query"):
            self.btn_query.config(state=new_state)
        if hasattr(self, "hex_send_button"):
            self.hex_entry.config(state=new_state)
            self.hex_send_button.config(state=new_state)

    # starts connecting without freezing tk while ble scans
    def _on_connect_clicked(self, show_error=True):
        if self.transport_var.get() == "Bluetooth LE":
            self.ctrl.transport = "ble"
        else:
            self.ctrl.transport = "serial"
        if self.ctrl.transport == "ble":
            name, address = parse_ble_target(self.ble_target_var.get())
            self.ctrl.ble_name = name
            self.ctrl.ble_address = address
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

    def _connect_in_background(self, show_error):
        self.btn_connect.config(state=tk.DISABLED)
        self.transport_combo.config(state=tk.DISABLED)
        self.ble_target_combo.config(state=tk.DISABLED)
        self.port_combo.config(state=tk.DISABLED)
        self.btn_refresh_ble.config(state=tk.DISABLED)
        self.btn_refresh_serial.config(state=tk.DISABLED)
        if self.ctrl.transport == "ble":
            target = self.ctrl.ble_name
        else:
            target = self.ctrl.port
        if not target:
            target = "uHand"
        self.status_bar.config(text=f"Connecting to {target}…")

        def worker():
            success, msg = self.ctrl.connect()
            if not success:
                def enable_button():
                    self.btn_connect.config(state=tk.NORMAL)

                def show_warning():
                    messagebox.showwarning("Connection Failed", msg)

                self.root.after(0, enable_button)
                if show_error:
                    self.root.after(0, show_warning)

        threading.Thread(target=worker, name="uHand-connect", daemon=True).start()

    def _on_disconnect_clicked(self):
        self.ctrl.disconnect()

    def _on_sim_toggled(self):
        was_connected = self.ctrl.is_connected()
        self.ctrl.simulation_mode = self.sim_var.get()
        if was_connected or self.ctrl.is_connected():
            self.ctrl.disconnect()
            self._connect_in_background(show_error=False)

    def _on_protocol_changed(self, event=None):
        val = self.proto_var.get()
        for p in ProtocolType:
            if p.value == val:
                self.ctrl.protocol = p
                self.ctrl.log("SYS", f"Switched serial protocol to {p.value}")
                break

    # emergency stop: neutral pose, red led and a beep
    def _on_estop_clicked(self):
        self.ctrl.stop_sequence()
        self._apply_pose([90, 90, 90, 90, 90, 90], force=True)
        self.ctrl.set_rgb(255, 0, 0)
        self.ctrl.set_buzzer(2000, 300)

    # moves the servo smoothly on a thread so the gui doesnt freeze
    def _start_smooth_move(self, angles):
        def move():
            self.ctrl.move_smooth(angles, duration_ms=self.smooth_dur_var.get())

        threading.Thread(target=move, daemon=True).start()

    def _on_slider_moved(self, ch, val):
        angle = int(float(val))
        angles = list(self.ctrl.current_angles)
        angles[ch] = angle

        if self.smooth_move_var.get():
            self._start_smooth_move(angles)
        elif self.ctrl.transport == "ble" and not self.ctrl.simulation_mode:
            self.ctrl.set_servo_angle(ch, angle)
        else:
            self.ctrl.send_angles(angles)
        self._highlight_channel(ch)
        self._render_hand_canvas()

    def _on_spin_changed(self, ch):
        val = self.channel_vars[ch].get()
        self._on_slider_moved(ch, str(val))

    # nudge button: a number moves it by that much, a string goes to that angle
    def _on_nudge_clicked(self, ch, val):
        if isinstance(val, str):
            target = int(val)
        else:
            target = self.ctrl.current_angles[ch] + val
        if target > 180:
            target = 180
        if target < 0:
            target = 0
        self.channel_vars[ch].set(target)
        self._on_slider_moved(ch, str(target))

    def _on_invert_toggled(self, ch):
        self.ctrl.inverted[ch] = self.invert_vars[ch].get()
        # send the angle again so the hardware updates
        self.ctrl.send_angles(self.ctrl.current_angles, force=True)

    def _on_trim_changed(self, ch):
        self.ctrl.trims[ch] = self.trim_vars[ch].get()
        self.ctrl.send_angles(self.ctrl.current_angles, force=True)

    def _on_limit_changed(self, ch):
        self.ctrl.min_limits[ch] = self.cal_min_vars[ch].get()
        self.ctrl.max_limits[ch] = self.cal_max_vars[ch].get()

    # puts a 6 angle pose on the sliders, the drawing and the hand
    def _apply_pose(self, angles, force=False):
        for i in range(len(angles)):
            self.channel_vars[i].set(angles[i])
        if self.smooth_move_var.get() and not force:
            self._start_smooth_move(angles)
        else:
            self.ctrl.send_angles(angles, force=force)
        self._render_hand_canvas()

    def _apply_rgb(self, r, g, b):
        self.r_var.set(r)
        self.g_var.set(g)
        self.b_var.set(b)
        self._update_rgb_swatch()
        self.ctrl.set_rgb(r, g, b)

    def _update_rgb_swatch(self):
        hex_c = f"#{self.r_var.get():02x}{self.g_var.get():02x}{self.b_var.get():02x}"
        self.swatch.configure(bg=hex_c)

    def _on_send_hex_clicked(self):
        hex_str = self.hex_input_var.get()
        self.ctrl.send_raw_hex(hex_str)

    #==========================================================================
    # sequence buttons

    def _show_frame(self, number, pose, dur):
        self.seq_listbox.insert(tk.END, f"#{number:2d} | Pose: {pose} | {dur}ms")

    # adds the current pose to the list
    def _capture_frame(self):
        pose = tuple(self.ctrl.current_angles)
        dur = self.smooth_dur_var.get()
        self.sequence_frames.append((pose, dur))
        idx = len(self.sequence_frames)
        self._show_frame(idx, pose, dur)

    def _delete_frame(self):
        sel = self.seq_listbox.curselection()
        if sel:
            idx = sel[0]
            self.seq_listbox.delete(idx)
            self.sequence_frames.pop(idx)

    def _clear_frames(self):
        self.seq_listbox.delete(0, tk.END)
        self.sequence_frames.clear()

    def _sequence_done(self):
        self.status_bar.config(text="Sequence done")

    def _play_custom_sequence(self):
        if not self.sequence_frames:
            messagebox.showinfo("Sequencer", "No frames captured.")
            return
        self.ctrl.play_sequence(
            self.sequence_frames,
            loop=self.loop_var.get(),
            speed_factor=self.speed_var.get(),
            on_complete=self._sequence_done
        )

    # loads a built in animation into the list and plays it
    def _load_preset_sequence(self, name):
        preset = gestures.PRESET_SEQUENCES.get(name)
        if preset:
            self._clear_frames()
            self.sequence_frames = list(preset)
            for i in range(len(self.sequence_frames)):
                frame = self.sequence_frames[i]
                self._show_frame(i + 1, frame[0], frame[1])
            self._play_custom_sequence()

    def _save_sequence(self):
        try:
            with open("sequence.json", "w", encoding="utf-8") as f:
                json.dump(self.sequence_frames, f, indent=2)
            messagebox.showinfo("Export", "Saved sequence to sequence.json")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def _load_sequence(self):
        if not os.path.exists("sequence.json"):
            messagebox.showwarning("Load", "sequence.json not found")
            return
        try:
            with open("sequence.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            self._clear_frames()
            self.sequence_frames = []
            for item in data:
                self.sequence_frames.append((tuple(item[0]), item[1]))
            for i in range(len(self.sequence_frames)):
                frame = self.sequence_frames[i]
                self._show_frame(i + 1, frame[0], frame[1])
            messagebox.showinfo("Import", f"Loaded {len(self.sequence_frames)} frames")
        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    def _save_calibration(self):
        self.ctrl.save_calibration("calibration.json")
        messagebox.showinfo("Calibration", "Saved calibration.json")

    def _load_calibration(self):
        if self.ctrl.load_calibration("calibration.json"):
            for i in range(6):
                self.trim_vars[i].set(self.ctrl.trims[i])
                self.invert_vars[i].set(self.ctrl.inverted[i])
                self.cal_min_vars[i].set(self.ctrl.min_limits[i])
                self.cal_max_vars[i].set(self.ctrl.max_limits[i])
            messagebox.showinfo("Calibration", "Loaded calibration.json")
        else:
            messagebox.showwarning("Calibration", "calibration.json not found")

    # back to 0 trim, no invert and full 0-180 range
    def _reset_calibration(self):
        for i in range(6):
            self.trim_vars[i].set(0)
            self.invert_vars[i].set(False)
            self.cal_min_vars[i].set(0)
            self.cal_max_vars[i].set(180)
            self._on_trim_changed(i)
            self._on_invert_toggled(i)
            self._on_limit_changed(i)

    #==========================================================================
    # controller callbacks, they come from other threads so everything
    # goes through root.after

    def _on_controller_log(self, direction, text):
        def update():
            if direction == "TX" or direction == "RX" or direction == "ERR" or direction == "SYS":
                tag = direction
            else:
                tag = "SYS"
            tstamp = time.strftime("%H:%M:%S")
            line = f"[{tstamp}] [{direction:<3}] {text}\n"
            self.console_txt.insert(tk.END, line, tag)
            if self.auto_scroll_var.get():
                self.console_txt.see(tk.END)

        self.root.after(0, update)

    def _on_controller_angles_updated(self, angles):
        def update():
            for i in range(len(angles)):
                self.channel_vars[i].set(angles[i])
            self._render_hand_canvas()

        self.root.after(0, update)

    # lamp colour, status text and buttons
    def _on_controller_connection_changed(self, connected, message):
        def update():
            if connected:
                if self.ctrl.transport == "ble":
                    self.ble_target_var.set(format_ble_target(self.ctrl.ble_name, self.ctrl.ble_address))
                    self.ble_target_combo.configure(values=[self.ble_target_var.get()])
                if self.ctrl.simulation_mode:
                    self._draw_lamp("#FF9900")
                    prefix = "Simulation"
                else:
                    self._draw_lamp("#00FF00")
                    prefix = "Connected"
                self.btn_connect.config(state=tk.DISABLED)
                self.btn_disconnect.config(state=tk.NORMAL)
                self.status_bar.config(text=f"{prefix}: {message}")
            else:
                self._draw_lamp("red")
                self.btn_connect.config(state=tk.NORMAL)
                self.btn_disconnect.config(state=tk.DISABLED)
                self.status_bar.config(text=f"Disconnected: {message}")
            self.transport_combo.config(state="readonly")
            self.ble_target_combo.config(state=tk.NORMAL)
            self.port_combo.config(state=tk.NORMAL)
            self.btn_refresh_ble.config(state=tk.NORMAL)
            self.btn_refresh_serial.config(state=tk.NORMAL)

        self.root.after(0, update)

    # close the ble / serial connection before the window closes
    def _close_application(self):
        try:
            self.ctrl.disconnect()
        finally:
            self.root.destroy()

    def _on_sequence_step(self, step, total):
        def update():
            self.status_bar.config(text=f"Playing {step}/{total}")

        self.root.after(0, update)

    #==========================================================================
    # help windows

    def _show_pinout_help(self):
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
        messagebox.showinfo("Wiring", msg)

    def _show_protocol_help(self):
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
        messagebox.showinfo("Protocol", msg)

    def _show_about(self):
        msg = (
            "uHand UNO Controller\n"
            "Version 1.0\n\n"
            "Control and simulation for the Hiwonder uHand UNO."
        )
        messagebox.showinfo("About", msg)


# starts the tkinter gui
def launch_gui(port=None, baud=None, transport=None):
    root = tk.Tk()
    defaults = load_connection_settings()
    if port is None:
        port = defaults["port"]
    if baud is None:
        baud = defaults["baudrate"]
    app = LegacyHandGUI(root, default_port=port, default_baud=baud)
    if transport == "ble" or transport == "serial":
        app.ctrl.transport = transport
        if transport == "ble":
            app.transport_var.set("Bluetooth LE")
        else:
            app.transport_var.set("Serial UART")
        app._on_transport_changed()
    root.mainloop()


if __name__ == "__main__":
    launch_gui()

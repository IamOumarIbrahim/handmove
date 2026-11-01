#   HANDMOVE - EEG Bridge (panel window)
#        Oumar Ibrahim U22200741

# tk window that sits next to the HANDMOVE gui and uses the same HandController
# sections: Source -> Signal -> Calibrate & Train -> Drive hand (+ UDP)
# the bridge callbacks are checked from the tk thread every 100 ms so we
# never call tk from a worker thread

import collections
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from .bridge import EEGBridge, UDPCommandListener
from .decoder import FingerDecoder, train_from_recording
from .sources import (BRAINFLOW_BOARDS, FINGER_LABELS, BrainFlowSource, LSLSource, ReplaySource,
                      SyntheticSource)

SOURCE_TYPES = ["Synthetic EEG (no hardware)", "Replay recording (.mat / .npz)",
                "OpenBCI / BrainFlow board", "Lab Streaming Layer (LSL)"]
CLASS_SETS = {
    "Rest vs Thumb": [0, 1],
    "Rest vs Index": [0, 2],
    "Rest / Thumb / Index": [0, 1, 2],
    "Thumb vs Pinky": [1, 5],
    "Thumb vs Index": [1, 2],
    "5 fingers (no rest)": [1, 2, 3, 4, 5],
    "Rest + 5 fingers": [0, 1, 2, 3, 4, 5],
}
BG = "#ECE9D8"
TRACE_SECONDS = 4.0


class EEGPanel:
    def __init__(self, master, controller=None, title="EEG Bridge", on_close=None):
        self.ctrl = controller
        self.on_close = on_close
        self.win = tk.Toplevel(master)
        self.win.title(title)
        self.win.geometry("760x860")
        self.win.configure(bg=BG)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.bridge = None
        self.udp = None
        self.last_recording = None
        self._trace = collections.deque()
        self._trace_lock = threading.Lock()
        self._pending_ui = collections.deque()

        self._build_source()
        self._build_signal()
        self._build_calibration()
        self._build_drive()
        self._on_source_type()
        self.win.after(100, self._poll)

    #==========================================================================
    # bulding the ui

    def _frame(self, text):
        f = tk.LabelFrame(self.win, text=text, bg=BG, padx=6, pady=4)
        f.pack(fill=tk.X, padx=8, pady=4)
        return f

    def _build_source(self):
        f = self._frame(" 1. EEG source ")
        self.src_type = tk.StringVar(value=SOURCE_TYPES[0])
        cb = ttk.Combobox(f, textvariable=self.src_type, values=SOURCE_TYPES, state="readonly", width=34)
        cb.grid(row=0, column=0, columnspan=2, sticky="w")
        cb.bind("<<ComboboxSelected>>", self._source_selected)
        tk.Label(f, text="Mains notch:", bg=BG).grid(row=0, column=2, sticky="e")
        self.notch = tk.StringVar(value="50 Hz")
        notch_box = ttk.Combobox(f, textvariable=self.notch, values=["50 Hz", "60 Hz", "Off"],
                                 state="readonly", width=7)
        notch_box.grid(row=0, column=3, sticky="w")

        self.opts = tk.Frame(f, bg=BG)
        self.opts.grid(row=1, column=0, columnspan=4, sticky="we", pady=4)
        # variables for every source type
        self.syn_channels = tk.StringVar(value="8")
        self.replay_path = tk.StringVar()
        self.replay_montage = tk.StringVar(value="8")
        self.replay_speed = tk.StringVar(value="1")
        self.bf_board = tk.StringVar(value=list(BRAINFLOW_BOARDS)[0])
        self.bf_port = tk.StringVar()
        self.lsl_type = tk.StringVar(value="EEG")
        self.lsl_name = tk.StringVar()

        self.btn_connect = tk.Button(f, text="Connect EEG", width=14, command=self._connect)
        self.btn_connect.grid(row=2, column=0, sticky="w")
        self.btn_disconnect = tk.Button(f, text="Disconnect", width=12, command=self._disconnect,
                                        state=tk.DISABLED)
        self.btn_disconnect.grid(row=2, column=1, sticky="w")
        self.src_status = tk.Label(f, text="Not connected", bg=BG, fg="#800000", anchor="w")
        self.src_status.grid(row=2, column=2, columnspan=2, sticky="w")

    def _source_selected(self, event):
        self._on_source_type()

    def _on_source_type(self):
        for w in self.opts.winfo_children():
            w.destroy()
        kind = SOURCE_TYPES.index(self.src_type.get())
        o = self.opts
        if kind == 0:
            tk.Label(o, text="Channels:", bg=BG).pack(side=tk.LEFT)
            ttk.Combobox(o, textvariable=self.syn_channels, values=["8", "16"], width=4,
                         state="readonly").pack(side=tk.LEFT)
            tk.Label(o, text="  Simulated user follows the calibration cues.", bg=BG, fg="#555").pack(side=tk.LEFT)
        elif kind == 1:
            tk.Entry(o, textvariable=self.replay_path, width=48).pack(side=tk.LEFT)
            tk.Button(o, text="Browse...", command=self._browse_replay).pack(side=tk.LEFT, padx=2)
            tk.Label(o, text=" Electrodes:", bg=BG).pack(side=tk.LEFT)
            ttk.Combobox(o, textvariable=self.replay_montage, values=["8", "16", "All"], width=4,
                         state="readonly").pack(side=tk.LEFT)
            tk.Label(o, text=" Speed:", bg=BG).pack(side=tk.LEFT)
            ttk.Combobox(o, textvariable=self.replay_speed, values=["1", "2", "5"], width=3,
                         state="readonly").pack(side=tk.LEFT)
        elif kind == 2:
            ttk.Combobox(o, textvariable=self.bf_board, values=list(BRAINFLOW_BOARDS), width=32,
                         state="readonly").pack(side=tk.LEFT)
            tk.Label(o, text=" Dongle port:", bg=BG).pack(side=tk.LEFT)
            ports = []
            try:
                from connection_settings import list_serial_ports
                found = []
                for p in list_serial_ports():
                    found.append(p["device"])
                ports = found
            except Exception:
                pass
            ttk.Combobox(o, textvariable=self.bf_port, values=ports, width=10).pack(side=tk.LEFT)
        else:
            tk.Label(o, text="Stream type:", bg=BG).pack(side=tk.LEFT)
            tk.Entry(o, textvariable=self.lsl_type, width=8).pack(side=tk.LEFT)
            tk.Label(o, text=" or name:", bg=BG).pack(side=tk.LEFT)
            tk.Entry(o, textvariable=self.lsl_name, width=18).pack(side=tk.LEFT)
            tk.Label(o, text="  (e.g. OpenBCI GUI > Networking > LSL)", bg=BG, fg="#555").pack(side=tk.LEFT)

    def _build_signal(self):
        f = self._frame(" 2. Signal (last 4 s, common-average referenced) ")
        self.trace_canvas = tk.Canvas(f, height=170, bg="#10161A", highlightthickness=0)
        self.trace_canvas.pack(fill=tk.X)
        self.signal_info = tk.Label(f, text="Channel quality: green = 2-60 uV, orange = noisy, red = flat or railed",
                                    bg=BG, fg="#555", anchor="w")
        self.signal_info.pack(fill=tk.X)

    def _build_calibration(self):
        f = self._frame(" 3. Calibrate & train ")
        tk.Label(f, text="Classes:", bg=BG).grid(row=0, column=0, sticky="e")
        self.class_set = tk.StringVar(value="Rest / Thumb / Index")
        class_box = ttk.Combobox(f, textvariable=self.class_set, values=list(CLASS_SETS), width=30,
                                 state="readonly")
        class_box.grid(row=0, column=1, columnspan=3, sticky="w")

        tk.Label(f, text="Trials/class:", bg=BG).grid(row=1, column=0, sticky="e")
        self.trials = tk.IntVar(value=15)
        tk.Spinbox(f, from_=3, to=60, textvariable=self.trials, width=5).grid(row=1, column=1, sticky="w")
        tk.Label(f, text="Cue s:", bg=BG).grid(row=1, column=2, sticky="e")
        self.cue_s = tk.DoubleVar(value=4.0)
        tk.Spinbox(f, from_=2, to=10, increment=0.5, textvariable=self.cue_s, width=5).grid(row=1, column=3, sticky="w")
        tk.Label(f, text="Rest s:", bg=BG).grid(row=1, column=4, sticky="e")
        self.rest_s = tk.DoubleVar(value=2.5)
        tk.Spinbox(f, from_=2, to=10, increment=0.5, textvariable=self.rest_s, width=5).grid(row=1, column=5, sticky="w")

        bf = tk.Frame(f, bg=BG)
        bf.grid(row=2, column=0, columnspan=6, sticky="w", pady=3)
        self.btn_calib = tk.Button(bf, text="Start calibration", command=self._start_calibration)
        self.btn_calib.pack(side=tk.LEFT)
        tk.Button(bf, text="Stop", command=self._stop_calibration).pack(side=tk.LEFT, padx=2)
        self.btn_train = tk.Button(bf, text="Train model", command=self._train_last, state=tk.DISABLED)
        self.btn_train.pack(side=tk.LEFT, padx=2)
        tk.Button(bf, text="Train on labelled file...", command=self._train_file).pack(side=tk.LEFT, padx=2)

        bf2 = tk.Frame(f, bg=BG)
        bf2.grid(row=3, column=0, columnspan=6, sticky="w", pady=2)
        tk.Button(bf2, text="Save recording...", command=self._save_recording).pack(side=tk.LEFT, padx=2)
        tk.Button(bf2, text="Save model...", command=self._save_model).pack(side=tk.LEFT, padx=2)
        tk.Button(bf2, text="Load model...", command=self._load_model).pack(side=tk.LEFT, padx=2)

        self.cue_label = tk.Label(f, text="", font=("Segoe UI", 26, "bold"), bg="#FFFFFF", fg="#0A246A",
                                  height=1, relief=tk.SUNKEN)
        self.cue_label.grid(row=4, column=0, columnspan=6, sticky="we", pady=2)
        self.model_info = tk.Label(f, text="No model loaded", bg=BG, anchor="w")
        self.model_info.grid(row=5, column=0, columnspan=6, sticky="w")
        f.grid_columnconfigure(5, weight=1)

    def _build_drive(self):
        f = self._frame(" 4. Drive the hand ")
        self.btn_drive = tk.Button(f, text="Start driving hand", bg="#C8E6C9", width=18,
                                   command=self._toggle_drive)
        self.btn_drive.grid(row=0, column=0, rowspan=2, padx=(0, 8))

        tk.Label(f, text="Confidence threshold", bg=BG).grid(row=0, column=1, sticky="w")
        self.threshold = tk.DoubleVar(value=0.6)
        tk.Scale(f, from_=0.3, to=0.95, resolution=0.05, orient=tk.HORIZONTAL, variable=self.threshold, bg=BG,
                 length=150, command=self._slider_moved).grid(row=1, column=1)
        tk.Label(f, text="Hold time (s)", bg=BG).grid(row=0, column=2, sticky="w")
        self.dwell = tk.DoubleVar(value=0.4)
        tk.Scale(f, from_=0.0, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, variable=self.dwell, bg=BG,
                 length=150, command=self._slider_moved).grid(row=1, column=2)

        self.udp_on = tk.BooleanVar(value=False)
        self.udp_port = tk.IntVar(value=5005)
        uf = tk.Frame(f, bg=BG)
        uf.grid(row=0, column=3, rowspan=2, sticky="w", padx=8)
        tk.Checkbutton(uf, text="Accept UDP commands", variable=self.udp_on, bg=BG,
                       command=self._toggle_udp).pack(anchor="w")
        pf = tk.Frame(uf, bg=BG)
        pf.pack(anchor="w")
        tk.Label(pf, text="port", bg=BG).pack(side=tk.LEFT)
        tk.Entry(pf, textvariable=self.udp_port, width=6).pack(side=tk.LEFT)

        self.prob_canvas = tk.Canvas(f, height=95, bg="#FFFFFF", highlightthickness=1, highlightbackground="#999")
        self.prob_canvas.grid(row=2, column=0, columnspan=4, sticky="we", pady=4)
        self.drive_info = tk.Label(f, text="", bg=BG, anchor="w", justify=tk.LEFT)
        self.drive_info.grid(row=3, column=0, columnspan=4, sticky="w")
        f.grid_columnconfigure(3, weight=1)

    def _slider_moved(self, value):
        self._apply_mapper_settings()

    #==========================================================================
    # button actions

    def _browse_replay(self):
        p = filedialog.askopenfilename(parent=self.win, title="EEG recording",
                                       filetypes=[("EEG recordings", "*.mat *.npz"), ("All files", "*.*")])
        if p:
            self.replay_path.set(p)

    def _notch_hz(self):
        if self.notch.get() == "50 Hz":
            return 50.0
        elif self.notch.get() == "60 Hz":
            return 60.0
        else:
            return None

    def _make_source(self):
        kind = SOURCE_TYPES.index(self.src_type.get())
        if kind == 0:
            return SyntheticSource(n_channels=int(self.syn_channels.get()))
        if kind == 1:
            if not self.replay_path.get():
                raise ValueError("Choose a .mat (Kaya 2018 5F) or .npz recording first")
            if self.replay_montage.get() == "All":
                montage = None
            else:
                montage = int(self.replay_montage.get())
            return ReplaySource(self.replay_path.get(), montage=montage, speed=float(self.replay_speed.get()))
        if kind == 2:
            board = self.bf_board.get()
            board_id = BRAINFLOW_BOARDS[board]
            # synthetic and wifi boards dont need a port
            if "SYNTHETIC" not in board_id and "WIFI" not in board_id:
                if not self.bf_port.get():
                    raise ValueError("Enter the serial port of the OpenBCI USB dongle (e.g. COM3)")
            return BrainFlowSource(board, serial_port=self.bf_port.get())
        stream_type = self.lsl_type.get()
        if not stream_type:
            stream_type = "EEG"
        return LSLSource(stream_type=stream_type, name=self.lsl_name.get())

    def _connect(self):
        self.src_status.config(text="Connecting...", fg="#806000")
        self.btn_connect.config(state=tk.DISABLED)

        def worker():
            try:
                src = self._make_source()
                bridge = EEGBridge(src, controller=self.ctrl, notch_hz=self._notch_hz())
                bridge.on_chunk = self._on_chunk
                bridge.start()
            except Exception as exc:
                err = exc

                def failed():
                    self._connect_failed(err)

                self._pending_ui.append(failed)
                return

            def connected():
                self._connected(bridge)

            self._pending_ui.append(connected)

        threading.Thread(target=worker, daemon=True).start()

    def _connect_failed(self, exc):
        self.btn_connect.config(state=tk.NORMAL)
        self.src_status.config(text="Connection failed", fg="#C00000")
        hint = ""
        if isinstance(exc, ImportError):
            hint = "\n\nInstall the EEG extras:  python -m pip install -r requirements-eeg.txt"
        messagebox.showerror("EEG source", f"{exc}{hint}", parent=self.win)

    def _connected(self, bridge):
        self.bridge = bridge
        info = bridge.source.info
        with self._trace_lock:
            self._trace = collections.deque(maxlen=int(TRACE_SECONDS * info.fs))
        self.btn_disconnect.config(state=tk.NORMAL)
        self.src_status.config(text=f"{info.name}: {info.n_channels} ch @ {info.fs:g} Hz", fg="#006000")

    def _disconnect(self):
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
        self._set_drive_button(False)
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.src_status.config(text="Not connected", fg="#800000")

    def _require_bridge(self):
        if self.bridge is None:
            messagebox.showinfo("EEG Bridge", "Connect an EEG source first.", parent=self.win)
            return False
        return True

    def _classes(self):
        return CLASS_SETS[self.class_set.get()]

    def _start_calibration(self):
        if not self._require_bridge():
            return
        self.bridge.stop_driving()
        self._set_drive_button(False)
        self.btn_calib.config(state=tk.DISABLED)

        def on_cue(label, i, total):
            if label is None:
                text = "Done"
            elif label == 0:
                text = "Relax"
            else:
                text = f"Imagine: {FINGER_LABELS[label].upper()}"
            # show the trial number while it is running
            if label is not None:
                shown = i + 1
                if shown > total:
                    shown = total
                text = f"{text}   ({shown}/{total})"
            if label == 0 or label is None:
                colour = "#808080"
            else:
                colour = "#0A246A"

            def update_cue():
                self.cue_label.config(text=text, fg=colour)

            self._pending_ui.append(update_cue)

        def on_done(data, labels):
            self.last_recording = (data, labels)
            self._pending_ui.append(self._calibration_done)

        self.bridge.run_calibration(self._classes(), self.trials.get(), self.cue_s.get(), self.rest_s.get(),
                                    on_cue=on_cue, on_done=on_done)

    def _stop_calibration(self):
        if self.bridge:
            self.bridge.stop_calibration()

    def _calibration_done(self):
        self.btn_calib.config(state=tk.NORMAL)
        if self.last_recording is not None and self.last_recording[0].shape[1]:
            self.btn_train.config(state=tk.NORMAL)
            if self.bridge:
                secs = self.last_recording[0].shape[1] / self.bridge.source.info.fs
            else:
                secs = 0
            self.model_info.config(text=f"Recorded {secs:.0f} s of labelled EEG. Press Train model.")

    def _train_last(self):
        if not self._require_bridge() or self.last_recording is None:
            return
        data, labels = self.last_recording

        def job():
            return self.bridge.train(data, labels, self._classes())

        self._train_async(job)

    def _train_file(self):
        if not self._require_bridge():
            return
        p = filedialog.askopenfilename(parent=self.win, title="Labelled EEG recording",
                                       filetypes=[("EEG recordings", "*.mat *.npz")])
        if not p:
            return
        info = self.bridge.source.info

        replay = None
        if isinstance(self.bridge.source, ReplaySource):
            replay = self.bridge.source
        same_file = False
        if replay is not None:
            if os.path.abspath(p) == os.path.abspath(self.replay_path.get()):
                same_file = True

        def job():
            from .sources import kaya_training_labels, load_recording, pick_channels
            data, fs, names, labels = load_recording(p)
            if labels is None:
                raise ValueError("That recording has no labels")
            skip_s = 0.5
            if p.lower().endswith(".mat"):
                # kaya 5F has short cues so we cut from the onset
                labels = kaya_training_labels(labels, fs)
                skip_s = 0.0
            if same_file:
                # train on the first 2/3 and replay the last 1/3 that it never saw
                # so the live accuracy isnt cheating by testing on training data
                cut = int(data.shape[1] * 2 / 3)
                data = data[:, :cut]
                labels = labels[:cut]
                replay.seek(cut)
            if abs(fs - info.fs) > 1e-6:
                raise ValueError(f"File is {fs:g} Hz but the source runs at {info.fs:g} Hz")
            idx = pick_channels(names, info.ch_names)
            if len(idx) != info.n_channels:
                raise ValueError(f"File lacks some of the source channels {info.ch_names}")
            dec = train_from_recording(data[idx], labels, fs, info.ch_names, self._classes(),
                                       notch_hz=self._notch_hz(), skip_s=skip_s)
            self.bridge.set_decoder(dec)
            return dec

        self._train_async(job)

    def _train_async(self, job):
        self.model_info.config(text="Training...")

        def worker():
            try:
                dec = job()

                def show():
                    self._show_model(dec)

                self._pending_ui.append(show)
            except Exception as exc:
                err = exc

                def failed():
                    self.model_info.config(text="Training failed")
                    messagebox.showerror("Train", str(err), parent=self.win)

                self._pending_ui.append(failed)

        threading.Thread(target=worker, daemon=True).start()

    def _show_model(self, dec):
        chance = 1.0 / len(dec.classes)
        if dec.cv_accuracy is None:
            acc = "n/a"
        else:
            acc = f"{dec.cv_accuracy * 100:.0f} %"
        names = ", ".join(dec.class_names())
        self.model_info.config(text=f"Model: {names} | balanced CV accuracy {acc} "
                                    f"(chance {chance * 100:.0f} %) | {len(dec.ch_names)} ch @ {dec.fs:g} Hz")
        self._apply_mapper_settings()

    def _save_recording(self):
        if self.last_recording is None or self.bridge is None:
            messagebox.showinfo("Save", "Run a calibration first.", parent=self.win)
            return
        p = filedialog.asksaveasfilename(parent=self.win, defaultextension=".npz", filetypes=[("NumPy", "*.npz")])
        if p:
            data, labels = self.last_recording
            self.bridge.save_last_recording(p, data, labels)

    def _save_model(self):
        if not self.bridge or not self.bridge.decoder:
            messagebox.showinfo("Save", "Train a model first.", parent=self.win)
            return
        p = filedialog.asksaveasfilename(parent=self.win, defaultextension=".npz",
                                         initialfile="eeg_model.npz", filetypes=[("Model", "*.npz")])
        if p:
            self.bridge.decoder.save(p)

    def _load_model(self):
        if not self._require_bridge():
            return
        p = filedialog.askopenfilename(parent=self.win, filetypes=[("Model", "*.npz")])
        if not p:
            return
        try:
            dec = FingerDecoder.load(p)
            self.bridge.set_decoder(dec)
            self._show_model(dec)
        except Exception as exc:
            messagebox.showerror("Load model", str(exc), parent=self.win)

    def _apply_mapper_settings(self):
        m = None
        if self.bridge:
            m = self.bridge.mapper
        if m is not None:
            m.threshold = self.threshold.get()
            m.dwell_s = self.dwell.get()
        if self.udp is not None:
            self.udp.mapper.threshold = self.threshold.get()
            self.udp.mapper.dwell_s = self.dwell.get()

    def _toggle_drive(self):
        if not self._require_bridge():
            return
        if self.bridge.driving:
            self.bridge.stop_driving()
            self._set_drive_button(False)
            return
        try:
            self._apply_mapper_settings()
            self.bridge.start_driving()
            self._apply_mapper_settings()
            self._set_drive_button(True)
        except Exception as exc:
            messagebox.showinfo("Drive hand", str(exc), parent=self.win)

    # the E-STOP in the main window calls this
    def stop_all_control(self):
        if self.bridge:
            self.bridge.stop_calibration()
            self.bridge.stop_driving()
        self._set_drive_button(False)
        if self.udp:
            self.udp.stop()
            self.udp = None
            self.udp_on.set(False)

    def _set_drive_button(self, on):
        if on:
            self.btn_drive.config(text="Stop driving hand", bg="#FFCDD2")
        else:
            self.btn_drive.config(text="Start driving hand", bg="#C8E6C9")

    def _toggle_udp(self):
        if self.udp_on.get():
            try:
                self.udp = UDPCommandListener(self.ctrl, port=self.udp_port.get())
                self._apply_mapper_settings()
                self.udp.start()
            except Exception as exc:
                self.udp = None
                self.udp_on.set(False)
                messagebox.showerror("UDP", str(exc), parent=self.win)
        elif self.udp:
            self.udp.stop()
            self.udp = None

    #==========================================================================
    # screen updates

    # this one runs on the bridge thread
    def _on_chunk(self, data):
        with self._trace_lock:
            self._trace.extend(data.T)

    def _poll(self):
        try:
            while self._pending_ui:
                func = self._pending_ui.popleft()
                func()
            if self.bridge is not None:
                self._draw_traces()
                self._draw_status()
        finally:
            if self.win.winfo_exists():
                self.win.after(100, self._poll)

    def _draw_traces(self):
        with self._trace_lock:
            if len(self._trace) < 10:
                return
            x = np.array(self._trace).T
        info = self.bridge.source.info
        c = self.trace_canvas
        c.delete("all")
        w = c.winfo_width()
        if w < 200:
            w = 200
        h = int(c["height"])
        n_ch = x.shape[0]
        lane = h / n_ch
        # common average ref just for the display
        x = x - x.mean(axis=0, keepdims=True)
        x = x - x.mean(axis=1, keepdims=True)
        rms = self.bridge.status.channel_rms
        if not rms:
            rms = []
            for row in x:
                rms.append(float(np.std(row)))
        step = x.shape[1] // (w - 60)
        if step < 1:
            step = 1
        xs = np.arange(0, x.shape[1], step)
        maxlen = int(TRACE_SECONDS * info.fs)
        for i in range(n_ch):
            y0 = lane * (i + 0.5)
            if i < len(rms):
                r = rms[i]
            else:
                r = 0.0
            # green is good, orange is noisy, red is flat or railed
            if 2 <= r <= 60:
                color = "#4CAF50"
            elif 0.5 <= r <= 150:
                color = "#FF9800"
            else:
                color = "#F44336"
            c.create_text(4, y0, text=f"{info.ch_names[i][:5]}", fill=color, anchor="w", font=("Consolas", 8))
            sig = x[i, xs]
            # dont let quiet channels get blown up too much
            peak = 30.0
            p98 = np.percentile(np.abs(x), 98)
            if p98 > peak:
                peak = p98
            scale = lane * 0.45 / peak
            px = 50 + (xs + (maxlen - x.shape[1])) * (w - 60) / maxlen
            py = y0 - sig * scale
            pts = []
            for k in range(len(px)):
                pts.append(float(px[k]))
                pts.append(float(py[k]))
            if len(pts) >= 4:
                c.create_line(*pts, fill="#9AD0F5", width=1)

    def _draw_status(self):
        s = self.bridge.status
        c = self.prob_canvas
        c.delete("all")
        dec = self.bridge.decoder
        if dec is not None and s.probs:
            w = c.winfo_width()
            if w < 200:
                w = 200
            n = len(s.probs)
            bw = (w - 20) / n
            thr = self.threshold.get()
            i = 0
            for name in s.probs:
                p = s.probs[name]
                x0 = 10 + i * bw
                top = 75 - p * 65
                # the pose the hand is in gets the dark colur
                if name == s.committed:
                    fill = "#0A246A"
                else:
                    fill = "#7BA7D9"
                c.create_rectangle(x0 + 6, top, x0 + bw - 6, 75, fill=fill, outline="")
                c.create_text(x0 + bw / 2, 86, text=f"{name} {p * 100:.0f}%", font=("Segoe UI", 9))
                i = i + 1
            y = 75 - thr * 65
            c.create_line(10, y, w - 10, y, fill="#C00000", dash=(4, 2))
        else:
            c.create_text(10, 45, anchor="w", fill="#777",
                          text="Train or load a model to see live finger probabilities here.")
        if s.driving:
            pose = s.committed
        else:
            pose = "not driving"
        first_line = f"Prediction: {s.prediction}    Hand pose: {pose}"
        if s.true_label is not None:
            first_line += f"    Recording says: {s.true_label}"
        lines = [first_line]
        if s.last_angles:
            lines.append(f"Last angles sent: {s.last_angles}")
        if s.recording:
            lines.append(f"Recording: {s.recorded_s:.0f} s")
        if s.error:
            lines.append(f"Error: {s.error}")
        self.drive_info.config(text="\n".join(lines))

    def close(self):
        try:
            if self.udp:
                self.udp.stop()
            if self.bridge:
                self.bridge.stop()
        finally:
            self.win.destroy()
            if self.on_close:
                self.on_close()


def open_panel(master, controller):
    return EEGPanel(master, controller=controller)

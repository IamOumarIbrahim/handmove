"""
EEG Bridge panel: a Tk window that sits next to the HANDMOVE GUI and drives
the same HandController.

Sections: Source -> Signal -> Calibrate & Train -> Drive hand (+ UDP input).
All bridge callbacks are polled from the Tk thread every 100 ms, so no Tk call
ever happens on a worker thread.
"""

from __future__ import annotations

import collections
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

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
    def __init__(self, master: tk.Misc, controller=None, title: str = "EEG Bridge", on_close=None):
        self.ctrl = controller
        self.on_close = on_close
        self.win = tk.Toplevel(master)
        self.win.title(title)
        self.win.geometry("760x860")
        self.win.configure(bg=BG)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.bridge: Optional[EEGBridge] = None
        self.udp: Optional[UDPCommandListener] = None
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

    # =================================================================== UI
    def _frame(self, text):
        f = tk.LabelFrame(self.win, text=text, bg=BG, padx=6, pady=4)
        f.pack(fill=tk.X, padx=8, pady=4)
        return f

    def _build_source(self):
        f = self._frame(" 1. EEG source ")
        self.src_type = tk.StringVar(value=SOURCE_TYPES[0])
        cb = ttk.Combobox(f, textvariable=self.src_type, values=SOURCE_TYPES, state="readonly", width=34)
        cb.grid(row=0, column=0, columnspan=2, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_source_type())
        tk.Label(f, text="Mains notch:", bg=BG).grid(row=0, column=2, sticky="e")
        self.notch = tk.StringVar(value="50 Hz")
        ttk.Combobox(f, textvariable=self.notch, values=["50 Hz", "60 Hz", "Off"], state="readonly",
                     width=7).grid(row=0, column=3, sticky="w")

        self.opts = tk.Frame(f, bg=BG)
        self.opts.grid(row=1, column=0, columnspan=4, sticky="we", pady=4)
        # Variables for all source kinds
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
        self.btn_disconnect = tk.Button(f, text="Disconnect", width=12, command=self._disconnect, state=tk.DISABLED)
        self.btn_disconnect.grid(row=2, column=1, sticky="w")
        self.src_status = tk.Label(f, text="Not connected", bg=BG, fg="#800000", anchor="w")
        self.src_status.grid(row=2, column=2, columnspan=2, sticky="w")

    def _on_source_type(self):
        for w in self.opts.winfo_children():
            w.destroy()
        kind = SOURCE_TYPES.index(self.src_type.get())
        o = self.opts
        if kind == 0:
            tk.Label(o, text="Channels:", bg=BG).pack(side=tk.LEFT)
            ttk.Combobox(o, textvariable=self.syn_channels, values=["8", "16"], width=4, state="readonly").pack(side=tk.LEFT)
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
                ports = [p["device"] for p in list_serial_ports()]
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
        ttk.Combobox(f, textvariable=self.class_set, values=list(CLASS_SETS), width=30,
                     state="readonly").grid(row=0, column=1, columnspan=3, sticky="w")
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
        bf = tk.Frame(f, bg=BG)
        bf.grid(row=3, column=0, columnspan=6, sticky="w", pady=2)
        tk.Button(bf, text="Save recording...", command=self._save_recording).pack(side=tk.LEFT, padx=2)
        tk.Button(bf, text="Save model...", command=self._save_model).pack(side=tk.LEFT, padx=2)
        tk.Button(bf, text="Load model...", command=self._load_model).pack(side=tk.LEFT, padx=2)

        self.cue_label = tk.Label(f, text="", font=("Segoe UI", 26, "bold"), bg="#FFFFFF", fg="#0A246A",
                                  height=1, relief=tk.SUNKEN)
        self.cue_label.grid(row=4, column=0, columnspan=6, sticky="we", pady=2)
        self.model_info = tk.Label(f, text="No model loaded", bg=BG, anchor="w")
        self.model_info.grid(row=5, column=0, columnspan=6, sticky="w")
        f.grid_columnconfigure(5, weight=1)

    def _build_drive(self):
        f = self._frame(" 4. Drive the hand ")
        self.btn_drive = tk.Button(f, text="Start driving hand", bg="#C8E6C9", width=18, command=self._toggle_drive)
        self.btn_drive.grid(row=0, column=0, rowspan=2, padx=(0, 8))
        tk.Label(f, text="Confidence threshold", bg=BG).grid(row=0, column=1, sticky="w")
        self.threshold = tk.DoubleVar(value=0.6)
        tk.Scale(f, from_=0.3, to=0.95, resolution=0.05, orient=tk.HORIZONTAL, variable=self.threshold, bg=BG,
                 length=150, command=lambda v: self._apply_mapper_settings()).grid(row=1, column=1)
        tk.Label(f, text="Hold time (s)", bg=BG).grid(row=0, column=2, sticky="w")
        self.dwell = tk.DoubleVar(value=0.4)
        tk.Scale(f, from_=0.0, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, variable=self.dwell, bg=BG,
                 length=150, command=lambda v: self._apply_mapper_settings()).grid(row=1, column=2)
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

    # ============================================================= actions
    def _browse_replay(self):
        p = filedialog.askopenfilename(parent=self.win, title="EEG recording",
                                       filetypes=[("EEG recordings", "*.mat *.npz"), ("All files", "*.*")])
        if p:
            self.replay_path.set(p)

    def _notch_hz(self):
        return {"50 Hz": 50.0, "60 Hz": 60.0}.get(self.notch.get())

    def _make_source(self):
        kind = SOURCE_TYPES.index(self.src_type.get())
        if kind == 0:
            return SyntheticSource(n_channels=int(self.syn_channels.get()))
        if kind == 1:
            if not self.replay_path.get():
                raise ValueError("Choose a .mat (Kaya 2018 5F) or .npz recording first")
            montage = None if self.replay_montage.get() == "All" else int(self.replay_montage.get())
            return ReplaySource(self.replay_path.get(), montage=montage, speed=float(self.replay_speed.get()))
        if kind == 2:
            board = self.bf_board.get()
            if "SYNTHETIC" not in BRAINFLOW_BOARDS[board] and "WIFI" not in BRAINFLOW_BOARDS[board] \
                    and not self.bf_port.get():
                raise ValueError("Enter the serial port of the OpenBCI USB dongle (e.g. COM3)")
            return BrainFlowSource(board, serial_port=self.bf_port.get())
        return LSLSource(stream_type=self.lsl_type.get() or "EEG", name=self.lsl_name.get())

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
                self._pending_ui.append(lambda e=exc: self._connect_failed(e))
                return
            self._pending_ui.append(lambda: self._connected(bridge))

        threading.Thread(target=worker, daemon=True).start()

    def _connect_failed(self, exc):
        self.btn_connect.config(state=tk.NORMAL)
        self.src_status.config(text="Connection failed", fg="#C00000")
        hint = ""
        if isinstance(exc, ImportError):
            hint = "\n\nInstall the EEG extras:  python -m pip install -r requirements-eeg.txt"
        messagebox.showerror("EEG source", f"{exc}{hint}", parent=self.win)

    def _connected(self, bridge: EEGBridge):
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

    def _require_bridge(self) -> bool:
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
            text = "Done" if label is None else ("Relax" if label == 0 else f"Imagine: {FINGER_LABELS[label].upper()}")
            self._pending_ui.append(lambda: self.cue_label.config(
                text=f"{text}   ({min(i + 1, total)}/{total})" if label is not None else text,
                fg="#808080" if label in (0, None) else "#0A246A"))

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
            secs = self.last_recording[0].shape[1] / self.bridge.source.info.fs if self.bridge else 0
            self.model_info.config(text=f"Recorded {secs:.0f} s of labelled EEG. Press Train model.")

    def _train_last(self):
        if not self._require_bridge() or self.last_recording is None:
            return
        data, labels = self.last_recording
        self._train_async(lambda: self.bridge.train(data, labels, self._classes()))

    def _train_file(self):
        if not self._require_bridge():
            return
        p = filedialog.askopenfilename(parent=self.win, title="Labelled EEG recording",
                                       filetypes=[("EEG recordings", "*.mat *.npz")])
        if not p:
            return
        info = self.bridge.source.info

        replay = self.bridge.source if isinstance(self.bridge.source, ReplaySource) else None
        same_file = replay is not None and os.path.abspath(p) == os.path.abspath(self.replay_path.get())

        def job():
            from .sources import kaya_training_labels, load_recording, pick_channels
            data, fs, names, labels = load_recording(p)
            if labels is None:
                raise ValueError("That recording has no labels")
            skip_s = 0.5
            if p.lower().endswith(".mat"):  # Kaya 5F: short cues, epoch from onset
                labels, skip_s = kaya_training_labels(labels, fs), 0.0
            if same_file:
                # Train on the first two thirds and replay the unseen last third,
                # so live accuracy is not inflated by testing on training data.
                cut = int(data.shape[1] * 2 / 3)
                data, labels = data[:, :cut], labels[:cut]
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
                self._pending_ui.append(lambda: self._show_model(dec))
            except Exception as exc:
                self._pending_ui.append(lambda e=exc: (self.model_info.config(text="Training failed"),
                                                      messagebox.showerror("Train", str(e), parent=self.win)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_model(self, dec: FingerDecoder):
        chance = 1.0 / len(dec.classes)
        acc = "n/a" if dec.cv_accuracy is None else f"{dec.cv_accuracy * 100:.0f} %"
        self.model_info.config(text=f"Model: {', '.join(dec.class_names)} | balanced CV accuracy {acc} "
                                    f"(chance {chance * 100:.0f} %) | {len(dec.ch_names)} ch @ {dec.fs:g} Hz")
        self._apply_mapper_settings()

    def _save_recording(self):
        if self.last_recording is None or self.bridge is None:
            messagebox.showinfo("Save", "Run a calibration first.", parent=self.win)
            return
        p = filedialog.asksaveasfilename(parent=self.win, defaultextension=".npz", filetypes=[("NumPy", "*.npz")])
        if p:
            self.bridge.save_last_recording(p, *self.last_recording)

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
        m = self.bridge.mapper if self.bridge else None
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

    def stop_all_control(self):
        """Used by the main window's E-STOP."""
        if self.bridge:
            self.bridge.stop_calibration()
            self.bridge.stop_driving()
        self._set_drive_button(False)
        if self.udp:
            self.udp.stop()
            self.udp = None
            self.udp_on.set(False)

    def _set_drive_button(self, on: bool):
        self.btn_drive.config(text="Stop driving hand" if on else "Start driving hand",
                              bg="#FFCDD2" if on else "#C8E6C9")

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

    # ============================================================ updates
    def _on_chunk(self, data: np.ndarray):  # bridge thread
        with self._trace_lock:
            self._trace.extend(data.T)

    def _poll(self):
        try:
            while self._pending_ui:
                self._pending_ui.popleft()()
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
        w = max(200, c.winfo_width())
        h = int(c["height"])
        n_ch = x.shape[0]
        lane = h / n_ch
        x = x - x.mean(axis=0, keepdims=True)                 # CAR for display
        x = x - x.mean(axis=1, keepdims=True)
        rms = self.bridge.status.channel_rms or [float(np.std(r)) for r in x]
        step = max(1, x.shape[1] // (w - 60))
        xs = np.arange(0, x.shape[1], step)
        maxlen = int(TRACE_SECONDS * info.fs)
        for i in range(n_ch):
            y0 = lane * (i + 0.5)
            r = rms[i] if i < len(rms) else 0.0
            color = "#4CAF50" if 2 <= r <= 60 else ("#FF9800" if 0.5 <= r <= 150 else "#F44336")
            c.create_text(4, y0, text=f"{info.ch_names[i][:5]}", fill=color, anchor="w", font=("Consolas", 8))
            sig = x[i, xs]
            scale = lane * 0.45 / max(30.0, np.percentile(np.abs(x), 98))
            px = 50 + (xs + (maxlen - x.shape[1])) * (w - 60) / maxlen
            pts = np.column_stack([px, y0 - sig * scale]).ravel().tolist()
            if len(pts) >= 4:
                c.create_line(*pts, fill="#9AD0F5", width=1)

    def _draw_status(self):
        s = self.bridge.status
        c = self.prob_canvas
        c.delete("all")
        dec = self.bridge.decoder
        if dec is not None and s.probs:
            w = max(200, c.winfo_width())
            n = len(s.probs)
            bw = (w - 20) / n
            thr = self.threshold.get()
            for i, (name, p) in enumerate(s.probs.items()):
                x0 = 10 + i * bw
                top = 75 - p * 65
                committed = name == s.committed
                c.create_rectangle(x0 + 6, top, x0 + bw - 6, 75,
                                   fill="#0A246A" if committed else "#7BA7D9", outline="")
                c.create_text(x0 + bw / 2, 86, text=f"{name} {p * 100:.0f}%", font=("Segoe UI", 9))
            y = 75 - thr * 65
            c.create_line(10, y, w - 10, y, fill="#C00000", dash=(4, 2))
        else:
            c.create_text(10, 45, anchor="w", fill="#777",
                          text="Train or load a model to see live finger probabilities here.")
        lines = [f"Prediction: {s.prediction}    Hand pose: {s.committed if s.driving else 'not driving'}"]
        if s.true_label is not None:
            lines[0] += f"    Recording says: {s.true_label}"
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


def open_panel(master: tk.Misc, controller) -> EEGPanel:
    return EEGPanel(master, controller=controller)

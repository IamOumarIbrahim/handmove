"""
EEGBridge: the running link between an EEG source and HandController.

    source.read() -> Preprocessor -> RingBuffer -> FingerDecoder -> IntentMapper
                                                                       |
                                                    HandController.send_angles()

It also records labelled data for calibration, runs the cue protocol, and can
accept commands from external BCI software over UDP (see UDPCommandListener).
Everything runs on one background thread; callbacks are invoked from that
thread, so GUI code must marshal them onto its own thread.
"""

from __future__ import annotations

import json
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from .decoder import FingerDecoder, Preprocessor, RingBuffer, train_from_recording
from .mapper import IntentMapper
from .sources import FINGER_LABELS, IGNORE, REST, EEGSource, save_recording

NAME_TO_LABEL = {v: k for k, v in FINGER_LABELS.items()}


@dataclass
class BridgeStatus:
    samples: int = 0
    fs: float = 0.0
    probs: Optional[Dict[str, float]] = None
    prediction: str = "-"
    committed: str = "-"
    true_label: Optional[str] = None
    cue: Optional[str] = None
    driving: bool = False
    recording: bool = False
    recorded_s: float = 0.0
    channel_rms: Optional[List[float]] = None
    last_angles: Optional[List[int]] = None
    error: Optional[str] = None


class EEGBridge:
    def __init__(self, source: EEGSource, controller=None, decoder: Optional[FingerDecoder] = None,
                 mapper: Optional[IntentMapper] = None, predict_hz: float = 8.0, notch_hz: Optional[float] = 50.0):
        self.source = source
        self.controller = controller
        self.predict_hz = predict_hz
        self.notch_hz = notch_hz
        self.decoder: Optional[FingerDecoder] = None
        self.mapper: Optional[IntentMapper] = mapper
        self.status = BridgeStatus(fs=source.info.fs)
        self.on_status: Optional[Callable[[BridgeStatus], None]] = None
        self.on_chunk: Optional[Callable[[np.ndarray], None]] = None

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.driving = False
        self._cue: Optional[int] = None
        self._rec_data: List[np.ndarray] = []
        self._rec_labels: List[np.ndarray] = []
        self.recording = False
        self._last_predict = 0.0
        self._rms_buf = RingBuffer((source.info.n_channels,), int(source.info.fs))
        self._calib_thread: Optional[threading.Thread] = None
        self._calib_stop = threading.Event()
        self.set_decoder(decoder)

    # ----------------------------------------------------------------- setup
    def set_decoder(self, decoder: Optional[FingerDecoder]) -> None:
        with self._lock:
            self.decoder = decoder
            info = self.source.info
            if decoder is not None:
                if len(decoder.ch_names) != info.n_channels:
                    raise ValueError(f"Model expects {len(decoder.ch_names)} channels, source has {info.n_channels}")
                if abs(decoder.fs - info.fs) > 1e-6:
                    raise ValueError(f"Model trained at {decoder.fs} Hz, source runs at {info.fs} Hz")
                self.pre = decoder.make_preprocessor()
                win = int(decoder.window_s * info.fs)
                if self.mapper is None or self.mapper.classes != decoder.classes:
                    self.mapper = IntentMapper(decoder.classes)
            else:
                self.pre = Preprocessor(info.fs, info.n_channels, notch_hz=self.notch_hz)
                win = int(info.fs)
            self.ring = RingBuffer((len(self.pre.bands), info.n_channels), win)

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.source.start()
        self._thread = threading.Thread(target=self._run, name="EEGBridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_calibration()
        self.driving = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.source.stop()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start_driving(self) -> None:
        if self.decoder is None or not self.decoder.trained:
            raise RuntimeError("Train or load a model before driving the hand")
        if self.controller is not None and getattr(self.controller, "is_playing_sequence", False):
            self.controller.stop_sequence()
        start = getattr(self.controller, "current_angles", None) if self.controller is not None else None
        if start is not None:
            self.mapper.reset(start)
        self.driving = True

    def stop_driving(self) -> None:
        self.driving = False

    # -------------------------------------------------------------- recording
    def set_cue(self, label: Optional[int]) -> None:
        """Current instruction shown to the user; it labels recorded samples."""
        self._cue = label
        if hasattr(self.source, "set_intent"):
            # The synthetic user follows the cue, which keeps labels honest.
            self.source.set_intent(label)

    def start_recording(self) -> None:
        with self._lock:
            self._rec_data, self._rec_labels = [], []
            self.recording = True

    def stop_recording(self):
        with self._lock:
            self.recording = False
            if not self._rec_data:
                return np.zeros((self.source.info.n_channels, 0)), np.zeros(0, int)
            return np.concatenate(self._rec_data, axis=1), np.concatenate(self._rec_labels)

    def save_last_recording(self, path: str, data, labels) -> None:
        save_recording(path, data, self.source.info.fs, self.source.info.ch_names, labels)

    def run_calibration(self, classes: Sequence[int], trials_per_class: int = 10, cue_s: float = 4.0,
                        rest_s: float = 2.0, on_cue: Optional[Callable[[Optional[int], int, int], None]] = None,
                        on_done: Optional[Callable[[np.ndarray, np.ndarray], None]] = None) -> None:
        """
        Cue protocol in the background: rest, then one cue per trial in random
        order. on_cue(label_or_None, trial_index, total) is called for every
        change; on_done(data, labels) when finished or stopped.
        """
        self.stop_calibration()
        self._calib_stop.clear()
        active = [c for c in classes if c != REST]
        order = active * trials_per_class
        random.shuffle(order)

        def worker():
            self.start_recording()
            try:
                total = len(order)
                for i, cls in enumerate(order):
                    self.set_cue(REST)
                    if on_cue:
                        on_cue(REST, i, total)
                    if self._calib_stop.wait(rest_s):
                        break
                    self.set_cue(cls)
                    if on_cue:
                        on_cue(cls, i, total)
                    if self._calib_stop.wait(cue_s):
                        break
                else:
                    self.set_cue(REST)
                    self._calib_stop.wait(rest_s)
            finally:
                self.set_cue(None)
                data, labels = self.stop_recording()
                if on_cue:
                    on_cue(None, len(order), len(order))
                if on_done:
                    on_done(data, labels)

        self._calib_thread = threading.Thread(target=worker, name="EEGCalibration", daemon=True)
        self._calib_thread.start()

    def stop_calibration(self) -> None:
        self._calib_stop.set()
        if self._calib_thread and self._calib_thread.is_alive() and threading.current_thread() is not self._calib_thread:
            self._calib_thread.join(timeout=2.0)

    def train(self, data: np.ndarray, labels: np.ndarray, classes: Sequence[int], window_s: float = 1.0) -> FingerDecoder:
        info = self.source.info
        dec = train_from_recording(data, labels, info.fs, info.ch_names, classes, window_s, self.notch_hz)
        self.set_decoder(dec)
        return dec

    # ---------------------------------------------------------------- loop
    def _run(self) -> None:
        last_status = 0.0
        while not self._stop.is_set():
            try:
                chunk = self.source.read()
            except Exception as exc:  # device unplugged etc.
                self.status.error = str(exc)
                self.driving = False
                self._emit()
                self._stop.wait(0.5)
                continue
            n = chunk.data.shape[1]
            if n == 0:
                if self.driving and self.mapper is not None:
                    self._send(self.mapper.step())
                self._stop.wait(0.01)
                continue
            self._handle_chunk(chunk)
            now = time.monotonic()
            if now - last_status > 0.1:
                last_status = now
                self._emit()

    def _handle_chunk(self, chunk) -> None:
        data = chunk.data
        n = data.shape[1]
        with self._lock:
            if self.recording:
                if self._cue is not None:
                    lab = np.full(n, self._cue, dtype=int)
                elif chunk.labels is not None:
                    lab = chunk.labels
                else:
                    lab = np.full(n, IGNORE, dtype=int)
                self._rec_data.append(data.copy())
                self._rec_labels.append(lab)
            self.ring.push(self.pre.process(data))
        self._rms_buf.push(data)
        self.status.samples += n
        if chunk.labels is not None and len(chunk.labels):
            self.status.true_label = FINGER_LABELS.get(int(chunk.labels[-1]), None)
        if self.on_chunk:
            self.on_chunk(data)

        now = time.monotonic()
        dec = self.decoder
        if dec is not None and dec.trained and self.ring.full and now - self._last_predict >= 1.0 / self.predict_hz:
            self._last_predict = now
            probs = dec.predict_proba(self.ring.latest())
            self.status.probs = dict(zip(dec.class_names, (float(p) for p in probs)))
            self.status.prediction = dec.class_names[int(np.argmax(probs))]
            if self.driving:
                self._send(self.mapper.update(probs, now))
                self.status.committed = self.mapper.class_name(self.mapper.committed)
        elif self.driving and self.mapper is not None:
            self._send(self.mapper.step(now))

    def _send(self, angles: Optional[List[int]]) -> None:
        if angles is None:
            return
        self.status.last_angles = angles
        if self.controller is not None:
            try:
                self.controller.send_angles(angles)
            except Exception as exc:
                self.status.error = f"Hand: {exc}"

    def _emit(self) -> None:
        s = self.status
        s.driving = self.driving
        s.recording = self.recording
        s.cue = FINGER_LABELS.get(self._cue) if self._cue is not None else None
        with self._lock:
            s.recorded_s = sum(d.shape[1] for d in self._rec_data) / self.source.info.fs if self.recording else 0.0
        if self._rms_buf.count:
            x = self._rms_buf.latest()
            s.channel_rms = list(np.std(x - x.mean(axis=1, keepdims=True), axis=1))
        if self.on_status:
            try:
                self.on_status(s)
            except Exception:
                pass


class UDPCommandListener:
    """
    Lets any external BCI program drive the hand by sending small JSON
    datagrams to 127.0.0.1:<port> (default 5005). Accepted messages:

        {"class": "index"}                          -> committed straight away
        {"class": 2, "confidence": 0.8}             -> goes through the mapper threshold
        {"probs": {"rest": 0.1, "index": 0.9}}      -> goes through the mapper
        {"angles": [180, 0, 180, 180, 180, 90]}     -> sent as-is (clamped 0-180)

    Works with OpenViBE, BCI2000, MATLAB, or a few lines of Python.
    """

    def __init__(self, controller, port: int = 5005, host: str = "127.0.0.1",
                 mapper: Optional[IntentMapper] = None, on_message: Optional[Callable[[dict], None]] = None):
        self.controller = controller
        self.addr = (host, port)
        self.mapper = mapper or IntentMapper([0, 1, 2, 3, 4, 5])
        self.on_message = on_message
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(self.addr)
        self._sock.settimeout(0.05)
        self._stop.clear()
        start = getattr(self.controller, "current_angles", None)
        if start is not None:
            self.mapper.reset(start)
        self._thread = threading.Thread(target=self._run, name="UDPCommands", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._sock:
            self._sock.close()

    def handle(self, msg: dict) -> None:
        m = self.mapper
        if "angles" in msg:
            angles = [int(a) for a in msg["angles"]][:6]
            if len(angles) == 6:
                m.set_target(angles)
                m.current = np.array(angles, dtype=float)
                self._send([max(0, min(180, a)) for a in angles])
            return
        if "probs" in msg:
            probs = [0.0] * len(m.classes)
            for k, v in msg["probs"].items():
                c = NAME_TO_LABEL.get(str(k).lower(), k)
                if c in m.classes:
                    probs[m.classes.index(c)] = float(v)
            self._send(m.update(probs))
            return
        if "class" in msg:
            c = msg["class"]
            c = NAME_TO_LABEL.get(str(c).lower(), c) if not isinstance(c, int) else c
            if c not in m.classes:
                return
            if "confidence" in msg:
                conf = float(msg["confidence"])
                others = (1 - conf) / max(1, len(m.classes) - 1)
                self._send(m.update([conf if k == c else others for k in m.classes]))
            else:
                m.commit(c)
                self._send(m.step())

    def _send(self, angles) -> None:
        if angles is not None and self.controller is not None:
            self.controller.send_angles(list(angles))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                self._send(self.mapper.step())
                continue
            except OSError:
                break
            try:
                msg = json.loads(payload.decode("utf-8"))
                self.handle(msg)
                if self.on_message:
                    self.on_message(msg)
            except Exception:
                continue

#   HANDMOVE - EEG Bridge (bridge)
#        Oumar Ibrahim U22200741

# EEGBridge connects the eeg source to the HandController
#
#   source.read() -> Preprocessor -> RingBuffer -> FingerDecoder -> IntentMapper
#                                                                       |
#                                                    HandController.send_angles()
#
# it also records labeled data for calibration, runs the cues and can take
# commands from other bci programs over UDP (UDPCommandListener)
# everything runs on one background thread and the callbacks come from that
# thread so the gui has to move them to its own thread

import json
import random
import socket
import threading
import time

import numpy as np

from .decoder import FingerDecoder, Preprocessor, RingBuffer, train_from_recording
from .mapper import IntentMapper
from .sources import FINGER_LABELS, IGNORE, REST, EEGSource, save_recording

NAME_TO_LABEL = {}
for k in FINGER_LABELS:
    NAME_TO_LABEL[FINGER_LABELS[k]] = k


class BridgeStatus:
    def __init__(self, fs=0.0):
        self.samples = 0
        self.fs = fs
        self.probs = None
        self.prediction = "-"
        self.committed = "-"
        self.true_label = None
        self.cue = None
        self.driving = False
        self.recording = False
        self.recorded_s = 0.0
        self.channel_rms = None
        self.last_angles = None
        self.error = None


class EEGBridge:
    def __init__(self, source, controller=None, decoder=None, mapper=None, predict_hz=8.0,
                 notch_hz=50.0):
        self.source = source
        self.controller = controller
        self.predict_hz = predict_hz
        self.notch_hz = notch_hz
        self.decoder = None
        self.mapper = mapper
        self.status = BridgeStatus(fs=source.info.fs)
        self.on_status = None
        self.on_chunk = None

        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.driving = False
        self._cue = None
        self._rec_data = []
        self._rec_labels = []
        self.recording = False
        self._last_predict = 0.0
        self._rms_buf = RingBuffer((source.info.n_channels,), int(source.info.fs))
        self._calib_thread = None
        self._calib_stop = threading.Event()
        self.set_decoder(decoder)

    # setup

    def set_decoder(self, decoder):
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

    # start / stop

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.source.start()
        self._thread = threading.Thread(target=self._run, name="EEGBridge", daemon=True)
        self._thread.start()

    def stop(self):
        self.stop_calibration()
        self.driving = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.source.stop()

    def is_running(self):
        if self._thread and self._thread.is_alive():
            return True
        return False

    def start_driving(self):
        if self.decoder is None or not self.decoder.is_trained():
            raise RuntimeError("Train or load a model before driving the hand")
        if self.controller is not None and getattr(self.controller, "is_playing_sequence", False):
            self.controller.stop_sequence()
        start = None
        if self.controller is not None:
            start = getattr(self.controller, "current_angles", None)
        if start is not None:
            self.mapper.reset(start)
        self.driving = True

    def stop_driving(self):
        self.driving = False

    # recording

    # the cue that is shown to the user, it labels the recorded samples
    def set_cue(self, label):
        self._cue = label
        if hasattr(self.source, "set_intent"):
            # the fake user follows the cue so the labels are right
            self.source.set_intent(label)

    def start_recording(self):
        with self._lock:
            self._rec_data = []
            self._rec_labels = []
            self.recording = True

    def stop_recording(self):
        with self._lock:
            self.recording = False
            if not self._rec_data:
                return np.zeros((self.source.info.n_channels, 0)), np.zeros(0, int)
            return np.concatenate(self._rec_data, axis=1), np.concatenate(self._rec_labels)

    def save_last_recording(self, path, data, labels):
        save_recording(path, data, self.source.info.fs, self.source.info.ch_names, labels)

    # cue protocol on a background thread: rest, then one cue per trial in random order
    # on_cue(label or None, trial index, total) is called on every change
    # on_done(data, labels) is called when its finished or stoped
    def run_calibration(self, classes, trials_per_class=10, cue_s=4.0, rest_s=2.0,
                        on_cue=None, on_done=None):
        self.stop_calibration()
        self._calib_stop.clear()
        active = []
        for c in classes:
            if c != REST:
                active.append(c)
        order = active * trials_per_class
        random.shuffle(order)

        def worker():
            self.start_recording()
            try:
                total = len(order)
                stopped = False
                for i in range(total):
                    cls = order[i]
                    self.set_cue(REST)
                    if on_cue:
                        on_cue(REST, i, total)
                    if self._calib_stop.wait(rest_s):
                        stopped = True
                        break
                    self.set_cue(cls)
                    if on_cue:
                        on_cue(cls, i, total)
                    if self._calib_stop.wait(cue_s):
                        stopped = True
                        break
                if not stopped:
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

    def stop_calibration(self):
        self._calib_stop.set()
        if self._calib_thread and self._calib_thread.is_alive():
            if threading.current_thread() is not self._calib_thread:
                self._calib_thread.join(timeout=2.0)

    def train(self, data, labels, classes, window_s=1.0):
        info = self.source.info
        dec = train_from_recording(data, labels, info.fs, info.ch_names, classes, window_s, self.notch_hz)
        self.set_decoder(dec)
        return dec

    # main loop

    def _run(self):
        last_status = 0.0
        while not self._stop.is_set():
            try:
                chunk = self.source.read()
            except Exception as exc:
                # headset unpluged or something
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

    def _handle_chunk(self, chunk):
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
        ready = False
        if dec is not None and dec.is_trained() and self.ring.is_full():
            if now - self._last_predict >= 1.0 / self.predict_hz:
                ready = True
        if ready:
            self._last_predict = now
            probs = dec.predict_proba(self.ring.latest())
            names = dec.class_names()
            prob_dict = {}
            for i in range(len(names)):
                prob_dict[names[i]] = float(probs[i])
            self.status.probs = prob_dict
            self.status.prediction = names[int(np.argmax(probs))]
            if self.driving:
                self._send(self.mapper.update(probs, now))
                self.status.committed = self.mapper.class_name(self.mapper.committed)
        elif self.driving and self.mapper is not None:
            self._send(self.mapper.step(now))

    def _send(self, angles):
        if angles is None:
            return
        self.status.last_angles = angles
        if self.controller is not None:
            try:
                self.controller.send_angles(angles)
            except Exception as exc:
                self.status.error = f"Hand: {exc}"

    def _emit(self):
        s = self.status
        s.driving = self.driving
        s.recording = self.recording
        if self._cue is not None:
            s.cue = FINGER_LABELS.get(self._cue)
        else:
            s.cue = None
        with self._lock:
            if self.recording:
                totl_samples = 0
                for d in self._rec_data:
                    totl_samples += d.shape[1]
                s.recorded_s = totl_samples / self.source.info.fs
            else:
                s.recorded_s = 0.0
        if self._rms_buf.count:
            x = self._rms_buf.latest()
            s.channel_rms = list(np.std(x - x.mean(axis=1, keepdims=True), axis=1))
        if self.on_status:
            try:
                self.on_status(s)
            except Exception:
                pass


# lets any other bci program move the hand by sending small json packets
# to 127.0.0.1:<port> (5005 by default). messages it understands:
#
#   {"class": "index"}                       -> used right away
#   {"class": 2, "confidence": 0.8}          -> goes through the mapper threshold
#   {"probs": {"rest": 0.1, "index": 0.9}}   -> goes through the mapper
#   {"angles": [180, 0, 180, 180, 180, 90]}  -> sent like that (clamped 0-180)
#
# works with openvibe, bci2000, matlab or a few lines of python
class UDPCommandListener:
    def __init__(self, controller, port=5005, host="127.0.0.1", mapper=None, on_message=None):
        self.controller = controller
        self.addr = (host, port)
        if mapper:
            self.mapper = mapper
        else:
            self.mapper = IntentMapper([0, 1, 2, 3, 4, 5])
        self.on_message = on_message
        self._sock = None
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(self.addr)
        self._sock.settimeout(0.05)
        self._stop.clear()
        start = getattr(self.controller, "current_angles", None)
        if start is not None:
            self.mapper.reset(start)
        self._thread = threading.Thread(target=self._run, name="UDPCommands", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._sock:
            self._sock.close()

    def handle(self, msg):
        m = self.mapper
        if "angles" in msg:
            angles = []
            for a in msg["angles"]:
                angles.append(int(a))
            angles = angles[:6]
            if len(angles) == 6:
                m.set_target(angles)
                m.current = np.array(angles, dtype=float)
                clamped = []
                for a in angles:
                    if a < 0:
                        a = 0
                    if a > 180:
                        a = 180
                    clamped.append(a)
                self._send(clamped)
            return
        if "probs" in msg:
            probs = [0.0] * len(m.classes)
            for k in msg["probs"]:
                v = msg["probs"][k]
                c = NAME_TO_LABEL.get(str(k).lower(), k)
                if c in m.classes:
                    probs[m.classes.index(c)] = float(v)
            self._send(m.update(probs))
            return
        if "class" in msg:
            c = msg["class"]
            if not isinstance(c, int):
                c = NAME_TO_LABEL.get(str(c).lower(), c)
            if c not in m.classes:
                return
            if "confidence" in msg:
                conf = float(msg["confidence"])
                n_other = len(m.classes) - 1
                if n_other < 1:
                    n_other = 1
                others = (1 - conf) / n_other
                probs = []
                for k in m.classes:
                    if k == c:
                        probs.append(conf)
                    else:
                        probs.append(others)
                self._send(m.update(probs))
            else:
                m.commit(c)
                self._send(m.step())

    def _send(self, angles):
        if angles is not None and self.controller is not None:
            self.controller.send_angles(list(angles))

    def _run(self):
        while not self._stop.is_set():
            try:
                payload, sender = self._sock.recvfrom(4096)
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

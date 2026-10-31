"""
Tests for the EEG bridge (eeg/ package). No hardware or downloads needed.
Run: python -m unittest discover tests
"""

import json
import os
import socket
import sys
import tempfile
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from controller import HandController
from eeg import (EEGBridge, FingerDecoder, IntentMapper, ReplaySource, SyntheticSource, UDPCommandListener,
                 load_kaya_mat, save_recording, train_from_recording)
from eeg.decoder import make_windows
from eeg.mapper import DEFAULT_POSES


def record_synthetic(seed, blocks=300, n_channels=8):
    src = SyntheticSource(n_channels=n_channels, realtime=False, block=250, seed=seed)
    src.start()
    chunks = [src.read() for _ in range(blocks)]
    return (np.concatenate([c.data for c in chunks], axis=1),
            np.concatenate([c.labels for c in chunks]), src.info)


class TestDecoder(unittest.TestCase):
    def test_trains_and_generalises_to_new_run(self):
        for n_ch in (8, 16):
            d, l, info = record_synthetic(1, n_channels=n_ch)
            dec = train_from_recording(d, l, info.fs, info.ch_names, [0, 1, 2])
            self.assertGreater(dec.cv_accuracy, 0.8)
            d2, l2, _ = record_synthetic(7, 150, n_channels=n_ch)
            X, y, _ = make_windows(dec.make_preprocessor().process(d2), l2, info.fs)
            keep = np.isin(y, dec.classes)
            pred = np.array(dec.classes)[dec.predict_proba_batch(X[keep]).argmax(axis=1)]
            self.assertGreater((pred == y[keep]).mean(), 0.8)

    def test_save_load_roundtrip(self):
        d, l, info = record_synthetic(2, 120)
        dec = train_from_recording(d, l, info.fs, info.ch_names, [0, 1], cv_folds=0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "model.npz")
            dec.save(path)
            dec2 = FingerDecoder.load(path)
        X, _, _ = make_windows(dec.make_preprocessor().process(d), l, info.fs)
        np.testing.assert_allclose(dec.predict_proba_batch(X[:5]), dec2.predict_proba_batch(X[:5]))


class TestMapper(unittest.TestCase):
    def test_commits_only_after_threshold_and_dwell(self):
        m = IntentMapper([0, 2], threshold=0.6, smoothing=1.0, dwell_s=0.3, max_speed_dps=1e6, send_hz=1e6)
        self.assertIsNone(m.update([0.45, 0.55], now=0.0))   # below threshold: hold
        m.update([0.1, 0.9], now=0.1)                          # candidate
        self.assertIsNone(m.committed)
        out = m.update([0.1, 0.9], now=0.5)                    # dwell elapsed
        self.assertEqual(m.committed, 2)
        self.assertEqual(out, list(DEFAULT_POSES[2]))

    def test_speed_limit(self):
        m = IntentMapper([0, 1], smoothing=1.0, dwell_s=0.0, max_speed_dps=100, send_hz=1e6)
        m.update([0.0, 1.0], now=0.0)
        out = m.update([0.0, 1.0], now=0.5)
        self.assertEqual(out[0], 130)  # thumb 180 -> 0 at 100 deg/s for 0.5 s


class TestReplay(unittest.TestCase):
    def test_kaya_mat_format_and_montage(self):
        from scipy.io import savemat
        names = ["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2", "A1", "A2",
                 "F7", "F8", "T3", "T4", "T5", "T6", "Fz", "Cz", "Pz", "X5"]
        n = 2000
        marker = np.zeros(n)
        marker[200:400] = 2
        marker[1900:] = 92
        o = {"sampFreq": 200, "data": np.random.randn(n, 22), "marker": marker[:, None],
             "chnames": np.array(names, dtype=object)[:, None]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "5F-SubjectA-160405-5St-SGLHand.mat")
            savemat(path, {"o": o})
            data, fs, ch, labels = load_kaya_mat(path)
            self.assertEqual(fs, 200)
            self.assertEqual(len(ch), 21)
            self.assertEqual(labels[300], 2)
            self.assertEqual(labels[1950], -1)
            src = ReplaySource(path, montage=8, realtime=False, block=100)
            self.assertEqual(src.info.ch_names, ["C3", "Cz", "C4", "F3", "F4", "P3", "Pz", "P4"])
            src.start()
            self.assertEqual(src.read().data.shape, (8, 100))

    def test_kaya_training_labels_epoch_from_onset(self):
        from eeg.sources import kaya_training_labels
        fs = 100
        labels = np.zeros(1000, dtype=int)
        labels[200:330] = 3          # 1.3 s cue
        labels[900:] = -1
        out = kaya_training_labels(labels, fs, start_s=0.25, len_s=1.0, rest_guard_s=1.0)
        self.assertTrue(np.all(out[225:325] == 3))
        self.assertTrue(np.all(out[200:225] == -1))
        self.assertTrue(np.all(out[330:430] == -1))   # guard after cue
        self.assertTrue(np.all(out[430:900] == 0))
        self.assertTrue(np.all(out[0:200] == 0))

    def test_npz_recording_roundtrip(self):
        d, l, info = record_synthetic(3, 20)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rec.npz")
            save_recording(path, d, info.fs, info.ch_names, l)
            src = ReplaySource(path, realtime=False, block=50)
            src.start()
            c = src.read()
            np.testing.assert_allclose(c.data, d[:, :50])


class TestBridge(unittest.TestCase):
    def test_end_to_end_drives_controller(self):
        d, l, info = record_synthetic(1)
        ctrl = HandController(simulation_mode=True, transport="serial")
        src = SyntheticSource(n_channels=8, seed=5, speed=4.0)
        bridge = EEGBridge(src, controller=ctrl)
        bridge.train(d, l, [0, 1])
        bridge.mapper.dwell_s = 0.2
        bridge.start()
        try:
            time.sleep(1.0)
            bridge.start_driving()
            bridge.set_cue(1)
            time.sleep(2.0)
            self.assertLess(ctrl.current_angles[0], 30)      # thumb flexed
            bridge.set_cue(0)
            time.sleep(2.0)
            self.assertGreater(ctrl.current_angles[0], 150)  # back to open
        finally:
            bridge.stop()


class TestUDP(unittest.TestCase):
    def test_udp_angles_and_class(self):
        ctrl = HandController(simulation_mode=True, transport="serial")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        lst = UDPCommandListener(ctrl, port=port, mapper=IntentMapper([0, 1, 2], max_speed_dps=1e6, send_hz=1e6))
        lst.start()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(json.dumps({"angles": [10, 20, 30, 40, 50, 60]}).encode(), ("127.0.0.1", port))
                time.sleep(0.3)
                self.assertEqual(ctrl.current_angles, [10, 20, 30, 40, 50, 60])
                s.sendto(json.dumps({"class": "index"}).encode(), ("127.0.0.1", port))
                time.sleep(0.3)
                self.assertEqual(ctrl.current_angles, list(DEFAULT_POSES[2]))
        finally:
            lst.stop()


if __name__ == "__main__":
    unittest.main()

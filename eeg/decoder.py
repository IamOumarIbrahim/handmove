"""
Signal processing and finger-intent decoding.

Pipeline (identical during calibration and live use):
  raw uV -> common average reference -> notch (50/60 Hz) -> filter bank
  (mu 8-13 Hz, beta 13-30 Hz, causal IIR with kept state) -> sliding window
  -> features [one-vs-rest CSP log-variance + per-channel log band power]
  -> shrinkage LDA -> class probabilities.

Only numpy and scipy are needed. Scalp EEG decoding of individual fingers is
hard: published 5-finger results with 19-channel EEG are around 40-60 % (chance
is 20 %). Fewer classes (rest vs. one finger, or two fingers) are far more
reliable, so the class set is configurable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import linalg, signal

from .sources import FINGER_LABELS, IGNORE

DEFAULT_BANDS: Tuple[Tuple[float, float], ...] = ((8.0, 13.0), (13.0, 30.0))


class Preprocessor:
    """Stateful causal filtering so chunks can be fed in any size."""

    def __init__(self, fs: float, n_channels: int, bands=DEFAULT_BANDS, notch_hz: Optional[float] = 50.0,
                 car: bool = True, order: int = 4):
        self.fs = fs
        self.n_channels = n_channels
        self.bands = [tuple(b) for b in bands]
        self.notch_hz = notch_hz
        self.car = car and n_channels > 2
        nyq = fs / 2.0
        self._notch = None
        if notch_hz and notch_hz < nyq - 1:
            b, a = signal.iirnotch(notch_hz, 30.0, fs)
            self._notch = signal.tf2sos(b, a)
            self._notch_zi = np.zeros((self._notch.shape[0], n_channels, 2))
        self._bank = []
        for lo, hi in self.bands:
            hi = min(hi, nyq * 0.95)
            sos = signal.butter(order, [lo, hi], btype="bandpass", fs=fs, output="sos")
            self._bank.append([sos, np.zeros((sos.shape[0], n_channels, 2))])

    def reset(self) -> None:
        if self._notch is not None:
            self._notch_zi[:] = 0
        for item in self._bank:
            item[1][:] = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        """x: (n_channels, n) -> (n_bands, n_channels, n)"""
        x = np.asarray(x, dtype=float)
        if x.shape[1] == 0:
            return np.zeros((len(self._bank), self.n_channels, 0))
        if self.car:
            x = x - x.mean(axis=0, keepdims=True)
        if self._notch is not None:
            x, self._notch_zi = signal.sosfilt(self._notch, x, axis=1, zi=self._notch_zi)
        out = np.empty((len(self._bank),) + x.shape)
        for i, item in enumerate(self._bank):
            out[i], item[1] = signal.sosfilt(item[0], x, axis=1, zi=item[1])
        return out


class RingBuffer:
    """Keeps the most recent `size` samples of a (bands, channels, n) stream."""

    def __init__(self, shape_prefix: Tuple[int, ...], size: int):
        self.buf = np.zeros(shape_prefix + (size,))
        self.size = size
        self.count = 0

    def push(self, x: np.ndarray) -> None:
        n = x.shape[-1]
        if n == 0:
            return
        if n >= self.size:
            self.buf[...] = x[..., -self.size:]
        else:
            self.buf = np.roll(self.buf, -n, axis=-1)
            self.buf[..., -n:] = x
        self.count += n

    @property
    def full(self) -> bool:
        return self.count >= self.size

    def latest(self) -> np.ndarray:
        return self.buf


def make_windows(filtered: np.ndarray, labels: np.ndarray, fs: float, window_s: float = 1.0,
                 step_s: float = 0.25, skip_s: float = 0.5):
    """
    Cut labelled training windows out of a continuous filtered recording.
    filtered: (bands, channels, n); labels: (n,) with IGNORE for unusable samples.
    A window is kept only if every sample in it carries the same label, and it
    starts at least `skip_s` after that label began (reaction time).
    Returns (X[n_win, bands, channels, win], y[n_win], groups[n_win]); groups
    identifies the trial so cross-validation can keep trials together.
    """
    win, step, skip = int(window_s * fs), max(1, int(step_s * fs)), int(skip_s * fs)
    labels = np.asarray(labels).astype(int)
    change = np.flatnonzero(np.diff(labels)) + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change, [len(labels)]])
    X, y, g = [], [], []
    for trial, (s, e) in enumerate(zip(starts, ends)):
        lab = labels[s]
        if lab == IGNORE:
            continue
        for w0 in range(s + skip, e - win + 1, step):
            X.append(filtered[..., w0:w0 + win])
            y.append(lab)
            g.append(trial)
    if not X:
        shape = (0,) + filtered.shape[:-1] + (win,)
        return np.zeros(shape), np.zeros(0, int), np.zeros(0, int)
    return np.stack(X), np.array(y), np.array(g)


def _cov(x: np.ndarray) -> np.ndarray:
    c = x @ x.T
    return c / max(np.trace(c), 1e-12)


@dataclass
class FingerDecoder:
    fs: float
    ch_names: List[str]
    classes: List[int]
    bands: List[Tuple[float, float]] = field(default_factory=lambda: list(DEFAULT_BANDS))
    window_s: float = 1.0
    csp_pairs: int = 2
    shrinkage: float = 0.2
    notch_hz: Optional[float] = 50.0
    # learned
    csp_filters: Optional[np.ndarray] = None  # (bands, n_filters, channels)
    lda_w: Optional[np.ndarray] = None        # (features, classes)
    lda_b: Optional[np.ndarray] = None        # (classes,)
    feat_mean: Optional[np.ndarray] = None
    feat_std: Optional[np.ndarray] = None
    cv_accuracy: Optional[float] = None

    @property
    def class_names(self) -> List[str]:
        return [FINGER_LABELS.get(c, str(c)) for c in self.classes]

    @property
    def trained(self) -> bool:
        return self.lda_w is not None

    def make_preprocessor(self) -> Preprocessor:
        return Preprocessor(self.fs, len(self.ch_names), self.bands, self.notch_hz)

    # ---------------------------------------------------------------- features
    def _fit_csp(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        n_bands, n_ch = X.shape[1], X.shape[2]
        pairs = max(1, min(self.csp_pairs, n_ch // 2))
        filters = []
        for b in range(n_bands):
            covs = np.array([_cov(x) for x in X[:, b]])
            band_f = []
            # one-vs-rest; with 2 classes one direction is enough
            targets = self.classes if len(self.classes) > 2 else self.classes[:1]
            for c in targets:
                ca = covs[y == c].mean(axis=0)
                cb = covs[y != c].mean(axis=0)
                reg = 1e-6 * np.eye(n_ch)
                vals, vecs = linalg.eigh(ca + reg, ca + cb + 2 * reg)
                band_f.append(vecs[:, :pairs].T)
                band_f.append(vecs[:, -pairs:].T)
            filters.append(np.concatenate(band_f))
        return np.stack(filters)

    def _features(self, X: np.ndarray) -> np.ndarray:
        """X: (n, bands, channels, samples) -> (n, features)"""
        csp = np.einsum("bfc,nbcs->nbfs", self.csp_filters, X)
        v = np.log(np.var(csp, axis=-1) + 1e-12).reshape(len(X), -1)
        bp = np.log(np.var(X, axis=-1) + 1e-12).reshape(len(X), -1)
        return np.concatenate([v, bp], axis=1)

    # ---------------------------------------------------------------- training
    def fit(self, X: np.ndarray, y: np.ndarray) -> "FingerDecoder":
        keep = np.isin(y, self.classes)
        X, y = X[keep], y[keep]
        missing = [FINGER_LABELS.get(c, str(c)) for c in self.classes if not np.any(y == c)]
        if missing:
            raise ValueError(f"No usable training windows for: {', '.join(missing)}. "
                             "Record more trials (each cue must last longer than the 1 s window + 0.5 s reaction).")
        self.csp_filters = self._fit_csp(X, y)
        F = self._features(X)
        self.feat_mean = F.mean(axis=0)
        self.feat_std = F.std(axis=0) + 1e-9
        F = (F - self.feat_mean) / self.feat_std
        d = F.shape[1]
        means = np.array([F[y == c].mean(axis=0) if np.any(y == c) else np.zeros(d) for c in self.classes])
        resid = F - means[[self.classes.index(v) for v in y]]
        S = resid.T @ resid / max(1, len(F) - len(self.classes))
        S = (1 - self.shrinkage) * S + self.shrinkage * (np.trace(S) / d) * np.eye(d)
        Sinv = linalg.pinvh(S)
        # Equal priors: the hand should not favour a class just because
        # calibration recorded more of it (e.g. long rest periods).
        priors = np.full(len(self.classes), 1.0 / len(self.classes))
        self.lda_w = Sinv @ means.T
        self.lda_b = -0.5 * np.sum(means @ Sinv * means, axis=1) + np.log(priors)
        return self

    def cross_validate(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int = 5) -> float:
        keep = np.isin(y, self.classes)
        X, y, groups = X[keep], y[keep], groups[keep]
        uniq = np.unique(groups)
        rng = np.random.default_rng(0)
        rng.shuffle(uniq)
        hits = {c: 0 for c in self.classes}
        counts = {c: 0 for c in self.classes}
        for k in range(min(folds, len(uniq))):
            test_g = uniq[k::folds]
            te = np.isin(groups, test_g)
            if te.all() or not te.any() or not set(self.classes) <= set(np.unique(y[~te])):
                continue
            m = FingerDecoder(self.fs, self.ch_names, self.classes, self.bands, self.window_s,
                              self.csp_pairs, self.shrinkage, self.notch_hz).fit(X[~te], y[~te])
            pred = np.array(m.classes)[m.predict_proba_batch(X[te]).argmax(axis=1)]
            for c in self.classes:
                sel = y[te] == c
                hits[c] += int(np.sum(pred[sel] == c))
                counts[c] += int(sel.sum())
        # Balanced accuracy (mean per-class hit rate): chance = 1 / n_classes
        # even when one class has many more windows than the others.
        recalls = [hits[c] / counts[c] for c in self.classes if counts[c]]
        self.cv_accuracy = float(np.mean(recalls)) if recalls else None
        return self.cv_accuracy

    # --------------------------------------------------------------- inference
    def predict_proba_batch(self, X: np.ndarray) -> np.ndarray:
        F = (self._features(X) - self.feat_mean) / self.feat_std
        z = F @ self.lda_w + self.lda_b
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=1, keepdims=True)

    def predict_proba(self, window: np.ndarray) -> np.ndarray:
        """window: (bands, channels, samples) -> (n_classes,)"""
        return self.predict_proba_batch(window[None])[0]

    # ------------------------------------------------------------ persistence
    def save(self, path: str) -> None:
        meta = dict(fs=self.fs, ch_names=self.ch_names, classes=self.classes, bands=self.bands,
                    window_s=self.window_s, csp_pairs=self.csp_pairs, shrinkage=self.shrinkage,
                    notch_hz=self.notch_hz, cv_accuracy=self.cv_accuracy)
        np.savez(path, meta=json.dumps(meta), csp=self.csp_filters, w=self.lda_w, b=self.lda_b,
                 mean=self.feat_mean, std=self.feat_std)

    @classmethod
    def load(cls, path: str) -> "FingerDecoder":
        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        m = cls(meta["fs"], meta["ch_names"], meta["classes"], [tuple(b) for b in meta["bands"]],
                meta["window_s"], meta["csp_pairs"], meta["shrinkage"], meta["notch_hz"])
        m.csp_filters, m.lda_w, m.lda_b = z["csp"], z["w"], z["b"]
        m.feat_mean, m.feat_std = z["mean"], z["std"]
        m.cv_accuracy = meta.get("cv_accuracy")
        return m


def train_from_recording(data: np.ndarray, labels: np.ndarray, fs: float, ch_names: Sequence[str],
                         classes: Sequence[int], window_s: float = 1.0, notch_hz: Optional[float] = 50.0,
                         cv_folds: int = 5, skip_s: float = 0.5) -> FingerDecoder:
    """Filter a continuous labelled recording, cut windows, cross-validate, and fit."""
    dec = FingerDecoder(fs, list(ch_names), sorted(int(c) for c in classes), window_s=window_s, notch_hz=notch_hz)
    pre = dec.make_preprocessor()
    filtered = pre.process(data)
    X, y, g = make_windows(filtered, labels, fs, window_s, skip_s=skip_s)
    if cv_folds:
        dec.cross_validate(X, y, g, cv_folds)
    return dec.fit(X, y)

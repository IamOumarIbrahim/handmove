#   HANDMOVE - EEG Bridge (decoder)
#        Oumar Ibrahim U22200741

# signal processing and finger decoding
# steps (same in calibration and live):
# raw uV -> common average ref -> notch 50/60 Hz -> filter bank
# (mu 8-13 Hz and beta 13-30 Hz, causal iir that keeps its state) -> window
# -> features (one vs rest CSP log variance + log band power per channel)
# -> shrinkage LDA -> probabilities for each class
#
# only numpy and scipy needed. single finger decoding from scalp eeg is hard,
# papers with 19 channels get about 40-60 % for 5 fingers (chance is 20 %)
# less classes works much better so the classes can be picked

import json

import numpy as np
from scipy import linalg, signal

from .sources import FINGER_LABELS, IGNORE

DEFAULT_BANDS = ((8.0, 13.0), (13.0, 30.0))


# filters that keep there state so chunks can be any size
class Preprocessor:
    def __init__(self, fs, n_channels, bands=DEFAULT_BANDS, notch_hz=50.0, car=True, order=4):
        self.fs = fs
        self.n_channels = n_channels
        self.bands = []
        for b in bands:
            self.bands.append(tuple(b))
        self.notch_hz = notch_hz
        self.car = car and n_channels > 2
        nyq = fs / 2.0
        self._notch = None
        if notch_hz and notch_hz < nyq - 1:
            b, a = signal.iirnotch(notch_hz, 30.0, fs)
            self._notch = signal.tf2sos(b, a)
            self._notch_zi = np.zeros((self._notch.shape[0], n_channels, 2))
        self._bank = []
        for band in self.bands:
            lo = band[0]
            hi = band[1]
            if hi > nyq * 0.95:
                hi = nyq * 0.95
            sos = signal.butter(order, [lo, hi], btype="bandpass", fs=fs, output="sos")
            self._bank.append([sos, np.zeros((sos.shape[0], n_channels, 2))])

    def reset(self):
        if self._notch is not None:
            self._notch_zi[:] = 0
        for item in self._bank:
            item[1][:] = 0

    # x is (channels, n), gives back (bands, channels, n)
    def process(self, x):
        x = np.asarray(x, dtype=float)
        if x.shape[1] == 0:
            return np.zeros((len(self._bank), self.n_channels, 0))
        if self.car:
            x = x - x.mean(axis=0, keepdims=True)
        if self._notch is not None:
            x, self._notch_zi = signal.sosfilt(self._notch, x, axis=1, zi=self._notch_zi)
        out = np.empty((len(self._bank), x.shape[0], x.shape[1]))
        for i in range(len(self._bank)):
            item = self._bank[i]
            out[i], item[1] = signal.sosfilt(item[0], x, axis=1, zi=item[1])
        return out


# keeps the last "size" samples of a (bands, channels, n) stream
class RingBuffer:
    def __init__(self, shape_prefix, size):
        self.buf = np.zeros(tuple(shape_prefix) + (size,))
        self.size = size
        self.count = 0

    def push(self, x):
        n = x.shape[-1]
        if n == 0:
            return
        if n >= self.size:
            self.buf[...] = x[..., -self.size:]
        else:
            self.buf = np.roll(self.buf, -n, axis=-1)
            self.buf[..., -n:] = x
        self.count += n

    def is_full(self):
        return self.count >= self.size

    def latest(self):
        return self.buf


# cuts the training windows out of a filtered recording
# filtered is (bands, channels, n) and labels is (n,) with IGNORE for bad samples
# a window is only kept if all its samples have the same label and it starts
# skip_s after that label started (reaction time)
# groups says which trial each window is from so cross validation keeps trials together
def make_windows(filtered, labels, fs, window_s=1.0, step_s=0.25, skip_s=0.5):
    win = int(window_s * fs)
    step = int(step_s * fs)
    if step < 1:
        step = 1
    skip = int(skip_s * fs)
    labels = np.asarray(labels).astype(int)
    change = np.flatnonzero(np.diff(labels)) + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change, [len(labels)]])
    X = []
    y = []
    g = []
    for trial in range(len(starts)):
        s = starts[trial]
        e = ends[trial]
        lab = labels[s]
        if lab == IGNORE:
            continue
        for w0 in range(s + skip, e - win + 1, step):
            X.append(filtered[..., w0:w0 + win])
            y.append(lab)
            g.append(trial)
    if len(X) == 0:
        shape = (0,) + filtered.shape[:-1] + (win,)
        return np.zeros(shape), np.zeros(0, int), np.zeros(0, int)
    return np.stack(X), np.array(y), np.array(g)


def covariance(x):
    c = np.dot(x, x.T)
    tr = np.trace(c)
    if tr < 1e-12:
        tr = 1e-12
    return c / tr


class FingerDecoder:
    def __init__(self, fs, ch_names, classes, bands=None, window_s=1.0, csp_pairs=2,
                 shrinkage=0.2, notch_hz=50.0, csp_filters=None, lda_w=None, lda_b=None,
                 feat_mean=None, feat_std=None, cv_accuracy=None):
        self.fs = fs
        self.ch_names = ch_names
        self.classes = classes
        if bands is None:
            bands = list(DEFAULT_BANDS)
        self.bands = bands
        self.window_s = window_s
        self.csp_pairs = csp_pairs
        self.shrinkage = shrinkage
        self.notch_hz = notch_hz
        # learned stuff
        self.csp_filters = csp_filters  # (bands, filters, channels)
        self.lda_w = lda_w  # (features, classes)
        self.lda_b = lda_b  # (classes,)
        self.feat_mean = feat_mean
        self.feat_std = feat_std
        self.cv_accuracy = cv_accuracy

    def class_names(self):
        names = []
        for c in self.classes:
            names.append(FINGER_LABELS.get(c, str(c)))
        return names

    def is_trained(self):
        return self.lda_w is not None

    def make_preprocessor(self):
        return Preprocessor(self.fs, len(self.ch_names), self.bands, self.notch_hz)

    # features

    def _fit_csp(self, X, y):
        n_bands = X.shape[1]
        n_ch = X.shape[2]
        pairs = self.csp_pairs
        if pairs > n_ch // 2:
            pairs = n_ch // 2
        if pairs < 1:
            pairs = 1
        filters = []
        for b in range(n_bands):
            cov_list = []
            for x in X[:, b]:
                cov_list.append(covariance(x))
            covs = np.array(cov_list)
            band_f = []
            # one vs rest, with 2 classes one way is enough
            if len(self.classes) > 2:
                targets = self.classes
            else:
                targets = self.classes[:1]
            for c in targets:
                ca = covs[y == c].mean(axis=0)
                cb = covs[y != c].mean(axis=0)
                reg = 1e-6 * np.eye(n_ch)
                vals, vecs = linalg.eigh(ca + reg, ca + cb + 2 * reg)
                band_f.append(vecs[:, :pairs].T)
                band_f.append(vecs[:, -pairs:].T)
            filters.append(np.concatenate(band_f))
        return np.stack(filters)

    # X is (n, bands, channels, samples), gives (n, features)
    def _features(self, X):
        n = len(X)
        n_bands = X.shape[1]
        csp = []
        for b in range(n_bands):
            # (filters, channels) times (n, channels, samples)
            csp.append(np.matmul(self.csp_filters[b], X[:, b]))
        csp = np.stack(csp, axis=1)
        v = np.log(np.var(csp, axis=-1) + 1e-12).reshape(n, -1)
        bp = np.log(np.var(X, axis=-1) + 1e-12).reshape(n, -1)
        return np.concatenate([v, bp], axis=1)

    # training

    def fit(self, X, y):
        keep = np.isin(y, self.classes)
        X = X[keep]
        y = y[keep]
        missing = []
        for c in self.classes:
            if not np.any(y == c):
                missing.append(FINGER_LABELS.get(c, str(c)))
        if missing:
            raise ValueError(f"No usable training windows for: {', '.join(missing)}. "
                             "Record more trials (each cue must last longer than the 1 s window + 0.5 s reaction).")
        self.csp_filters = self._fit_csp(X, y)
        F = self._features(X)
        self.feat_mean = F.mean(axis=0)
        self.feat_std = F.std(axis=0) + 1e-9
        F = (F - self.feat_mean) / self.feat_std
        d = F.shape[1]
        mean_list = []
        for c in self.classes:
            if np.any(y == c):
                mean_list.append(F[y == c].mean(axis=0))
            else:
                mean_list.append(np.zeros(d))
        means = np.array(mean_list)
        rows = []
        for v in y:
            rows.append(self.classes.index(v))
        resid = F - means[rows]
        dof = len(F) - len(self.classes)
        if dof < 1:
            dof = 1
        S = np.dot(resid.T, resid) / dof
        S = (1 - self.shrinkage) * S + self.shrinkage * (np.trace(S) / d) * np.eye(d)
        Sinv = linalg.pinvh(S)
        # equal priors so the hand doesnt like a class just because there was
        # more of it in calibration (like long rest)
        priors = np.full(len(self.classes), 1.0 / len(self.classes))
        self.lda_w = np.dot(Sinv, means.T)
        temp = np.dot(means, Sinv) * means
        self.lda_b = -0.5 * np.sum(temp, axis=1) + np.log(priors)
        return self

    def cross_validate(self, X, y, groups, folds=5):
        keep = np.isin(y, self.classes)
        X = X[keep]
        y = y[keep]
        groups = groups[keep]
        uniq = np.unique(groups)
        rng = np.random.default_rng(0)
        rng.shuffle(uniq)
        hits = {}
        counts = {}
        for c in self.classes:
            hits[c] = 0
            counts[c] = 0
        n_folds = folds
        if len(uniq) < n_folds:
            n_folds = len(uniq)
        for k in range(n_folds):
            test_g = uniq[k::folds]
            te = np.isin(groups, test_g)
            if te.all() or not te.any():
                continue
            # every class has to be in the training part
            train_classes = list(np.unique(y[~te]))
            has_all = True
            for c in self.classes:
                if c not in train_classes:
                    has_all = False
            if not has_all:
                continue
            m = FingerDecoder(self.fs, self.ch_names, self.classes, self.bands, self.window_s,
                              self.csp_pairs, self.shrinkage, self.notch_hz)
            m.fit(X[~te], y[~te])
            probs = m.predict_proba_batch(X[te])
            pred = np.array(m.classes)[probs.argmax(axis=1)]
            for c in self.classes:
                sel = y[te] == c
                hits[c] += int(np.sum(pred[sel] == c))
                counts[c] += int(sel.sum())
        # balanced accuracy (mean of each class hit rate) so chance is 1 / classes
        # even if one class has way more windows
        recalls = []
        for c in self.classes:
            if counts[c]:
                recalls.append(hits[c] / counts[c])
        if recalls:
            self.cv_accuracy = float(np.mean(recalls))
        else:
            self.cv_accuracy = None
        return self.cv_accuracy

    # prediction

    def predict_proba_batch(self, X):
        F = (self._features(X) - self.feat_mean) / self.feat_std
        z = np.dot(F, self.lda_w) + self.lda_b
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=1, keepdims=True)

    # window is (bands, channels, samples), gives (classes,)
    def predict_proba(self, window):
        return self.predict_proba_batch(window[None])[0]

    # saving and loading

    def save(self, path):
        meta = {}
        meta["fs"] = self.fs
        meta["ch_names"] = self.ch_names
        meta["classes"] = self.classes
        meta["bands"] = self.bands
        meta["window_s"] = self.window_s
        meta["csp_pairs"] = self.csp_pairs
        meta["shrinkage"] = self.shrinkage
        meta["notch_hz"] = self.notch_hz
        meta["cv_accuracy"] = self.cv_accuracy
        np.savez(path, meta=json.dumps(meta), csp=self.csp_filters, w=self.lda_w, b=self.lda_b,
                 mean=self.feat_mean, std=self.feat_std)

    @staticmethod
    def load(path):
        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        bands = []
        for b in meta["bands"]:
            bands.append(tuple(b))
        m = FingerDecoder(meta["fs"], meta["ch_names"], meta["classes"], bands,
                          meta["window_s"], meta["csp_pairs"], meta["shrinkage"], meta["notch_hz"])
        m.csp_filters = z["csp"]
        m.lda_w = z["w"]
        m.lda_b = z["b"]
        m.feat_mean = z["mean"]
        m.feat_std = z["std"]
        m.cv_accuracy = meta.get("cv_accuracy")
        return m


# filter the labelled recording, cut windows, cross validate and then fit
def train_from_recording(data, labels, fs, ch_names, classes, window_s=1.0, notch_hz=50.0,
                         cv_folds=5, skip_s=0.5):
    cls_list = []
    for c in classes:
        cls_list.append(int(c))
    cls_list.sort()
    dec = FingerDecoder(fs, list(ch_names), cls_list, window_s=window_s, notch_hz=notch_hz)
    pre = dec.make_preprocessor()
    filtered = pre.process(data)
    X, y, g = make_windows(filtered, labels, fs, window_s, skip_s=skip_s)
    if cv_folds:
        dec.cross_validate(X, y, g, cv_folds)
    dec.fit(X, y)
    return dec

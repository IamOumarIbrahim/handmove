"""
EEG input sources behind a single device-agnostic interface.

Every source yields `Chunk` objects: a (n_channels, n_samples) float array in
microvolts, plus an optional per-sample label array (ground truth, only known
for replayed datasets and the synthetic generator).

Sources
-------
- BrainFlowSource : OpenBCI Cyton (8 ch), Cyton + Daisy (16 ch), Ganglion,
                    BrainFlow's synthetic board, and any other BrainFlow board id.
- LSLSource       : any device or program that publishes a Lab Streaming Layer
                    EEG stream (OpenBCI GUI, Emotiv, g.tec Unicorn, Muse, ...).
- ReplaySource    : plays back a recording in real time. Reads the Kaya et al.
                    2018 "5F" finger-imagery .mat files and HANDMOVE's own .npz
                    recordings.
- SyntheticSource : generates mu-rhythm EEG whose desynchronisation pattern
                    depends on the intended finger. Lets the full pipeline be
                    exercised with no hardware and no download.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

# Label convention shared by every source and the decoder.
REST = 0
FINGER_LABELS: Dict[int, str] = {0: "rest", 1: "thumb", 2: "index", 3: "middle", 4: "ring", 5: "pinky"}
IGNORE = -1  # samples that belong to no class (breaks, session markers)

# Electrode subsets used to emulate an 8 or 16 channel headset from a
# larger recording. Chosen to cover sensorimotor cortex first.
MONTAGE_8 = ["C3", "Cz", "C4", "F3", "F4", "P3", "Pz", "P4"]
MONTAGE_16 = MONTAGE_8 + ["Fz", "T3", "T4", "Fp1", "Fp2", "O1", "O2", "F7"]
# Default electrode names of the OpenBCI Cyton/Daisy montage in the OpenBCI docs.
OPENBCI_8 = ["Fp1", "Fp2", "C3", "C4", "P7", "P8", "O1", "O2"]
OPENBCI_16 = OPENBCI_8 + ["F7", "F8", "F3", "F4", "T7", "T8", "P3", "P4"]


@dataclass
class Chunk:
    data: np.ndarray                      # (n_channels, n_samples), microvolts
    labels: Optional[np.ndarray] = None   # (n_samples,) int, or None if unknown


@dataclass
class SourceInfo:
    name: str
    fs: float
    ch_names: List[str]
    has_labels: bool = False
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def n_channels(self) -> int:
        return len(self.ch_names)


class EEGSource(ABC):
    """Common interface. `read()` never blocks for long; it returns what is available."""

    info: SourceInfo

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def read(self) -> Chunk: ...

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


def _empty(n_ch: int, with_labels: bool) -> Chunk:
    return Chunk(np.zeros((n_ch, 0)), np.zeros(0, dtype=int) if with_labels else None)


# =============================================================================
# Timed (paced) base for file and synthetic sources
# =============================================================================

class _PacedSource(EEGSource):
    """Releases samples at `fs * speed` per wall-clock second. With
    realtime=False each read() returns a fixed block instantly (for tests)."""

    def __init__(self, realtime: bool = True, speed: float = 1.0, block: int = 32):
        self.realtime = realtime
        self.speed = speed
        self.block = block
        self._t0 = 0.0
        self._emitted = 0
        self._running = False

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self._emitted = 0
        self._running = True

    def stop(self) -> None:
        self._running = False

    def _due(self) -> int:
        if not self._running:
            return 0
        if not self.realtime:
            return self.block
        elapsed = time.perf_counter() - self._t0
        target = int(elapsed * self.info.fs * self.speed)
        return max(0, target - self._emitted)


# =============================================================================
# Synthetic source
# =============================================================================

class SyntheticSource(_PacedSource):
    """
    Background 1/f noise plus a 10 Hz mu and 20 Hz beta rhythm on every channel.
    While a finger is "imagined", the rhythm drops (event-related
    desynchronisation) on a channel pattern specific to that finger, which is a
    simplified version of what real motor imagery looks like.

    The intended class follows an automatic cue schedule (cue_s on, rest_s off)
    unless `set_intent()` is called, so labels are always available.
    """

    def __init__(self, n_channels: int = 8, fs: float = 250.0, classes: Sequence[int] = (1, 2, 3, 4, 5),
                 cue_s: float = 4.0, rest_s: float = 2.0, seed: Optional[int] = None,
                 erd_depth: float = 0.2, **kw):
        super().__init__(**kw)
        names = (OPENBCI_16 if n_channels > 8 else OPENBCI_8)[:n_channels]
        names += [f"Ch{i + 1}" for i in range(len(names), n_channels)]
        self.info = SourceInfo("Synthetic EEG", fs, names, has_labels=True)
        self.rng = np.random.default_rng(seed)
        self.classes = list(classes)
        self.cue_n = int(cue_s * fs)
        self.rest_n = int(rest_s * fs)
        self.erd_depth = erd_depth
        self._manual_intent: Optional[int] = None
        self._sample = 0
        self._pink_state = np.zeros(n_channels)
        # The simulated "subject": fixed rhythm phases across the scalp and a
        # fixed channel pattern that each class desynchronises. Only the noise
        # depends on `seed`, so a model trained on one run works on the next.
        pattern_rng = np.random.default_rng(1234)
        self._phase = pattern_rng.uniform(0, 2 * np.pi, (n_channels, 2))
        self.patterns = {}
        for c in range(0, 6):
            w = pattern_rng.uniform(0.0, 1.0, n_channels) ** 2
            self.patterns[c] = w / w.max()
        self.patterns[REST] = np.zeros(n_channels)

    def set_intent(self, label: Optional[int]) -> None:
        """Force the simulated user's intent (None = follow the cue schedule)."""
        self._manual_intent = label

    def _scheduled_label(self, idx: np.ndarray) -> np.ndarray:
        period = self.cue_n + self.rest_n
        trial = idx // period
        within = idx % period
        cls = np.array(self.classes)[trial % len(self.classes)]
        return np.where(within < self.rest_n, REST, cls)

    def read(self) -> Chunk:
        n = self._due()
        if n == 0:
            return _empty(self.info.n_channels, True)
        fs = self.info.fs
        idx = np.arange(self._sample, self._sample + n)
        labels = (np.full(n, self._manual_intent) if self._manual_intent is not None
                  else self._scheduled_label(idx))
        t = idx / fs
        n_ch = self.info.n_channels

        # 1/f-ish noise via a leaky integrator of white noise
        white = self.rng.normal(0, 1, (n_ch, n))
        pink = np.empty_like(white)
        state = self._pink_state
        for k in range(n):
            state = 0.97 * state + white[:, k]
            pink[:, k] = state
        self._pink_state = state

        gain = np.ones((n_ch, n))
        for c in np.unique(labels):
            mask = labels == c
            gain[:, mask] -= self.erd_depth * self.patterns[int(c)][:, None]
        mu = 10.0 * np.sin(2 * np.pi * 10.0 * t + self._phase[:, :1])
        beta = 4.0 * np.sin(2 * np.pi * 21.0 * t + self._phase[:, 1:])
        data = 2.0 * pink + gain * (mu + beta) + self.rng.normal(0, 2.0, (n_ch, n))

        self._sample += n
        self._emitted += n
        return Chunk(data, labels.astype(int))


# =============================================================================
# Replay source (Kaya 2018 5F .mat, HANDMOVE .npz)
# =============================================================================

def load_kaya_mat(path: str):
    """
    Load one file of Kaya et al. 2018, "A large electroencephalographic motor
    imagery dataset for EEG-based brain-computer interfaces", Sci Data 5:180211.
    Files are on figshare (collection 3917698); the 5F paradigm files are named
    5F-Subject<X>-Session<Y>-<date>.mat (5F-...-HFREQ at 1000 Hz).

    Structure: variable `o` with fields sampFreq, data (nS x 22, uV), marker
    (nS x 1) and chnames (22 names, the last is the X5 sync channel).
    Marker codes in 5F: 1..5 = thumb..pinky, 0 = blank/rest,
    91/92/93/99 = breaks and session start/end.

    Returns (data[n_ch, n], fs, ch_names, labels[n]).
    """
    from scipy.io import loadmat

    mat = loadmat(path, squeeze_me=True, struct_as_record=False)
    o = mat["o"]
    fs = float(o.sampFreq)
    data = np.asarray(o.data, dtype=float).T
    names = [str(n).strip() for n in np.atleast_1d(o.chnames)]
    marker = np.asarray(o.marker).astype(int).ravel()

    keep = [i for i, n in enumerate(names) if not n.upper().startswith("X")]
    data = data[keep]
    names = [names[i] for i in keep]

    labels = np.full(marker.shape, IGNORE, dtype=int)
    labels[marker == 0] = REST
    for code in range(1, 6):
        labels[marker == code] = code
    return data, fs, names, labels


def kaya_training_labels(labels: np.ndarray, fs: float, start_s: float = 0.25, len_s: float = 1.0,
                         rest_guard_s: float = 1.0) -> np.ndarray:
    """
    Kaya 5F cues last only ~1.3 s, so training windows are taken at a fixed
    offset from each cue onset (default 0.25-1.25 s) instead of over the
    marker span. Rest samples within `rest_guard_s` after a cue ends are
    dropped because post-movement rebound would blur the rest class.
    """
    labels = np.asarray(labels).astype(int)
    out = np.where(labels == REST, REST, IGNORE)
    is_finger = (labels >= 1) & (labels <= 5)
    edges = np.flatnonzero(np.diff(is_finger.astype(int))) + 1
    for e in edges:
        if is_finger[e]:  # onset
            a, b = e + int(start_s * fs), e + int((start_s + len_s) * fs)
            out[e:a] = IGNORE
            out[a:b] = labels[e]
        else:  # offset
            out[e:e + int(rest_guard_s * fs)] = np.where(out[e:e + int(rest_guard_s * fs)] == REST, IGNORE,
                                                         out[e:e + int(rest_guard_s * fs)])
    out[is_finger & (out == REST)] = IGNORE
    return out


def save_recording(path: str, data: np.ndarray, fs: float, ch_names: Sequence[str],
                   labels: Optional[np.ndarray] = None) -> None:
    """Save a session in HANDMOVE's .npz format (playable by ReplaySource)."""
    np.savez_compressed(path, data=data, fs=fs, ch_names=np.array(list(ch_names)),
                        labels=labels if labels is not None else np.zeros(0, dtype=int))


def load_recording(path: str):
    if path.lower().endswith(".mat"):
        return load_kaya_mat(path)
    z = np.load(path, allow_pickle=False)
    labels = z["labels"] if "labels" in z and z["labels"].size else None
    return z["data"], float(z["fs"]), [str(c) for c in z["ch_names"]], labels


def pick_channels(ch_names: Sequence[str], wanted: Sequence[str]) -> List[int]:
    upper = [c.upper() for c in ch_names]
    return [upper.index(w.upper()) for w in wanted if w.upper() in upper]


class ReplaySource(_PacedSource):
    """
    Replays a recording as if it were a live headset.

    montage: None to keep all channels, 8 or 16 to emulate that headset size
    using MONTAGE_8 / MONTAGE_16, or an explicit list of channel names.
    """

    def __init__(self, path: str, montage=None, loop: bool = True, start_s: float = 0.0, **kw):
        super().__init__(**kw)
        data, fs, names, labels = load_recording(path)
        if montage is not None:
            wanted = {8: MONTAGE_8, 16: MONTAGE_16}.get(montage, montage)
            idx = pick_channels(names, wanted)
            if not idx:
                raise ValueError(f"None of {list(wanted)} found in {names}")
            data, names = data[idx], [names[i] for i in idx]
        self.data = data
        self.labels = labels
        self.loop = loop
        self._pos = int(start_s * fs)
        self.info = SourceInfo(f"Replay: {path.replace(chr(92), '/').split('/')[-1]}", fs, names,
                               has_labels=labels is not None)

    def read(self) -> Chunk:
        n = self._due()
        if n == 0:
            return _empty(self.info.n_channels, self.info.has_labels)
        total = self.data.shape[1]
        if self._pos >= total and not self.loop:
            self._emitted += n
            return _empty(self.info.n_channels, self.info.has_labels)
        idx = (np.arange(self._pos, self._pos + n) % total) if self.loop else np.arange(self._pos, min(total, self._pos + n))
        self._pos += len(idx)
        self._emitted += n
        return Chunk(self.data[:, idx], self.labels[idx] if self.labels is not None else None)

    def seek(self, sample: int) -> None:
        self._pos = max(0, min(int(sample), self.data.shape[1] - 1))

    @property
    def finished(self) -> bool:
        return not self.loop and self._pos >= self.data.shape[1]


# =============================================================================
# BrainFlow (OpenBCI and many others)
# =============================================================================

BRAINFLOW_BOARDS = {
    "OpenBCI Cyton (8 ch)": "CYTON_BOARD",
    "OpenBCI Cyton + Daisy (16 ch)": "CYTON_DAISY_BOARD",
    "OpenBCI Cyton WiFi (8 ch)": "CYTON_WIFI_BOARD",
    "OpenBCI Cyton + Daisy WiFi (16 ch)": "CYTON_DAISY_WIFI_BOARD",
    "OpenBCI Ganglion (4 ch)": "GANGLION_BOARD",
    "BrainFlow synthetic board": "SYNTHETIC_BOARD",
}


class BrainFlowSource(EEGSource):
    """
    Live data through BrainFlow (pip install brainflow).

    board: a key of BRAINFLOW_BOARDS, a BoardIds name such as "CYTON_BOARD",
           or an integer board id.
    serial_port: e.g. "COM3" for the Cyton USB dongle (find it in Device Manager).
    """

    def __init__(self, board="OpenBCI Cyton (8 ch)", serial_port: str = "", ip_address: str = "",
                 ip_port: int = 0, ch_names: Optional[Sequence[str]] = None):
        from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams

        if isinstance(board, str):
            board = BRAINFLOW_BOARDS.get(board, board)
            board_id = getattr(BoardIds, board).value
        else:
            board_id = int(board)
        params = BrainFlowInputParams()
        params.serial_port = serial_port
        params.ip_address = ip_address
        params.ip_port = ip_port
        BoardShim.disable_board_logger()
        self._BoardShim = BoardShim
        self.board_id = board_id
        self.board = BoardShim(board_id, params)
        self.eeg_rows = BoardShim.get_eeg_channels(board_id)
        fs = BoardShim.get_sampling_rate(board_id)
        n = len(self.eeg_rows)
        if ch_names is None:
            try:
                ch_names = BoardShim.get_eeg_names(board_id)
            except Exception:
                ch_names = None
            if not ch_names or len(ch_names) != n:
                ch_names = (OPENBCI_16 if n > 8 else OPENBCI_8)[:n] + [f"Ch{i + 1}" for i in range(16, n)]
        self.info = SourceInfo(f"BrainFlow {BoardIds(board_id).name}", fs, list(ch_names)[:n])

    def start(self) -> None:
        self.board.prepare_session()
        self.board.start_stream(45000)

    def stop(self) -> None:
        try:
            if self.board.is_prepared():
                self.board.stop_stream()
                self.board.release_session()
        except Exception:
            pass

    def read(self) -> Chunk:
        raw = self.board.get_board_data()
        if raw.size == 0:
            return _empty(self.info.n_channels, False)
        return Chunk(np.asarray(raw[self.eeg_rows], dtype=float))


# =============================================================================
# Lab Streaming Layer
# =============================================================================

class LSLSource(EEGSource):
    """
    Reads the first LSL stream matching `stream_type` (default "EEG") or `name`.
    Many vendors publish LSL streams natively or through a small app: OpenBCI
    GUI (Networking widget -> LSL, "TimeSeries"), Emotiv, g.tec Unicorn,
    BrainVision, Muse (muselsl), Neurosity, and others.
    """

    def __init__(self, stream_type: str = "EEG", name: str = "", timeout: float = 5.0):
        import pylsl

        self._pylsl = pylsl
        prop, value = ("name", name) if name else ("type", stream_type)
        streams = pylsl.resolve_byprop(prop, value, timeout=timeout)
        if not streams:
            raise RuntimeError(f"No LSL stream with {prop}={value!r} found within {timeout:.0f} s")
        si = streams[0]
        self.inlet = pylsl.StreamInlet(si, max_buflen=60, processing_flags=pylsl.proc_clocksync)
        try:
            si = self.inlet.info(timeout=timeout)  # full header, includes channel labels
        except Exception:
            pass
        n = si.channel_count()
        names = []
        try:
            ch = si.desc().child("channels").child("channel")
            for _ in range(n):
                names.append(ch.child_value("label") or "")
                ch = ch.next_sibling()
        except Exception:
            names = []
        if len(names) != n or not all(names):
            names = [f"Ch{i + 1}" for i in range(n)]
        fs = si.nominal_srate() or 250.0
        self.info = SourceInfo(f"LSL {si.name()}", fs, names)

    def start(self) -> None:
        self.inlet.open_stream(timeout=5.0)

    def stop(self) -> None:
        try:
            self.inlet.close_stream()
        except Exception:
            pass

    def read(self) -> Chunk:
        samples, _ = self.inlet.pull_chunk(timeout=0.0, max_samples=4096)
        if not samples:
            return _empty(self.info.n_channels, False)
        return Chunk(np.asarray(samples, dtype=float).T)

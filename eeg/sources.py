#   HANDMOVE - EEG Bridge (sources)
#        Oumar Ibrahim U22200741

# all the eeg inputs are here, every source gives back a Chunk
# Chunk.data is (channels, samples) in microvolts and labels is the
# true class for each sample (only replay and synthetic know this)
#
# BrainFlowSource - openbci cyton / daisy / ganglion and other brainflow boards
# LSLSource - any headset that sends a lab streaming layer stream
# ReplaySource - plays a recording file (kaya 2018 5F .mat or our .npz)
# SyntheticSource - fake eeg so we can test without a headset

import time

import numpy as np

# labels used by every source and the decoder
REST = 0
FINGER_LABELS = {0: "rest", 1: "thumb", 2: "index", 3: "middle", 4: "ring", 5: "pinky"}
IGNORE = -1  # samples that are not any class (breaks etc)

# electrodes to use when we want to act like a 8 or 16 channel headset
# motor cortex ones first
MONTAGE_8 = ["C3", "Cz", "C4", "F3", "F4", "P3", "Pz", "P4"]
MONTAGE_16 = MONTAGE_8 + ["Fz", "T3", "T4", "Fp1", "Fp2", "O1", "O2", "F7"]
# default openbci cyton/daisy electrode names from there docs
OPENBCI_8 = ["Fp1", "Fp2", "C3", "C4", "P7", "P8", "O1", "O2"]
OPENBCI_16 = OPENBCI_8 + ["F7", "F8", "F3", "F4", "T7", "T8", "P3", "P4"]


class Chunk:
    def __init__(self, data, labels=None):
        self.data = data  # (channels, samples)
        self.labels = labels  # (samples,) or None


class SourceInfo:
    def __init__(self, name, fs, ch_names, has_labels=False, extra=None):
        self.name = name
        self.fs = fs
        self.ch_names = ch_names
        self.has_labels = has_labels
        if extra is None:
            extra = {}
        self.extra = extra
        self.n_channels = len(ch_names)


class EEGSource:
    # base class, read() should not block it just returns what there is

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def read(self):
        raise NotImplementedError

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


def empty_chunk(n_ch, with_labels):
    if with_labels:
        return Chunk(np.zeros((n_ch, 0)), np.zeros(0, dtype=int))
    else:
        return Chunk(np.zeros((n_ch, 0)), None)


#==============================================================================
# base for file and synthetic sources, gives out fs * speed samples per second
# if realtime is False every read gives one block right away (for the tests)


class PacedSource(EEGSource):
    def __init__(self, realtime=True, speed=1.0, block=32):
        self.realtime = realtime
        self.speed = speed
        self.block = block
        self._t0 = 0.0
        self._emitted = 0
        self._running = False

    def start(self):
        self._t0 = time.perf_counter()
        self._emitted = 0
        self._running = True

    def stop(self):
        self._running = False

    def _due(self):
        if not self._running:
            return 0
        if not self.realtime:
            return self.block
        elapsed = time.perf_counter() - self._t0
        target = int(elapsed * self.info.fs * self.speed)
        n = target - self._emitted
        if n < 0:
            n = 0
        return n


# Synthetic source
# noise + 10 Hz mu and 20ish Hz beta on all channels. when a finger is
# imagined the rythm gets smaller on a channel pattern for that finger
# (thats basically what real motor imagery does)
# the class follows a cue schedule (cue_s on, rest_s off) unless set_intent is used


class SyntheticSource(PacedSource):
    def __init__(self, n_channels=8, fs=250.0, classes=(1, 2, 3, 4, 5), cue_s=4.0,
                 rest_s=2.0, seed=None, erd_depth=0.2, **kw):
        PacedSource.__init__(self, **kw)
        if n_channels > 8:
            names = OPENBCI_16[:n_channels]
        else:
            names = OPENBCI_8[:n_channels]
        for i in range(len(names), n_channels):
            names.append("Ch" + str(i + 1))
        self.info = SourceInfo("Synthetic EEG", fs, names, has_labels=True)
        self.rng = np.random.default_rng(seed)
        self.classes = list(classes)
        self.cue_n = int(cue_s * fs)
        self.rest_n = int(rest_s * fs)
        self.erd_depth = erd_depth
        self._manual_intent = None
        self._sample = 0
        self._pink_state = np.zeros(n_channels)

        # the fake "person": phases and finger patterns are always the same
        # only the noise uses seed, so a model from one run works on the next
        pattern_rng = np.random.default_rng(1234)
        self._phase = pattern_rng.uniform(0, 2 * np.pi, (n_channels, 2))
        self.patterns = {}
        for c in range(0, 6):
            w = pattern_rng.uniform(0.0, 1.0, n_channels) ** 2
            self.patterns[c] = w / w.max()
        self.patterns[REST] = np.zeros(n_channels)

    def set_intent(self, label):
        # None means go back to the cue schedule
        self._manual_intent = label

    def _scheduled_label(self, idx):
        period = self.cue_n + self.rest_n
        trial = idx // period
        within = idx % period
        cls_arr = np.array(self.classes)
        cls = cls_arr[trial % len(self.classes)]
        return np.where(within < self.rest_n, REST, cls)

    def read(self):
        n = self._due()
        if n == 0:
            return empty_chunk(self.info.n_channels, True)
        fs = self.info.fs
        idx = np.arange(self._sample, self._sample + n)
        if self._manual_intent is not None:
            labels = np.full(n, self._manual_intent)
        else:
            labels = self._scheduled_label(idx)
        t = idx / fs
        n_ch = self.info.n_channels

        # pink-ish noise, white noise into a leaky integrater
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
            pat = self.patterns[int(c)]
            gain[:, mask] -= self.erd_depth * pat[:, None]
        mu = 10.0 * np.sin(2 * np.pi * 10.0 * t + self._phase[:, :1])
        beta = 4.0 * np.sin(2 * np.pi * 21.0 * t + self._phase[:, 1:])
        data = 2.0 * pink + gain * (mu + beta)
        data = data + self.rng.normal(0, 2.0, (n_ch, n))

        self._sample += n
        self._emitted += n
        return Chunk(data, labels.astype(int))


#==============================================================================
# Replay source (Kaya 2018 5F .mat and our .npz)


# loads one file from Kaya et al 2018 sci data 5:180211 (figshare 3917698)
# files are 5F-Subject<X>-Session<Y>-<date>.mat, HFREQ ones are 1000 Hz
# the .mat has a struct o with sampFreq, data (nS x 22), marker and chnames
# last channel X5 is just sync so we drop it
# markers: 1..5 = thumb..pinky  0 = rest  91/92/93/99 = breaks and session codes
# returns data (ch, n), fs, names, labels
def load_kaya_mat(path):
    from scipy.io import loadmat

    mat = loadmat(path, squeeze_me=True, struct_as_record=False)
    o = mat["o"]
    fs = float(o.sampFreq)
    data = np.asarray(o.data, dtype=float).T
    names = []
    for nm in np.atleast_1d(o.chnames):
        names.append(str(nm).strip())
    marker = np.asarray(o.marker).astype(int).ravel()

    keep = []
    for i in range(len(names)):
        if not names[i].upper().startswith("X"):
            keep.append(i)
    data = data[keep]
    new_names = []
    for i in keep:
        new_names.append(names[i])
    names = new_names

    labels = np.full(marker.shape, IGNORE, dtype=int)
    labels[marker == 0] = REST
    for code in range(1, 6):
        labels[marker == code] = code
    return data, fs, names, labels


# kaya cues are only about 1.3 s long so we take the training part at a fixed
# time after the cue starts (0.25 to 1.25 s) and not the whole marker
# rest right after a cue is dropped for rest_guard_s because of the rebound
def kaya_training_labels(labels, fs, start_s=0.25, len_s=1.0, rest_guard_s=1.0):
    labels = np.asarray(labels).astype(int)
    out = np.where(labels == REST, REST, IGNORE)
    is_finger = (labels >= 1) & (labels <= 5)
    edges = np.flatnonzero(np.diff(is_finger.astype(int))) + 1
    guard = int(rest_guard_s * fs)
    for e in edges:
        if is_finger[e]:
            # cue starts
            a = e + int(start_s * fs)
            b = e + int((start_s + len_s) * fs)
            out[e:a] = IGNORE
            out[a:b] = labels[e]
        else:
            # cue ends
            part = out[e:e + guard]
            out[e:e + guard] = np.where(part == REST, IGNORE, part)
    out[is_finger & (out == REST)] = IGNORE
    return out


# saves a session as .npz so ReplaySource can play it
def save_recording(path, data, fs, ch_names, labels=None):
    if labels is None:
        labels = np.zeros(0, dtype=int)
    np.savez_compressed(path, data=data, fs=fs, ch_names=np.array(list(ch_names)), labels=labels)


def load_recording(path):
    if path.lower().endswith(".mat"):
        return load_kaya_mat(path)
    z = np.load(path, allow_pickle=False)
    labels = None
    if "labels" in z:
        if z["labels"].size:
            labels = z["labels"]
    names = []
    for c in z["ch_names"]:
        names.append(str(c))
    return z["data"], float(z["fs"]), names, labels


def pick_channels(ch_names, wanted):
    upper = []
    for c in ch_names:
        upper.append(c.upper())
    idx = []
    for w in wanted:
        if w.upper() in upper:
            idx.append(upper.index(w.upper()))
    return idx


# plays a recording like it is a live headset
# montage: None = keep all, 8 or 16 = use MONTAGE_8 / MONTAGE_16,
# or a list of channel names
class ReplaySource(PacedSource):
    def __init__(self, path, montage=None, loop=True, start_s=0.0, **kw):
        PacedSource.__init__(self, **kw)
        data, fs, names, labels = load_recording(path)
        if montage is not None:
            if montage == 8:
                wanted = MONTAGE_8
            elif montage == 16:
                wanted = MONTAGE_16
            else:
                wanted = montage
            idx = pick_channels(names, wanted)
            if len(idx) == 0:
                raise ValueError(f"None of {list(wanted)} found in {names}")
            data = data[idx]
            picked = []
            for i in idx:
                picked.append(names[i])
            names = picked
        self.data = data
        self.labels = labels
        self.loop = loop
        self._pos = int(start_s * fs)
        file_name = path.replace("\\", "/").split("/")[-1]
        self.info = SourceInfo("Replay: " + file_name, fs, names, has_labels=labels is not None)

    def read(self):
        n = self._due()
        if n == 0:
            return empty_chunk(self.info.n_channels, self.info.has_labels)
        totl = self.data.shape[1]
        if self._pos >= totl and not self.loop:
            self._emitted += n
            return empty_chunk(self.info.n_channels, self.info.has_labels)
        if self.loop:
            idx = np.arange(self._pos, self._pos + n) % totl
        else:
            end = self._pos + n
            if end > totl:
                end = totl
            idx = np.arange(self._pos, end)
        self._pos += len(idx)
        self._emitted += n
        if self.labels is not None:
            return Chunk(self.data[:, idx], self.labels[idx])
        else:
            return Chunk(self.data[:, idx], None)

    def seek(self, sample):
        pos = int(sample)
        if pos > self.data.shape[1] - 1:
            pos = self.data.shape[1] - 1
        if pos < 0:
            pos = 0
        self._pos = pos

    def is_finished(self):
        if not self.loop and self._pos >= self.data.shape[1]:
            return True
        return False


#==============================================================================
# BrainFlow (openbci and lots of others)

BRAINFLOW_BOARDS = {
    "OpenBCI Cyton (8 ch)": "CYTON_BOARD",
    "OpenBCI Cyton + Daisy (16 ch)": "CYTON_DAISY_BOARD",
    "OpenBCI Cyton WiFi (8 ch)": "CYTON_WIFI_BOARD",
    "OpenBCI Cyton + Daisy WiFi (16 ch)": "CYTON_DAISY_WIFI_BOARD",
    "OpenBCI Ganglion (4 ch)": "GANGLION_BOARD",
    "BrainFlow synthetic board": "SYNTHETIC_BOARD",
}


# live data with brainflow (pip install brainflow)
# board can be a name from BRAINFLOW_BOARDS, a BoardIds name like "CYTON_BOARD"
# or a number. serial_port is like "COM3" for the cyton dongle
class BrainFlowSource(EEGSource):
    def __init__(self, board="OpenBCI Cyton (8 ch)", serial_port="", ip_address="",
                 ip_port=0, ch_names=None):
        from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams

        if isinstance(board, str):
            if board in BRAINFLOW_BOARDS:
                board = BRAINFLOW_BOARDS[board]
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
                if n > 8:
                    ch_names = OPENBCI_16[:n]
                else:
                    ch_names = OPENBCI_8[:n]
                for i in range(16, n):
                    ch_names.append("Ch" + str(i + 1))
        self.info = SourceInfo("BrainFlow " + BoardIds(board_id).name, fs, list(ch_names)[:n])

    def start(self):
        self.board.prepare_session()
        self.board.start_stream(45000)

    def stop(self):
        try:
            if self.board.is_prepared():
                self.board.stop_stream()
                self.board.release_session()
        except Exception:
            pass

    def read(self):
        raw = self.board.get_board_data()
        if raw.size == 0:
            return empty_chunk(self.info.n_channels, False)
        return Chunk(np.asarray(raw[self.eeg_rows], dtype=float))


#==============================================================================
# Lab Streaming Layer
# reads the first lsl stream with this type (default "EEG") or name
# lots of headsets can send lsl: openbci gui (networking -> LSL timeseries),
# emotiv, unicorn, brainvision, muse (muselsl) and more


class LSLSource(EEGSource):
    def __init__(self, stream_type="EEG", name="", timeout=5.0):
        import pylsl

        self._pylsl = pylsl
        if name:
            prop = "name"
            value = name
        else:
            prop = "type"
            value = stream_type
        streams = pylsl.resolve_byprop(prop, value, timeout=timeout)
        if not streams:
            raise RuntimeError(f"No LSL stream with {prop}={value!r} found within {timeout:.0f} s")
        si = streams[0]
        self.inlet = pylsl.StreamInlet(si, max_buflen=60, processing_flags=pylsl.proc_clocksync)
        try:
            # full header has the channel labels
            si = self.inlet.info(timeout=timeout)
        except Exception:
            pass
        n = si.channel_count()
        names = []
        try:
            ch = si.desc().child("channels").child("channel")
            for k in range(n):
                lbl = ch.child_value("label")
                if not lbl:
                    lbl = ""
                names.append(lbl)
                ch = ch.next_sibling()
        except Exception:
            names = []
        all_named = True
        for nm in names:
            if not nm:
                all_named = False
        if len(names) != n or not all_named:
            names = []
            for i in range(n):
                names.append("Ch" + str(i + 1))
        fs = si.nominal_srate()
        if not fs:
            fs = 250.0
        self.info = SourceInfo("LSL " + si.name(), fs, names)

    def start(self):
        self.inlet.open_stream(timeout=5.0)

    def stop(self):
        try:
            self.inlet.close_stream()
        except Exception:
            pass

    def read(self):
        samples, stamps = self.inlet.pull_chunk(timeout=0.0, max_samples=4096)
        if not samples:
            return empty_chunk(self.info.n_channels, False)
        return Chunk(np.asarray(samples, dtype=float).T)

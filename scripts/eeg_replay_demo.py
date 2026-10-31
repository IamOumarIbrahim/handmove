"""
Watch the hand move from recorded EEG, with no headset and no hardware.

    python scripts/eeg_replay_demo.py
    python scripts/eeg_replay_demo.py --classes "Rest / Thumb / Index" --electrodes 8

1. Opens the normal GUI with "Simulate" ticked, so nothing goes to a real hand.
2. Opens the EEG panel and replays a Kaya 2018 5F recording from data/kaya5F.
3. Trains the decoder on the first two thirds of that recording.
4. Replays the unseen last third and drives the 3D hand from the decoder.
"""

import argparse
import glob
import os
import sys
import tkinter as tk
from tkinter import filedialog

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import gui_legacy  # noqa: E402
from eeg.panel import CLASS_SETS, SOURCE_TYPES, EEGPanel  # noqa: E402


def default_file() -> str:
    preferred = os.path.join(ROOT, "data", "kaya5F", "5F-SubjectC-151204-5St-SGLHand.mat")
    if os.path.exists(preferred):
        return preferred
    files = sorted(glob.glob(os.path.join(ROOT, "data", "kaya5F", "5F-*.mat")), key=lambda f: "HFREQ" in f)
    if not files:
        sys.exit("No Kaya 5F .mat files found in data/kaya5F")
    return files[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=None, help="recording to replay (default: a 200 Hz Kaya 5F file)")
    ap.add_argument("--classes", default="Rest vs Thumb", choices=list(CLASS_SETS))
    ap.add_argument("--electrodes", default="16", choices=["8", "16", "All"])
    ap.add_argument("--speed", default="1", choices=["1", "2", "5"])
    args = ap.parse_args()
    path = args.file or default_file()
    print(f"Replaying {path}", flush=True)

    root = tk.Tk()
    app = gui_legacy.LegacyHandGUI(root)
    app.sim_var.set(True)              # tick "Simulate" before the GUI auto-connects
    app.ctrl.simulation_mode = True

    def start():
        panel = EEGPanel(root, controller=app.ctrl, title="EEG Bridge (replay demo)")
        sw = panel.win.winfo_screenwidth()
        panel.win.geometry(f"+{max(0, sw - 775)}+10")   # keep the 3D hand visible
        panel.src_type.set(SOURCE_TYPES[1])
        panel._on_source_type()
        panel.replay_path.set(path)
        panel.replay_montage.set(args.electrodes)
        panel.replay_speed.set(args.speed)
        panel.class_set.set(args.classes)
        panel.notch.set("50 Hz")
        panel._connect()
        state = {"step": "connect"}

        def skip_to_next_cue():
            src = panel.bridge.source
            labels = getattr(src, "labels", None)
            if labels is None:
                return
            pos = src._pos
            cues = [i for i in range(pos, len(labels)) if 1 <= labels[i] <= 5][:1]
            if cues:
                src._pos = max(pos, cues[0] - int(2 * src.info.fs))

        def advance():
            if not panel.win.winfo_exists():
                return
            if state["step"] == "connect" and panel.bridge is not None:
                state["step"] = "train"
                original = filedialog.askopenfilename
                filedialog.askopenfilename = lambda **kw: path
                try:
                    panel._train_file()
                finally:
                    filedialog.askopenfilename = original
            elif state["step"] == "train" and panel.bridge.decoder is not None:
                state["step"] = "drive"
                skip_to_next_cue()
                panel._apply_mapper_settings()
                panel._toggle_drive()
                panel.win.after(1000, lambda: print(panel.model_info.cget("text"), flush=True))
                print("Driving the simulated hand from the replayed EEG.", flush=True)
                return
            panel.win.after(250, advance)

        panel.win.after(250, advance)

    root.after(600, start)
    root.mainloop()


if __name__ == "__main__":
    main()

"""
Run the EEG Bridge on its own:  python -m eeg [--sim]

Without --sim it connects to the hand with the saved settings (same as the
GUI). With --sim the hand is simulated, which is handy for trying the decoder.
"""

import argparse
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from controller import HandController  # noqa: E402
from eeg.panel import EEGPanel  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="HANDMOVE EEG Bridge")
    ap.add_argument("--sim", action="store_true", help="simulate the hand instead of connecting to it")
    args = ap.parse_args()
    ctrl = HandController(simulation_mode=args.sim, transport="serial" if args.sim else None)
    if not args.sim:
        ok, msg = ctrl.connect()
        print(("Connected: " if ok else "Hand not connected: ") + msg)
    ctrl.on_log = lambda d, t: print(f"[{d}] {t}") if d in ("ERR", "SYS") else None
    root = tk.Tk()
    root.withdraw()
    EEGPanel(root, controller=ctrl, title="HANDMOVE EEG Bridge", on_close=lambda: (ctrl.disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()

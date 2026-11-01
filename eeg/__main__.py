#   HANDMOVE - EEG Bridge (run on its own)
#        Oumar Ibrahim U22200741

# run just the eeg bridge:  python -m eeg [--sim]
# without --sim it connects to the hand with the saved settings (same as the gui)
# with --sim the hand is simulated, good for trying the decoder

import argparse
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from controller import HandController  # noqa: E402
from eeg.panel import EEGPanel  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="HANDMOVE EEG Bridge")
    ap.add_argument("--sim", action="store_true", help="simulate the hand instead of connecting to it")
    args = ap.parse_args()
    if args.sim:
        ctrl = HandController(simulation_mode=args.sim, transport="serial")
    else:
        ctrl = HandController(simulation_mode=args.sim, transport=None)
    if not args.sim:
        ok, msg = ctrl.connect()
        if ok:
            print("Connected: " + msg)
        else:
            print("Hand not connected: " + msg)

    # only print errors and system messages
    def print_log(d, t):
        if d == "ERR" or d == "SYS":
            print(f"[{d}] {t}")

    ctrl.on_log = print_log
    root = tk.Tk()
    root.withdraw()

    def close_all():
        ctrl.disconnect()
        root.destroy()

    EEGPanel(root, controller=ctrl, title="HANDMOVE EEG Bridge", on_close=close_all)
    root.mainloop()


if __name__ == "__main__":
    main()

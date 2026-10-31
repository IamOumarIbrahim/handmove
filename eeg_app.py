"""
Launch the HANDMOVE GUI together with the EEG Bridge panel.

    python main.py --gui --eeg

The EEG panel is a separate window that drives the GUI's own HandController,
so sliders and the hand view follow whatever the EEG decoder commands.
gui_legacy.py is used as-is.
"""

import tkinter as tk
from typing import Optional

import gui_legacy
from connection_settings import load_connection_settings
from eeg.panel import EEGPanel


def launch_gui_with_eeg(port: Optional[str] = None, baud: Optional[int] = None,
                        transport: Optional[str] = None) -> None:
    root = tk.Tk()
    defaults = load_connection_settings()
    app = gui_legacy.LegacyHandGUI(
        root,
        default_port=defaults["port"] if port is None else port,
        default_baud=defaults["baudrate"] if baud is None else baud,
    )
    if transport in ("ble", "serial"):
        app.ctrl.transport = transport
        app.transport_var.set("Bluetooth LE" if transport == "ble" else "Serial UART")
        app._on_transport_changed()

    panel = {"p": None}

    def open_panel():
        if panel["p"] is not None and panel["p"].win.winfo_exists():
            panel["p"].win.lift()
            return
        panel["p"] = EEGPanel(root, controller=app.ctrl)

    # Add an "EEG" menu to the existing menu bar without editing gui_legacy.py
    menubar = root.nametowidget(root["menu"])
    eeg_menu = tk.Menu(menubar, tearoff=0)
    eeg_menu.add_command(label="Open EEG Bridge...", command=open_panel)
    menubar.add_cascade(label="EEG", menu=eeg_menu)

    # E-STOP in the main window also stops EEG control before going neutral.
    def estop():
        p = panel["p"]
        if p is not None and p.win.winfo_exists():
            p.stop_all_control()
        app._on_estop_clicked()

    app.btn_estop.config(command=estop)

    original_close = app._close_application

    def close_all():
        p = panel["p"]
        if p is not None and p.win.winfo_exists():
            p.close()
        original_close()

    root.protocol("WM_DELETE_WINDOW", close_all)
    root.after(400, open_panel)
    root.mainloop()


if __name__ == "__main__":
    launch_gui_with_eeg()

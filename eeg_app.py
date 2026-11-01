#   HANDMOVE - GUI with the EEG panel
#        Oumar Ibrahim U22200741

# starts the HANDMOVE gui together with the EEG Bridge panel
#     python main.py --gui --eeg
# the eeg panel is a second window that uses the gui's own HandController
# so the sliders and the hand view follow what the decoder sends
# gui_legacy.py is used as it is

import tkinter as tk

import gui_legacy
from connection_settings import load_connection_settings
from eeg.panel import EEGPanel


def launch_gui_with_eeg(port=None, baud=None, transport=None):
    root = tk.Tk()
    defaults = load_connection_settings()
    if port is None:
        port = defaults["port"]
    if baud is None:
        baud = defaults["baudrate"]
    app = gui_legacy.LegacyHandGUI(root, default_port=port, default_baud=baud)
    if transport == "ble" or transport == "serial":
        app.ctrl.transport = transport
        if transport == "ble":
            app.transport_var.set("Bluetooth LE")
        else:
            app.transport_var.set("Serial UART")
        app._on_transport_changed()

    panel = {"p": None}

    def open_panel():
        if panel["p"] is not None and panel["p"].win.winfo_exists():
            panel["p"].win.lift()
            return
        panel["p"] = EEGPanel(root, controller=app.ctrl)

    # add a "EEG" menu to the menu bar without changing gui_legacy.py
    menubar = root.nametowidget(root["menu"])
    eeg_menu = tk.Menu(menubar, tearoff=0)
    eeg_menu.add_command(label="Open EEG Bridge...", command=open_panel)
    menubar.add_cascade(label="EEG", menu=eeg_menu)

    # E-STOP in the main window stops the eeg control too before going neutral
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

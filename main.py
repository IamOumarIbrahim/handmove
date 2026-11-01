#   HANDMOVE - uHand UNO Controller (launcher)
#        Oumar Ibrahim U22200741

# one launcher for the uHand UNO controller
# can start the tkinter gui or the menu in the terminal
# hiwonder BLE is the default connection

import argparse
import os
import sys

# make sure the HANDMOVE folder is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from connection_settings import load_connection_settings


def main():
    parser = argparse.ArgumentParser(
        description="uHand UNO Robotic Hand Controller Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --gui               Launch GUI (saved Hiwonder BLE device is the default)
  python main.py --cli               Launch menu-based terminal interface
  python main.py --gui --transport serial --port COM5   Use a serial UART adapter
  python main.py --cli --sim         Run terminal menu in offline simulation mode
  python main.py --gui --eeg         Launch GUI plus the EEG Bridge panel
        """
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-g", "--gui", action="store_true", help="Launch Legacy Tkinter Graphical Interface")
    group.add_argument("-c", "--cli", "--terminal", action="store_true", help="Launch Menu-Based Terminal")

    defaults = load_connection_settings()
    default_port = defaults["port"]
    if not default_port:
        default_port = None
    parser.add_argument("-p", "--port", type=str, default=default_port,
                        help="Serial COM port (used when --transport serial)")
    parser.add_argument("--transport", choices=["ble", "serial"], default=defaults["transport"],
                        help="Connection transport (default: saved setting; normally BLE)")
    parser.add_argument("-b", "--baud", type=int, default=defaults["baudrate"],
                        help="Baud rate (documented uHand UNO default: 9600)")
    parser.add_argument("-s", "--sim", "--simulation", action="store_true", help="Force offline simulation mode")
    parser.add_argument("--eeg", action="store_true", help="Open the EEG Bridge panel next to the GUI")

    args = parser.parse_args()
    selected_port = args.port
    if not selected_port:
        selected_port = ""

    # what we are connecting to (for the messages)
    if args.transport == "serial":
        if selected_port:
            target = f"{selected_port} at {args.baud} baud"
        else:
            target = f"select COM port at {args.baud} baud"
    else:
        target = "Hiwonder BLE"

    # pick the mode
    if args.eeg and not args.cli:
        from eeg_app import launch_gui_with_eeg
        print("Launching GUI with the EEG Bridge panel...")
        launch_gui_with_eeg(port=selected_port, baud=args.baud, transport=args.transport)
    elif args.cli:
        from terminal_menu import TerminalMenuApp
        print(f"Starting uHand UNO Terminal Menu via {target}...")
        app = TerminalMenuApp(port=selected_port, baudrate=args.baud, simulation=args.sim, transport=args.transport)
        app.run()
    elif args.gui:
        import gui_legacy
        print(f"Launching Legacy Tkinter Graphical Interface via {target}...")
        gui_legacy.launch_gui(port=selected_port, baud=args.baud, transport=args.transport)
    else:
        # no flag given so ask in the console
        if args.transport == "serial":
            if selected_port:
                shown = "Serial " + selected_port
            else:
                shown = "Serial COM port"
        else:
            shown = "Hiwonder Bluetooth LE"
        print("=" * 64)
        print("   uHand UNO Robotic Hand Controller Suite [Reverse-Engineer]")
        print(f"   Target: {shown} | Baud Rate: {args.baud}")
        print("=" * 64)
        print("  [1] Launch Legacy Tkinter Graphical Interface (Recommended)")
        print("  [2] Launch Menu-Based Interactive Terminal")
        print("  [0] Exit")
        print("-" * 64)

        try:
            choice = input("Select interface [1/2, default 1]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            return

        if choice == "2" or choice == "cli" or choice == "c":
            from terminal_menu import TerminalMenuApp
            app = TerminalMenuApp(port=selected_port, baudrate=args.baud, simulation=args.sim, transport=args.transport)
            app.run()
        elif choice == "0" or choice == "q" or choice == "exit":
            print("Exiting.")
        else:
            import gui_legacy
            gui_legacy.launch_gui(port=selected_port, baud=args.baud, transport=args.transport)


if __name__ == "__main__":
    main()

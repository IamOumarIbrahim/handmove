"""
Unified Launcher for uHand UNO Robotic Hand Controller Suite.
Supports launching either the legacy Tkinter Graphical Interface or the
Menu-Based Interactive Terminal. Hiwonder BLE is the default connection transport.
"""

import argparse
import os
import sys

# Ensure HANDMOVE directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from connection_settings import load_connection_settings


def main() -> None:
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
    parser.add_argument(
        "-p", "--port", type=str, default=defaults["port"] or None,
        help="Serial COM port (used when --transport serial)"
    )
    parser.add_argument(
        "--transport", choices=["ble", "serial"], default=defaults["transport"],
        help="Connection transport (default: saved setting; normally BLE)"
    )
    parser.add_argument(
        "-b", "--baud", type=int, default=defaults["baudrate"],
        help="Baud rate (documented uHand UNO default: 9600)"
    )
    parser.add_argument("-s", "--sim", "--simulation", action="store_true", help="Force offline simulation mode")
    parser.add_argument("--eeg", action="store_true", help="Open the EEG Bridge panel next to the GUI")

    args = parser.parse_args()
    selected_port = args.port or ""

    # Determine mode
    if args.eeg and not args.cli:
        from eeg_app import launch_gui_with_eeg
        print("Launching GUI with the EEG Bridge panel...")
        launch_gui_with_eeg(port=selected_port, baud=args.baud, transport=args.transport)
    elif args.cli:
        from terminal_menu import TerminalMenuApp
        target = f"{selected_port or 'select COM port'} at {args.baud} baud" if args.transport == "serial" else "Hiwonder BLE"
        print(f"Starting uHand UNO Terminal Menu via {target}...")
        app = TerminalMenuApp(port=selected_port, baudrate=args.baud, simulation=args.sim, transport=args.transport)
        app.run()
    elif args.gui:
        import gui_legacy
        target = f"{selected_port or 'select COM port'} at {args.baud} baud" if args.transport == "serial" else "Hiwonder BLE"
        print(f"Launching Legacy Tkinter Graphical Interface via {target}...")
        gui_legacy.launch_gui(port=selected_port, baud=args.baud, transport=args.transport)
    else:
        # If neither flag specified, present quick console selection
        print("=" * 64)
        print("   uHand UNO Robotic Hand Controller Suite [Reverse-Engineer]")
        print(f"   Target: {'Serial ' + (selected_port or 'COM port') if args.transport == 'serial' else 'Hiwonder Bluetooth LE'} | Baud Rate: {args.baud}")
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

        if choice in ("2", "cli", "c"):
            from terminal_menu import TerminalMenuApp
            app = TerminalMenuApp(port=selected_port, baudrate=args.baud, simulation=args.sim, transport=args.transport)
            app.run()
        elif choice in ("0", "q", "exit"):
            print("Exiting.")
        else:
            import gui_legacy
            gui_legacy.launch_gui(port=selected_port, baud=args.baud, transport=args.transport)


if __name__ == "__main__":
    main()

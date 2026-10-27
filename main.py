"""
Unified Launcher for uHand UNO Robotic Hand Controller Suite.
Supports launching either the legacy Tkinter Graphical Interface or the
Menu-Based Interactive Terminal. Default target port is COM3.
"""

import argparse
import os
import sys

# Ensure HANDMOVE directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="uHand UNO Robotic Hand Controller Suite (COM3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --gui               Launch legacy Tkinter GUI (Default: COM3)
  python main.py --cli               Launch menu-based terminal interface
  python main.py --gui --port COM3   Specify COM3 explicitly
  python main.py --cli --sim         Run terminal menu in offline simulation mode
        """
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-g", "--gui", action="store_true", help="Launch Legacy Tkinter Graphical Interface")
    group.add_argument("-c", "--cli", "--terminal", action="store_true", help="Launch Menu-Based Terminal")

    parser.add_argument("-p", "--port", type=str, default="COM3", help="Serial COM Port (default: COM3)")
    parser.add_argument("-b", "--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("-s", "--sim", "--simulation", action="store_true", help="Force offline simulation mode")

    args = parser.parse_args()

    # Determine mode
    if args.cli:
        from terminal_menu import TerminalMenuApp
        print(f"Starting uHand UNO Terminal Menu on {args.port} (Baud: {args.baud})...")
        app = TerminalMenuApp(port=args.port, baudrate=args.baud, simulation=args.sim)
        app.run()
    elif args.gui:
        import gui_legacy
        print(f"Launching Legacy Tkinter Graphical Interface on {args.port}...")
        gui_legacy.launch_gui(port=args.port, baud=args.baud)
    else:
        # If neither flag specified, present quick console selection
        print("=" * 64)
        print("   uHand UNO Robotic Hand Controller Suite [Reverse-Engineer]")
        print(f"   Target Port: {args.port} | Baud Rate: {args.baud}")
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
            app = TerminalMenuApp(port=args.port, baudrate=args.baud, simulation=args.sim)
            app.run()
        elif choice in ("0", "q", "exit"):
            print("Exiting.")
        else:
            import gui_legacy
            gui_legacy.launch_gui(port=args.port, baud=args.baud)


if __name__ == "__main__":
    main()

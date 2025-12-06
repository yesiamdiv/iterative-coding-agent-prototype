# ============================================================================
# Main Entry Point
# ============================================================================

from tkinter import messagebox
from app_gui import AppGUI


if __name__ == "__main__":
    try:
        app = AppGUI()
        app.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        messagebox.showerror("Fatal Error", str(e))
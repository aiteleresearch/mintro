"""MINTRO-Setup.exe: installs MINTRO for the current user in one step, then opens it."""
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from mintro import __version__, installer

BG, INK, MUTED, MINT = "#0d0e10", "#f3f4f6", "#8b9099", "#3ddc97"


def payload() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "MINTRO.zip"


def main() -> None:
    root = tk.Tk()
    root.title("MINTRO Setup")
    root.configure(bg=BG)
    root.resizable(False, False)
    w, h = 440, 190
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 2}")
    try:
        root.iconbitmap(str(Path(getattr(sys, "_MEIPASS", ".")) / "mintro.ico"))
    except tk.TclError:
        pass

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("M.Horizontal.TProgressbar", troughcolor="#1f2124", background=MINT, bordercolor=BG,
                    lightcolor=MINT, darkcolor=MINT, thickness=6)

    tk.Label(root, text="MINTRO", font=("Segoe UI Semibold", 15), fg=INK, bg=BG).place(x=28, y=24)
    tk.Label(root, text=f"version {__version__}", font=("Segoe UI", 9), fg=MUTED, bg=BG).place(x=122, y=32)
    status = tk.Label(root, text="Getting ready…", font=("Segoe UI", 10), fg=MUTED, bg=BG, anchor="w")
    status.place(x=28, y=74, width=384)
    bar = ttk.Progressbar(root, style="M.Horizontal.TProgressbar", maximum=100, length=384)
    bar.place(x=28, y=104)
    note = tk.Label(root, text="Installs for you only, no admin needed. Your data stays in %LOCALAPPDATA%\\MINTRO.",
                    font=("Segoe UI", 8), fg=MUTED, bg=BG, anchor="w", wraplength=384, justify="left")
    note.place(x=28, y=130, width=384)

    def report(pct, text):
        root.after(0, lambda: (bar.configure(value=pct), status.configure(text=text)))

    def work():
        try:
            exe = installer.install(payload(), report)
            report(100, "Installed. Opening MINTRO…")
            import subprocess
            subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
            root.after(1800, root.destroy)
        except Exception as e:  # show the reason and let the person close the window
            root.after(0, lambda: (status.configure(text=f"Setup failed: {e}", fg="#ff7b6f"),
                                   tk.Button(root, text="Close", command=root.destroy, relief="flat", bg="#1f2124",
                                             fg=INK, activebackground="#2a2d31").place(x=352, y=148, width=60)))

    root.after(300, lambda: threading.Thread(target=work, daemon=True).start())
    root.mainloop()


if __name__ == "__main__":
    main()

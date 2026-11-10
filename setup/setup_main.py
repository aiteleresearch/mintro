"""MINTRO-Setup.exe: installs MINTRO for the current user, then opens it.

    MINTRO-Setup.exe            the setup window: welcome, progress, ready (WebView2; a plain window without it)
    MINTRO-Setup.exe --auto     the same window, but it starts installing straight away
    MINTRO-Setup.exe --silent   no window at all, for scripted installs; exit code 0 when installed
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

from mintro import __version__, installer

BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
LINKS = {"terms": f"{installer.WEBSITE}/terms.html", "privacy": f"{installer.WEBSITE}/privacy.html",
         "help": f"{installer.WEBSITE}/contact.html"}


def payload() -> Path:
    return BUNDLE / "MINTRO.zip"


def launch(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


def keep_desktop_choice(asked: bool) -> bool:
    """On an update the window doesn't ask; keep a desktop shortcut only if there is one."""
    return installer.desktop_shortcut().exists() if installer.installed_version() else asked


# ---- the setup window (HTML in WebView2) ----------------------------------------------------------------

class Api:
    """What the setup page (installer.html) can call through window.pywebview.api."""

    def __init__(self, auto: bool):
        self._window = None
        self._auto = auto
        self._busy = False
        self._scale = None

    def set_scale(self, ratio) -> None:
        """The page's pixel ratio (display scaling times Windows' text size). The window is sized to give the
        page its full design size at that ratio; this corrects the first guess, made from the display's DPI."""
        try:
            ratio = min(max(float(ratio), 0.5), 4.0)
        except (TypeError, ValueError):
            return
        if self._scale is None or abs(ratio - self._scale) > 0.01:
            self._scale = ratio
            _fit(self._window, ratio, center=False)

    def info(self) -> dict:
        size = 0  # the unpacked size of the app, a fair guide to what it takes on disk
        try:
            import zipfile
            with zipfile.ZipFile(payload()) as z:
                size = sum(i.file_size for i in z.infolist())
        except OSError:
            pass
        return {"version": __version__, "installed": installer.installed_version(),
                "size_mb": round(size / 1e6) if size else None, "auto": self._auto}

    def install(self, options: dict) -> None:
        if self._busy:
            return
        self._busy = True
        options = options or {}
        threading.Thread(target=self._work, args=(bool(options.get("desktop", True)), bool(options.get("launch", True))),
                         daemon=True).start()

    def _work(self, desktop: bool, open_after: bool) -> None:
        def report(pct, text):
            self._js(f"setProgress({float(pct)}, {json.dumps(text)})")
        try:
            exe = installer.install(payload(), report, desktop=keep_desktop_choice(desktop))
        except Exception as e:  # shown on the page, with Try again
            self._busy = False
            self._js(f"failed({json.dumps(str(e) or e.__class__.__name__)})")
            return
        self._busy = False
        if open_after:
            launch(exe)
        self._js(f"installed({json.dumps(open_after)})")
        if open_after:  # MINTRO is opening: step out of its way
            threading.Timer(4.0, self.close).start()

    def launch(self) -> None:
        launch(installer.EXE)

    def open_url(self, name: str) -> None:
        import webbrowser
        if name in LINKS:
            webbrowser.open(LINKS[name])

    def minimize(self) -> None:
        self._window.minimize()

    def close(self) -> None:
        if self._window is not None and not self._busy:  # never mid-install
            self._window.destroy()

    def _js(self, code: str) -> None:
        try:
            self._window.evaluate_js(code)
        except Exception:
            pass


def run_window(auto: bool) -> None:
    import webview
    api = Api(auto)
    page = (BUNDLE / "installer.html").read_text(encoding="utf-8")
    window = webview.create_window("MINTRO Setup", html=page, js_api=api, width=W, height=H, resizable=False,
                                   frameless=True, easy_drag=False, background_color="#0b0c0e")
    api._window = window  # private: pywebview would otherwise walk the whole native window to expose it to the page
    window.events.before_show += lambda: _fit(window)  # runs on the window's thread, before anyone sees it
    window.events.shown += lambda: _round_corners(window)
    webview.start(gui="edgechromium", private_mode=True)  # WebView2 only: never the old IE engine


W, H = 700, 470  # installer.html's design size, in CSS pixels


def _text_scale() -> float:
    """Windows' text size (Settings > Accessibility > Text size), which WebView2 adds to the display scaling."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
            return max(1.0, int(winreg.QueryValueEx(key, "TextScaleFactor")[0]) / 100)
    except (OSError, ValueError):
        return 1.0


def _fit(window, scale: float | None = None, center: bool = True) -> None:
    """Size the window in physical pixels so the page gets its whole W x H design at this display's scaling.

    pywebview sizes a frameless window as if it had a frame and leaves out the scaling, so at 112% the page
    got 612 x 386 of its 700 x 470 and was cut off. On a screen too small for the full size, the window
    takes the screen's work area and the page scales its design down to fit (installer.html).
    """
    form = getattr(window, "native", None)
    if form is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        hwnd = ctypes.c_void_p(form.Handle.ToInt64())
        if scale is None:
            scale = (user32.GetDpiForWindow(hwnd) or 96) / 96 * _text_scale()
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(ctypes.c_void_p(user32.MonitorFromWindow(hwnd, 2)), ctypes.byref(info))  # nearest
        work = info.rcWork
        w = min(round(W * scale), work.right - work.left)
        h = min(round(H * scale), work.bottom - work.top)
        if center:
            x, y = work.left + (work.right - work.left - w) // 2, work.top + (work.bottom - work.top - h) // 2
        else:  # a correction once shown: grow around the window's centre, staying on screen
            b = form.Bounds
            x, y = b.X + (b.Width - w) // 2, b.Y + (b.Height - h) // 2
        x = min(max(work.left, x), work.right - w)
        y = min(max(work.top, y), work.bottom - h)

        from System import Action
        from System.Drawing import Rectangle
        from System.Windows.Forms import FormStartPosition

        def apply():
            form.StartPosition = FormStartPosition.Manual  # or WinForms re-centres it at the old size on Show
            form.Bounds = Rectangle(int(x), int(y), int(w), int(h))

        if form.InvokeRequired:
            form.Invoke(Action(apply))
        else:
            apply()
    except Exception:
        pass  # pywebview's own size; the page still scales its design to fit


def _round_corners(window) -> None:
    """Windows 11 rounds frameless windows only when asked."""
    try:
        import ctypes
        hwnd = window.native.Handle.ToInt64()
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass


# ---- the plain window (no WebView2 on this PC) ------------------------------------------------------------

def run_plain() -> None:
    import tkinter as tk
    from tkinter import ttk
    bg, ink, muted, mint = "#0d0e10", "#f3f4f6", "#8b9099", "#3ddc97"
    root = tk.Tk()
    root.title("MINTRO Setup")
    root.configure(bg=bg)
    root.resizable(False, False)
    w, h = 440, 190
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 2}")
    try:
        root.iconbitmap(str(BUNDLE / "mintro.ico"))
    except tk.TclError:
        pass
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("M.Horizontal.TProgressbar", troughcolor="#1f2124", background=mint, bordercolor=bg,
                    lightcolor=mint, darkcolor=mint, thickness=6)
    tk.Label(root, text="MINTRO", font=("Segoe UI Semibold", 15), fg=ink, bg=bg).place(x=28, y=24)
    tk.Label(root, text=f"version {__version__}", font=("Segoe UI", 9), fg=muted, bg=bg).place(x=122, y=32)
    status = tk.Label(root, text="Getting ready…", font=("Segoe UI", 10), fg=muted, bg=bg, anchor="w")
    status.place(x=28, y=74, width=384)
    bar = ttk.Progressbar(root, style="M.Horizontal.TProgressbar", maximum=100, length=384)
    bar.place(x=28, y=104)
    tk.Label(root, text="Installs for you only, no admin needed. Your data stays in %LOCALAPPDATA%\\MINTRO.",
             font=("Segoe UI", 8), fg=muted, bg=bg, anchor="w", wraplength=384, justify="left").place(x=28, y=130, width=384)

    def report(pct, text):
        root.after(0, lambda: (bar.configure(value=pct), status.configure(text=text)))

    def work():
        try:
            exe = installer.install(payload(), report, desktop=keep_desktop_choice(True))
            report(100, "Installed. Opening MINTRO…")
            launch(exe)
            root.after(1800, root.destroy)
        except Exception as e:
            root.after(0, lambda: (status.configure(text=f"Setup failed: {e}", fg="#ff7b6f"),
                                   tk.Button(root, text="Close", command=root.destroy, relief="flat", bg="#1f2124",
                                             fg=ink, activebackground="#2a2d31").place(x=352, y=148, width=60)))

    root.after(300, lambda: threading.Thread(target=work, daemon=True).start())
    root.mainloop()


def run_silent() -> int:
    try:
        installer.install(payload(), desktop=keep_desktop_choice(True))
        return 0
    except Exception as e:
        print(f"MINTRO setup failed: {e}", file=sys.stderr)
        return 1


def main() -> None:
    if "--silent" in sys.argv:
        sys.exit(run_silent())
    try:
        run_window(auto="--auto" in sys.argv)
    except Exception:  # no WebView2 runtime, or pywebview couldn't start: the plain window still installs
        run_plain()


if __name__ == "__main__":
    main()

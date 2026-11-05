"""MINTRO desktop card: a small frameless, always-on-top window. Without pywebview it opens in the browser."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import os
import sys
import webbrowser

from . import server, store, wallets

PORT = 8777
W, H, COMPACT_H = 360, 640, 64
MARGIN = 16

log = logging.getLogger("mintro.app")


class CardApi:
    """Methods the card page can call through window.pywebview.api."""

    def __init__(self, base_url: str, compact: bool):
        self._base = base_url
        self._compact = compact
        self._window = None
        self._scale: float | None = None  # the page's devicePixelRatio, once it reports it

    def is_compact(self) -> bool:
        return self._compact

    def compact(self, on: bool) -> bool:
        on = bool(on)
        log.info("card asks compact=%s (currently %s)", on, self._compact)
        if on != self._compact:
            self._compact = on
            _fit(self._window, COMPACT_H if on else H, keep_bottom=True, scale=self._scale)
            _save_position(on, self._scale)
        return self._compact

    def set_scale(self, ratio: float) -> None:
        """The page's pixel ratio: display scaling times Windows' text size (Settings > Accessibility).

        The card is designed for 360 x 640 CSS pixels, so the window grows with the ratio instead of
        squeezing the layout; it grows up and to the left so it stays in its corner.
        """
        ratio = min(max(float(ratio), 0.5), 4.0)
        if self._scale is None or abs(ratio - self._scale) > 0.01:
            self._scale = ratio
            log.info("card pixel ratio %.2f", ratio)
            _fit(self._window, COMPACT_H if self._compact else H, keep_bottom=True, keep_right=True, scale=ratio)
            _save_position(self._compact, ratio)

    def close(self) -> None:
        self._window.destroy()

    def open_url(self, url: str) -> None:
        if isinstance(url, str) and url.startswith("https://"):
            log.info("opening %s in the browser", url)
            webbrowser.open(url)

    def open_report(self) -> None:
        webbrowser.open(self._base)

    def open_folder(self, name: str) -> None:
        folder = {"wallets": wallets.WALLETS, "data": store.DATA, "mintro": store.ROOT}.get(name)
        if folder:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)

    def open_security(self) -> None:
        os.startfile("windowsdefender://threat/")  # Windows Security > Protection history


def main() -> None:
    store.DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=store.DATA / "mintro.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if server.already_running(PORT):
        _bring_to_front()
        return
    try:
        import webview
    except ImportError:
        log.warning("pywebview not installed; opening the card in the browser")
        server.run(PORT, open_browser=True, page="card")
        return

    httpd, app, url = server.start(PORT)
    x, y, compact, scale = _initial_position()
    api = CardApi(url, compact)
    api._scale = scale
    window = webview.create_window(
        "MINTRO", url + "card", js_api=api, width=W, height=H, x=x, y=max(_work_area().top, y + (COMPACT_H - H) * compact),
        frameless=True, easy_drag=False, on_top=True, resizable=False, shadow=True, background_color="#0d0e10",
        min_size=(W, COMPACT_H),
    )
    api._window = window
    app.start_updates(window.destroy)
    window.events.shown += lambda: _on_shown(window, api, x, y)
    # Coming back from minimized: re-apply the size, which also wakes the web view up
    window.events.restored += lambda: _fit(window, COMPACT_H if api._compact else H, scale=api._scale)
    window.events.moved += lambda *args: _save_position(api._compact, api._scale)
    try:
        # A kept profile makes the web view start much faster than a fresh private one each launch
        webview.start(private_mode=False, storage_path=str(store.DATA / "webview"))
    finally:
        app.engine.shutdown()
        app.gpu_engine.shutdown()
        app.bench.stop()
        wallets.stop_all()
        httpd.shutdown()


def _on_shown(window, api: CardApi, x: int, y: int) -> None:
    try:
        _fit(window, COMPACT_H if api._compact else H, x=x, y=y, scale=api._scale)
        _round_corners()
    except Exception:
        log.exception("couldn't size the card window")


def _initial_position() -> tuple[int, int, bool, float | None]:
    """Last saved top-left, mode and pixel ratio if the card still fits there; else the bottom-right corner."""
    area = _work_area()
    saved = store.load("window.json") or {}
    compact = bool(saved.get("compact"))
    scale = saved.get("scale") if isinstance(saved.get("scale"), (int, float)) else None
    x, y = saved.get("x"), saved.get("y")
    w, h = round(W * (scale or 1)), round((COMPACT_H if compact else H) * (scale or 1))
    if not (isinstance(x, int) and isinstance(y, int)
            and area.left <= x <= area.right - w and area.top <= y <= area.bottom - h):
        x, y = area.right - w - MARGIN, area.bottom - h - MARGIN
    return x, y, compact, scale


def _save_position(compact: bool, scale: float | None) -> None:
    rect = _rect()
    if rect:
        store.save("window.json", {"x": rect.left, "y": rect.top, "compact": compact, "scale": scale})


def _work_area() -> wt.RECT:
    """The screen minus the taskbar."""
    area = wt.RECT(0, 0, 1920, 1080)
    if os.name == "nt":
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
    return area


def _find_window(own: bool = True) -> int:
    """The card's window: titled MINTRO and created by this process (or, for another instance, by WinForms)."""
    if os.name != "nt":
        return 0
    user32, found = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        title, cls, pid = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(64), wt.DWORD()
        user32.GetWindowTextW(hwnd, title, 64)
        if title.value == "MINTRO":
            user32.GetClassNameW(hwnd, cls, 64)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if (pid.value == os.getpid()) if own else cls.value.startswith("WindowsForms"):
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else 0


def _rect():
    hwnd = _find_window()
    rect = wt.RECT()
    if hwnd and ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect
    return None


def _fit(window, height: int, keep_bottom: bool = False, keep_right: bool = False,
         x: int | None = None, y: int | None = None, scale: float | None = None) -> None:
    """Give the card its exact size, inside the screen area above the taskbar.

    The size is set through the WinForms form on its own UI thread. Resizing the window behind WinForms'
    back (SetWindowPos from another thread) gets undone on the next restore or layout pass, and its web
    view stays docked to the stale size.
    """
    hwnd, rect, form = _find_window(), _rect(), getattr(window, "native", None)
    if not (rect and form):
        log.warning("card window not found; size left to pywebview")
        return
    if scale is None:  # until the page reports its pixel ratio, go by the display's DPI
        try:
            scale = (ctypes.windll.user32.GetDpiForWindow(hwnd) or 96) / 96
        except AttributeError:
            scale = 1.0
    w, h = round(W * scale), round(height * scale)
    if x is None or y is None:
        x = rect.right - w if keep_right else rect.left
        y = rect.bottom - h if keep_bottom else rect.top
    area = _work_area()
    x = min(max(area.left, x), area.right - w)
    y = min(max(area.top, y), area.bottom - h)

    from System import Action  # pythonnet, loaded by pywebview
    from System.Drawing import Rectangle

    def apply():
        form.Bounds = Rectangle(int(x), int(y), int(w), int(h))

    if form.InvokeRequired:
        form.Invoke(Action(apply))
    else:
        apply()
    log.info("card window %dx%d at %d,%d (scale %.2f)", w, h, x, y, scale)


def _round_corners() -> None:
    """Windows 11 doesn't round frameless windows by itself; ask the compositor to."""
    hwnd = _find_window()
    if not hwnd:
        return
    try:
        pref = ctypes.c_int(2)  # DWMWA_WINDOW_CORNER_PREFERENCE (33) = DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except (AttributeError, OSError):
        pass  # older Windows: square corners


def _bring_to_front() -> None:
    hwnd = _find_window(own=False)
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)


def run() -> None:
    """Entry point for MINTRO.bat and the installed MINTRO.exe."""
    try:
        main()
    except Exception:
        logging.getLogger("mintro.app").exception("card failed; falling back to the browser")
        server.run(PORT, open_browser=True, page="card")
    sys.exit(0)


if __name__ == "__main__":
    run()

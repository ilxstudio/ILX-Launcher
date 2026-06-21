"""
docs/_capture.py — one-off screenshot harness for the user manual.

Opens each launcher window, lets it render, and captures THAT WINDOW'S region to
docs/img/<name>.png via a PowerShell .NET screen grab. Throwaway tooling, not shipped.

Run from the project root:  python docs/_capture.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "img")
os.makedirs(IMG, exist_ok=True)

# Load launcher.py as a module without running __main__.
spec = importlib.util.spec_from_file_location("launcher", os.path.join(ROOT, "launcher.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

import tkinter as tk


def _grab_region(x: int, y: int, w: int, h: int, path: str) -> bool:
    """Capture a screen rectangle to a PNG via PowerShell .NET."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        f"$bmp=New-Object System.Drawing.Bitmap {w},{h};"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        f"$g.CopyFromScreen({x},{y},0,0,(New-Object System.Drawing.Size({w},{h})));"
        f"$bmp.Save('{path}');$g.Dispose();$bmp.Dispose()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    return r.returncode == 0 and os.path.exists(path)


def capture_window(build_fn, name: str, settle_frames: int = 12, pre=None) -> None:
    """Open a launcher window via build_fn (which calls mainloop), render a few frames,
    grab its region, then close it. `pre` runs after the first render (e.g. open a tab)."""
    out = os.path.join(IMG, name + ".png")
    state = {"n": 0}
    real_mainloop = tk.Tk.mainloop

    def fake_mainloop(self, *a, **k):
        # Bring to front so the capture isn't occluded.
        try:
            self.lift(); self.attributes("-topmost", True)
        except tk.TclError:
            pass
        for _ in range(settle_frames):
            self.update_idletasks(); self.update()
            time.sleep(0.05)
        if pre is not None:
            try:
                pre(self)
            except Exception as e:        # noqa: BLE001
                print("  pre() error:", e)
            for _ in range(8):
                self.update_idletasks(); self.update()
                time.sleep(0.05)
        self.update_idletasks(); self.update()
        time.sleep(0.3)
        x, y = self.winfo_rootx(), self.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        # Include a little title-bar margin (Windows title bar ~ 31px) and border.
        ok = _grab_region(max(0, x - 8), max(0, y - 39), w + 16, h + 47, out)
        print(f"  {name}.png  {'OK' if ok else 'FAILED'}  ({w}x{h})")
        self.destroy()

    tk.Tk.mainloop = fake_mainloop
    try:
        build_fn()
    finally:
        tk.Tk.mainloop = real_mainloop


def _select_tab(win, index):
    """Select a notebook tab by index inside a window (for multi-tab captures)."""
    from tkinter import ttk

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, ttk.Notebook):
                c.select(index)
                return True
            if walk(c):
                return True
        return False
    walk(win)


def main() -> int:
    print("Capturing launcher windows to docs/img/ ...")
    capture_window(m.run, "main_window")
    capture_window(m.run_config, "config_llm")
    capture_window(m.run_config, "config_build",
                   pre=lambda w: _select_tab(w, 1))
    capture_window(m.run_config, "config_behavior",
                   pre=lambda w: _select_tab(w, 2))
    capture_window(m.run_config, "config_watchdog",
                   pre=lambda w: _select_tab(w, 3))
    capture_window(m.run_coder, "coder")
    capture_window(m.run_deps, "deps")
    capture_window(m.run_quality, "quality")
    capture_window(m.run_git, "git")
    capture_window(m.run_profile, "profile")
    capture_window(m.run_logs, "logs")
    capture_window(m.run_crashes, "crashes")
    capture_window(m.run_automation, "automation")
    capture_window(m.run_runconfigs, "runconfigs")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

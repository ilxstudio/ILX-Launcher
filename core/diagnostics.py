from __future__ import annotations

import datetime
import os
import shutil
import subprocess

import core.state as s
from core.interpreter import interp_has_module, tool_python
from core.process import proj_run


def screenshot(reason: str = "manual") -> str:
    ts   = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(s._HERE, f"screenshot-{reason}-{ts}.png")
    try:
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
            "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
            "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
            "$g=[System.Drawing.Graphics]::FromImage($bmp);"
            "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
            f"$bmp.Save('{path}');$g.Dispose();$bmp.Dispose()"
        )
        rc, _ = proj_run(["powershell", "-NoProfile", "-Command", ps], timeout=20)
        return path if os.path.exists(path) else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def pyspy_available() -> bool:
    if shutil.which("py-spy") is not None:
        return True
    py = tool_python()
    return bool(py) and interp_has_module(py, "py_spy")


def pyspy_dump(pid: int) -> str:
    exe = shutil.which("py-spy")
    if exe:
        cmd = [exe, "dump", "--pid", str(pid)]
    else:
        py = tool_python()
        if not py:
            return "py-spy unavailable (no real Python in this frozen build)"
        cmd = [py, "-m", "py_spy", "dump", "--pid", str(pid)]
    rc, out = proj_run(cmd, timeout=30)
    return out.strip() or f"(py-spy exited {rc} - may need Administrator on Windows)"

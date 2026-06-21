from __future__ import annotations

import datetime
import os
import subprocess

import core.state as s


def notify(title: str, message: str) -> None:
    if not s._config.get("notify", True):
        return
    title   = title.replace("'", " ")
    message = message.replace("'", " ")[:120]
    ps = (
        "[reflection.assembly]::LoadWithPartialName('System.Windows.Forms') > $null;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Warning;$n.Visible=$true;"
        f"$n.ShowBalloonTip(5000,'{title}','{message}',"
        "[System.Windows.Forms.ToolTipIcon]::Warning);Start-Sleep -Seconds 5;$n.Dispose()"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=s._NO_WINDOW)
    except OSError:
        pass

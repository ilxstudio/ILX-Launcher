from __future__ import annotations

import os
import sys
import threading
import time

import tkinter as tk
from tkinter import ttk

import core.state as s
from core.automation import request_tests
from core.build import build_exe, build_installer
from core.config import apply_config, load_config, load_recents, reload_config_if_changed
from core.interpreter import interp_label, project_python
from core.process import (
    check_backdoor, check_for_changes, is_running, jump_to_crash, restart,
    source_files, start_with_deps, stop,
)
from ui.theme import (
    build_traffic_light, card, make_code_text, set_lamp, set_readonly, stat_row, style_theme,
)


# --- Sub-window launchers -----------------------------------------------------

def _open_tool(flag: str) -> None:
    try:
        import subprocess
        subprocess.Popen(
            [sys.executable, s._SELF, flag, "--project", s._HERE],
            cwd=s._HERE, creationflags=s._NO_WINDOW)
    except OSError as e:
        print(f"[launcher] could not open {flag}: {e}")


def _open_coder():      _open_tool("--coder")
def _open_config():     _open_tool("--config")
def _open_deps():       _open_tool("--deps")
def _open_quality():    _open_tool("--quality")
def _open_git():        _open_tool("--git")
def _open_profile():    _open_tool("--profile")
def _open_runconfigs(): _open_tool("--runconfigs")
def _open_logs():       _open_tool("--logs")
def _open_crashes():    _open_tool("--crashes")
def _open_automation(): _open_tool("--automation")


def _open_folder() -> None:
    try:
        import subprocess
        subprocess.Popen(["explorer", s._HERE], creationflags=s._NO_WINDOW)
    except OSError:
        pass


# --- REPL window (Toplevel — shares this process) -----------------------------

def _open_repl_window(parent: tk.Tk) -> None:
    from core.repl import repl_eval
    if s._ui.get("repl_win") is not None:
        try:
            s._ui["repl_win"].lift()
            return
        except tk.TclError:
            pass
    win = tk.Toplevel(parent)
    win.title("ILX Live REPL")
    win.geometry("760x520")
    win.configure(bg=s._C_BG)
    s._ui["repl_win"] = win
    outer = ttk.Frame(win, padding=12); outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Live REPL", style="Title.TLabel").pack(anchor="w")
    ttk.Label(outer, text="Run Python inside the RUNNING app. Needs the REPL hook wired "
              "(Configuration > Copy REPL hook) and the app started.",
              style="Lbl.TLabel", wraplength=720).pack(anchor="w", pady=(0, 8))
    transcript = make_code_text(outer, readonly=True, height=18)
    transcript.configure(font=(s._MONO, 9))
    inrow = ttk.Frame(outer); inrow.pack(fill="x", pady=(6, 0))
    ttk.Label(inrow, text=">>>", style="Lbl.TLabel").pack(side="left", padx=(0, 4))
    code = tk.StringVar()
    entry = ttk.Entry(inrow, textvariable=code, font=(s._MONO, 10))
    entry.pack(side="left", fill="x", expand=True)
    entry.focus_set()

    def send(_e=None):
        c = code.get().strip()
        if not c:
            return
        code.set("")
        transcript.configure(state="normal")
        transcript.insert("end", f">>> {c}\n")
        result = repl_eval(c)
        transcript.insert("end", result + "\n")
        transcript.see("end")
        transcript.configure(state="disabled")
    entry.bind("<Return>", send)
    ttk.Button(inrow, text="Run", style="Accent.TButton", command=send).pack(
        side="left", padx=6)

    def on_close():
        s._ui["repl_win"] = None
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)


# --- Tick helpers -------------------------------------------------------------

def _fmt_uptime(seconds: float) -> str:
    sec = int(seconds)
    h, rem = divmod(sec, 3600)
    m, s2  = divmod(rem, 60)
    return f"{h}:{m:02d}:{s2:02d}" if h else f"{m}:{s2:02d}"


def _draw_spark() -> None:
    cv = s._ui.get("spark")
    if cv is None:
        return
    cv.delete("all")
    hist = list(s._mem_hist)
    if len(hist) < 2:
        return
    lo, hi = min(hist), max(hist)
    span = (hi - lo) or 1.0
    n = len(hist)
    line_pts: list[float] = []
    for i, val in enumerate(hist):
        x = 2 + (i / (n - 1)) * (s._SPARK_W - 4)
        y = (s._SPARK_H - 3) - ((val - lo) / span) * (s._SPARK_H - 6)
        line_pts.extend((x, y))
    if len(line_pts) >= 4:
        base = s._SPARK_H - 1
        poly = [2, base] + line_pts + [s._SPARK_W - 2, base]
        cv.create_polygon(*poly, fill="#dfe8fb", outline="")
        cv.create_line(*line_pts, fill=s._C_ACCENT, width=2, capstyle="round",
                       joinstyle="round", smooth=True)


def _refresh_activity() -> None:
    cj   = s._crash_jump
    act  = s._ui["activity"]
    pbar = s._ui["pbar"]
    cbtn = s._ui["crash_btn"]
    if s._build_running:
        act.configure(text=s._build_overlay, fg=s._C_HDR)
        pbar["value"] = s._build_progress * 100
        if not pbar.winfo_ismapped():
            pbar.pack(side="left", padx=8)
    elif s._wd_msg and not is_running():
        act.configure(text=f"watchdog stopped the app: {s._wd_msg}", fg=s._C_BAD)
        if pbar.winfo_ismapped(): pbar.pack_forget()
    elif cj:
        exc = f" - {cj['exc']}" if cj.get("exc") else ""
        act.configure(text=f"crash: {cj['rel']}:{cj['line']}{exc}", fg=s._C_BAD)
        if pbar.winfo_ismapped(): pbar.pack_forget()
    elif s._last_exit not in (None, 0) and not is_running():
        act.configure(text=f"app exited with code {s._last_exit}", fg=s._C_WARN)
        if pbar.winfo_ismapped(): pbar.pack_forget()
    elif s._last_exit == 0 and not is_running():
        act.configure(text="app exited cleanly (code 0)", fg=s._C_LBL)
        if pbar.winfo_ismapped(): pbar.pack_forget()
    else:
        act.configure(text=s._build_overlay, fg=s._C_LBL)
        if pbar.winfo_ismapped(): pbar.pack_forget()
    if cj and not cbtn.winfo_ismapped():
        cbtn.pack(side="left", padx=(0, 6), before=s._ui["activity"])
    elif not cj and cbtn.winfo_ismapped():
        cbtn.pack_forget()


# --- Main tick ----------------------------------------------------------------

def _tick(root: tk.Tk) -> None:
    st = s._stats

    if is_running():
        s._ui["stat_pid"].configure(text=str(s._child_pid))
        s._ui["stat_uptime"].configure(
            text=_fmt_uptime(time.monotonic() - (s._started_at or 0.0)))
        mem = st.get("mem_mb")
        s._ui["stat_mem"].configure(text=f"{mem:.1f} MB" if isinstance(mem, float) else "...")
        cpu = st.get("cpu_pct")
        s._ui["stat_cpu"].configure(text=f"{cpu:.0f}%" if isinstance(cpu, float) else "...")
    else:
        for k in ("stat_pid", "stat_uptime", "stat_mem", "stat_cpu"):
            s._ui[k].configure(text="--")
    s._ui["stat_reloads"].configure(text=str(max(0, s._launches - 1)))
    _draw_spark()

    s._ui["stat_files"].configure(text=str(st.get("files", "...")))
    s._ui["stat_loc"].configure(text=f"{st.get('loc', 0):,}")
    s._ui["stat_size"].configure(text=f"{st.get('size_kb', 0.0):.0f} KB")
    big_lines = int(st.get("big_lines", 0) or 0)
    big_name  = st.get("big_name", "") or "--"
    s._ui["stat_largest"].configure(
        text=f"{big_name} {big_lines}" if big_lines else "...",
        fg=(s._C_BAD if big_lines > s._MAX_FILE_LINES
            else s._C_WARN if big_lines > s._MAX_FILE_LINES * 0.8 else s._C_OK))
    s._ui["version"].configure(text=f"v{st.get('version', '')}")
    s._ui["title"].configure(text=f"{st.get('name', '')}")
    if "stat_interp" in s._ui:
        s._ui["stat_interp"].configure(text=interp_label())

    light = s._ui["light"]
    set_lamp(light, "red", s._test_state == "fail")
    set_lamp(light, "yel", s._test_state == "running")
    set_lamp(light, "grn", s._test_state == "pass")
    caption = {"running": "running...", "pass": s._test_summary, "fail": s._test_summary,
               "none": "no run yet"}.get(s._test_state, "--")
    s._ui["stat_test"].configure(text=caption)

    if is_running():
        s._ui["status"].configure(text=f"Running  .  pid {s._child_pid}", fg=s._C_OK)
        s._ui["status_dot"].configure(fg=s._C_OK)
    else:
        s._ui["status"].configure(text="Stopped", fg=s._C_BAD)
        s._ui["status_dot"].configure(fg=s._C_BAD)

    _refresh_activity()
    reload_config_if_changed()
    check_for_changes()
    check_backdoor()
    root.after(200, lambda: _tick(root))


# --- Project combo helpers ----------------------------------------------------

def _project_label(path: str) -> str:
    return f"{os.path.basename(path)}  ({path})"


def _switch_project(path: str) -> None:
    from core.config import set_project
    set_project(path)


def _on_project_combo(event=None) -> None:
    combo = s._ui.get("project_combo")
    if combo is None:
        return
    idx = combo.current()
    if 0 <= idx < len(s._combo_paths):
        new = s._combo_paths[idx]
        if new != s._HERE:
            _switch_project(new)
            _refresh_runconfig_combo()


def _refresh_runconfig_combo() -> None:
    from core.config import load_runconfigs
    combo = s._ui.get("rc_combo")
    if combo is None:
        return
    configs = load_runconfigs(s._HERE)
    names   = ["(default)"] + sorted(configs.keys())
    combo["values"] = names
    combo.set("(default)")


def _on_runconfig_combo(event=None) -> None:
    from core.config import load_runconfigs
    combo = s._ui.get("rc_combo")
    if combo is None:
        return
    name = combo.get()
    if name == "(default)":
        s._active_runconfig = None
        return
    configs = load_runconfigs(s._HERE)
    s._active_runconfig = configs.get(name)


def _browse_project() -> None:
    from tkinter import filedialog
    from core.config import is_project_dir, remember_project, set_project
    path = filedialog.askdirectory(title="Select a project folder (must contain main.py)")
    if not path or not is_project_dir(path):
        return
    remember_project(path)
    set_project(path)
    recents = load_recents()
    s._combo_paths = recents
    combo = s._ui.get("project_combo")
    if combo:
        combo["values"] = [_project_label(p) for p in recents]
        combo.set(_project_label(s._HERE))
    _refresh_runconfig_combo()


# --- Close --------------------------------------------------------------------

def _close(root: tk.Tk) -> None:
    stop()
    try:
        root.destroy()
    except tk.TclError:
        pass


# --- Main entry point ---------------------------------------------------------

def run() -> int:
    from core.automation import test_worker
    from core.process import stats_worker
    load_config()
    root = tk.Tk()
    root.title("ILX Launcher")
    root.resizable(False, False)
    style_theme(root)

    recents = load_recents()
    from core.config import is_project_dir
    from core.interpreter import load_interp_for
    if is_project_dir(s._HERE) and os.path.abspath(s._HERE) not in (
            os.path.abspath(p) for p in recents):
        recents.insert(0, s._HERE)
    s._combo_paths = recents
    s._project_interp = load_interp_for(s._HERE)

    outer = ttk.Frame(root, padding=16); outer.pack(fill="both", expand=True)

    head = ttk.Frame(outer); head.pack(fill="x")
    title = ttk.Label(head, text="...", style="Title.TLabel")
    title.pack(side="left")
    s._ui["title"] = title
    ttk.Label(head, text="live loader", style="Lbl.TLabel").pack(
        side="left", padx=(8, 0), pady=(6, 0))
    version = ttk.Label(head, text="v...", style="Ver.TLabel")
    version.pack(side="right", pady=(4, 0))
    s._ui["version"] = version

    prow = ttk.Frame(outer); prow.pack(fill="x", pady=(10, 0))
    ttk.Label(prow, text="Project", style="Lbl.TLabel").pack(side="left", padx=(0, 8))
    project_combo = ttk.Combobox(prow,
                                 values=[_project_label(p) for p in s._combo_paths],
                                 width=64, state="readonly")
    project_combo.set(_project_label(s._HERE))
    project_combo.pack(side="left", padx=(0, 8))
    project_combo.bind("<<ComboboxSelected>>", _on_project_combo)
    s._ui["project_combo"] = project_combo
    ttk.Button(prow, text="Browse", command=_browse_project).pack(side="left")
    ttk.Label(prow, text="  Run config", style="Lbl.TLabel").pack(side="left", padx=(8, 6))
    rc_combo = ttk.Combobox(prow, width=18, state="readonly")
    rc_combo.pack(side="left", padx=(0, 6))
    rc_combo.bind("<<ComboboxSelected>>", _on_runconfig_combo)
    s._ui["rc_combo"] = rc_combo
    ttk.Button(prow, text="Edit configs...", command=_open_runconfigs).pack(side="left")
    _refresh_runconfig_combo()

    cols = ttk.Frame(outer); cols.pack(fill="x", pady=(14, 0))

    c1 = ttk.Frame(cols); c1.pack(side="left", anchor="n")
    ttk.Button(c1, text="Start program", width=26, style="Accent.TButton",
               command=start_with_deps).pack(fill="x", pady=(0, 5))
    for label, cmd in (("Restart program", restart),
                       ("Refresh code", lambda: _open_tool("--refresh")),
                       ("Close launcher", lambda: _close(root))):
        ttk.Button(c1, text=label, width=26, command=cmd).pack(fill="x", pady=2)
    ttk.Frame(c1, height=10).pack()
    ttk.Button(c1, text="Coder (LLM) -- edit a file", width=26,
               command=_open_coder).pack(fill="x", pady=2)
    ttk.Button(c1, text="Configuration", width=26,
               command=_open_config).pack(fill="x", pady=2)
    ttk.Frame(c1, height=6).pack()
    trow = ttk.Frame(c1); trow.pack(fill="x")
    for label, cmd, w in (("Deps", _open_deps, 5), ("Quality", _open_quality, 7),
                          ("Git", _open_git, 4), ("Profile", _open_profile, 7),
                          ("Logs", _open_logs, 5), ("Crashes", _open_crashes, 7),
                          ("Automation", _open_automation, 10),
                          ("REPL", lambda: _open_repl_window(root), 5)):
        ttk.Button(trow, text=label, width=w, command=cmd).pack(side="left", padx=1)

    c2 = ttk.Frame(cols); c2.pack(side="left", anchor="n", padx=(16, 0))
    p2 = card(c2, "Process")
    stat_row(p2, "PID",     "stat_pid",     s._ui)
    stat_row(p2, "Uptime",  "stat_uptime",  s._ui)
    stat_row(p2, "CPU",     "stat_cpu",     s._ui)
    stat_row(p2, "Memory",  "stat_mem",     s._ui)
    spark = tk.Canvas(p2, width=s._SPARK_W, height=s._SPARK_H, bg=s._C_CARD2,
                      highlightthickness=0)
    spark.pack(anchor="w", pady=4)
    s._ui["spark"] = spark
    stat_row(p2, "Reloads", "stat_reloads", s._ui)

    c3 = ttk.Frame(cols); c3.pack(side="left", anchor="n", padx=(16, 0))
    p3 = card(c3, "Codebase")
    stat_row(p3, "Py files", "stat_files",   s._ui)
    stat_row(p3, "Lines",    "stat_loc",     s._ui)
    stat_row(p3, "Largest",  "stat_largest", s._ui)
    stat_row(p3, "Src size", "stat_size",    s._ui)
    stat_row(p3, "Python",   "stat_py",      s._ui)
    stat_row(p3, "Interp",   "stat_interp",  s._ui)
    v = sys.version_info
    s._ui["stat_py"].configure(text=f"{v.major}.{v.minor}.{v.micro}")

    c4 = ttk.Frame(cols); c4.pack(side="left", anchor="n", padx=(16, 0))
    p4 = card(c4, "Tests")
    trow2 = tk.Frame(p4, bg=s._C_CARD); trow2.pack(anchor="w")
    light = tk.Canvas(trow2, width=44, height=124, bg=s._C_CARD, highlightthickness=0)
    light.pack(side="left")
    build_traffic_light(light)
    s._ui["light"] = light
    tbtns = tk.Frame(trow2, bg=s._C_CARD); tbtns.pack(side="left", padx=(8, 0))
    ttk.Button(tbtns, text="Run tests",      width=13, command=request_tests).pack(pady=2)
    ttk.Button(tbtns, text="Open folder",    width=13, command=_open_folder).pack(pady=2)
    ttk.Button(tbtns, text="Build EXE",      width=13, command=build_exe).pack(pady=2)
    ttk.Button(tbtns, text="Build Installer",width=13, command=build_installer).pack(pady=2)
    test_lbl = tk.Label(p4, text="--", bg=s._C_CARD, fg=s._C_LBL, font=(s._FONT, 9))
    test_lbl.pack(anchor="w", pady=(6, 0))
    s._ui["stat_test"] = test_lbl

    ttk.Frame(outer, height=10).pack()
    barwrap = tk.Frame(outer, bg=s._C_BORDER); barwrap.pack(fill="x")
    bar = tk.Frame(barwrap, bg=s._C_CARD); bar.pack(fill="x", padx=1, pady=1)
    barpad = tk.Frame(bar, bg=s._C_CARD); barpad.pack(fill="x", padx=12, pady=6)
    dot = tk.Label(barpad, text="*", bg=s._C_CARD, fg=s._C_BAD, font=(s._FONT, 9))
    dot.pack(side="left", padx=(0, 6))
    s._ui["status_dot"] = dot
    status = tk.Label(barpad, text="Stopped", bg=s._C_CARD, fg=s._C_BAD,
                      font=(s._FONT, 9, "bold"))
    status.pack(side="left")
    s._ui["status"] = status
    tk.Label(barpad, text="   ", bg=s._C_CARD).pack(side="left")
    crash_btn = ttk.Button(barpad, text="Open crash", command=jump_to_crash)
    s._ui["crash_btn"] = crash_btn
    activity = tk.Label(barpad, text="idle", bg=s._C_CARD, fg=s._C_LBL, font=(s._FONT, 9))
    activity.pack(side="left")
    s._ui["activity"] = activity
    pbar = ttk.Progressbar(barpad, length=200, mode="determinate")
    s._ui["pbar"] = pbar

    s._stats_stop.clear()
    s._test_stop.clear()
    workers = [threading.Thread(target=stats_worker, daemon=True),
               threading.Thread(target=test_worker,  daemon=True)]
    for w in workers:
        w.start()

    s._ui["root"] = root
    root.attributes("-topmost", bool(s._config.get("always_on_top")))
    _tick(root)
    root.protocol("WM_DELETE_WINDOW", lambda: _close(root))
    root.mainloop()

    s._stats_stop.set()
    s._test_stop.set()
    s._manual_stop.set()
    stop()
    for w in workers:
        w.join(timeout=2)
    return 0

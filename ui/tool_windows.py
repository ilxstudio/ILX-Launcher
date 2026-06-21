from __future__ import annotations

import os
import shutil
import threading

import tkinter as tk
from tkinter import filedialog, ttk

import core.state as s
from core.automation import (
    auto_install_deps, black_format, coverage_run, matrix_test, pip_freeze,
    pip_outdated, quality_gate, quality_run, scaffold_project, sqlite_list_tables,
    sqlite_query,
)
from core.config import (
    delete_runconfig, load_config, load_runconfigs, parse_dotenv, save_runconfig,
)
from core.diagnostics import pyspy_available, pyspy_dump, screenshot
from core.process import (
    crash_history_summary, git, is_running, proj_run, stats_worker,
)
from core.automation import profile_run
from ui.theme import make_code_text, style_theme


# --- Shared tool window factory -----------------------------------------------

def _tool_window(title: str, subtitle: str, width: int = 760, height: int = 560):
    root = tk.Tk()
    root.title(title)
    root.geometry(f"{width}x{height}")
    style_theme(root)
    outer = ttk.Frame(root, padding=14); outer.pack(fill="both", expand=True)
    ttk.Label(outer, text=title,    style="Title.TLabel").pack(anchor="w")
    ttk.Label(outer, text=subtitle, style="Lbl.TLabel", wraplength=width - 40).pack(
        anchor="w", pady=(0, 8))
    bar = ttk.Frame(outer); bar.pack(fill="x")
    from core.interpreter import interp_label
    ttk.Label(outer, text=f"Project: {os.path.basename(s._HERE)}  *  {interp_label()}",
              style="Lbl.TLabel").pack(anchor="w", pady=(8, 2))
    out = make_code_text(outer, readonly=True, height=20)
    out.configure(font=(s._MONO, 9))

    def set_output(text: str) -> None:
        out.configure(state="normal")
        out.delete("1.0", "end")
        out.insert("1.0", text)
        out.configure(state="disabled")
    return root, bar, set_output


def _run_async(root: tk.Tk, set_output, fn, *, busy: str = "working...") -> None:
    set_output(busy)
    holder: dict = {}

    def work():
        try:
            holder["r"] = fn()
        except Exception as e:
            holder["r"] = f"error: {e}"
    threading.Thread(target=work, daemon=True).start()

    def poll():
        if "r" in holder:
            set_output(holder["r"])
        else:
            root.after(150, poll)
    root.after(150, poll)


def _set_text(widget: tk.Text, text: str) -> None:
    try:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
    except tk.TclError:
        pass


# --- Dependencies window -------------------------------------------------------

def run_deps() -> int:
    load_config()
    root, bar, set_output = _tool_window(
        "ILX Dependencies",
        "Install and inspect packages in this project's Python interpreter.")
    ttk.Button(bar, text="Installed",
               command=lambda: _run_async(root, set_output, pip_freeze)).pack(side="left")
    ttk.Button(bar, text="Outdated",
               command=lambda: _run_async(root, set_output, pip_outdated)).pack(
        side="left", padx=4)
    ttk.Button(bar, text="Install all requirements",
               command=lambda: _run_async(root, set_output, lambda: auto_install_deps()[1],
                                          busy="installing...")).pack(side="left", padx=4)
    con = ttk.Frame(root); con.pack(fill="x", padx=14, pady=(2, 6))
    ttk.Label(con, text="pip", style="Lbl.TLabel").pack(side="left", padx=(0, 6))
    cmd = tk.StringVar(value="install ")
    entry = ttk.Entry(con, textvariable=cmd); entry.pack(side="left", fill="x", expand=True)

    def run_pip(_e=None):
        from core.automation import pip_command
        _run_async(root, set_output, lambda: pip_command(cmd.get()),
                   busy=f"running: pip {cmd.get().strip()}...")
    entry.bind("<Return>", run_pip)
    ttk.Button(con, text="Run", style="Accent.TButton", command=run_pip).pack(
        side="left", padx=6)
    _run_async(root, set_output, pip_freeze)
    root.mainloop()
    return 0


# --- Quality window ------------------------------------------------------------

def run_quality() -> int:
    load_config()
    root, bar, set_output = _tool_window(
        "ILX Code Quality",
        "Lint, format-check, and type-check this project.")
    ttk.Button(bar, text="Ruff (lint)",
               command=lambda: _run_async(root, set_output, lambda: quality_run("ruff"),
                                          busy="running ruff...")).pack(side="left")
    ttk.Button(bar, text="Black (check)",
               command=lambda: _run_async(root, set_output, lambda: quality_run("black"),
                                          busy="running black...")).pack(side="left", padx=4)
    ttk.Button(bar, text="Black (format)",
               command=lambda: _run_async(root, set_output, black_format,
                                          busy="formatting...")).pack(side="left")
    ttk.Button(bar, text="Mypy (types)",
               command=lambda: _run_async(root, set_output, lambda: quality_run("mypy"),
                                          busy="running mypy...")).pack(side="left", padx=4)
    set_output("Pick a check above.")
    root.mainloop()
    return 0


# --- Git window ---------------------------------------------------------------

def run_git() -> int:
    load_config()
    root, bar, set_output = _tool_window(
        "ILX Git", "Quick git status and common actions for this project.", height=520)

    def status():
        rc, out  = git("status", "-sb")
        rc2, log = git("log", "-3", "--oneline")
        return f"=== status ===\n{out}\n\n=== last commits ===\n{log}"

    ttk.Button(bar, text="Refresh",
               command=lambda: _run_async(root, set_output, status)).pack(side="left")
    ttk.Button(bar, text="Pull",
               command=lambda: _run_async(root, set_output, lambda: git("pull")[1],
                                          busy="pulling...")).pack(side="left", padx=4)
    ttk.Button(bar, text="Push",
               command=lambda: _run_async(root, set_output, lambda: git("push")[1],
                                          busy="pushing...")).pack(side="left")
    crow = ttk.Frame(bar); crow.pack(side="left", padx=(12, 0))
    msg = tk.StringVar()
    ttk.Entry(crow, textvariable=msg, width=30).pack(side="left")

    def commit():
        m = msg.get().strip()
        if not m:
            return "(type a commit message first)"
        git("add", "-A")
        _, out = git("commit", "-m", m)
        return out
    ttk.Button(crow, text="Commit all",
               command=lambda: _run_async(root, set_output, commit,
                                          busy="committing...")).pack(side="left", padx=4)
    _run_async(root, set_output, status)
    root.mainloop()
    return 0


# --- Profiler window ----------------------------------------------------------

def run_profile() -> int:
    load_config()
    root, bar, set_output = _tool_window(
        "ILX Profiler",
        "Run the app under cProfile and rank functions by cumulative time.", height=600)
    ttk.Button(bar, text="Profile run (cProfile)",
               command=lambda: _run_async(root, set_output, profile_run,
                                          busy="profiling... (close the app when done)")).pack(
        side="left")

    def live_dump():
        if not pyspy_available():
            return "py-spy not installed. Run:  pip install py-spy"
        if not is_running():
            return "start the app first, then capture a live stack dump"
        return pyspy_dump(s._child_pid)
    ttk.Button(bar, text="Live stack (py-spy)",
               command=lambda: _run_async(root, set_output, live_dump,
                                          busy="dumping live stacks...")).pack(
        side="left", padx=4)
    set_output("cProfile: run the app start-to-finish and rank functions.\n"
               "py-spy: snapshot the RUNNING app's stacks right now.")
    root.mainloop()
    return 0


# --- Logs window --------------------------------------------------------------

def run_logs() -> int:
    load_config()
    root = tk.Tk()
    root.title("ILX Processes & Logs")
    root.geometry("900x640")
    style_theme(root)
    outer = ttk.Frame(root, padding=14); outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Processes & Logs", style="Title.TLabel").pack(anchor="w")
    ttk.Label(outer, text="Live output from the app and any Procfile processes.",
              style="Lbl.TLabel", wraplength=860).pack(anchor="w", pady=(0, 8))

    from core.automation import orch_start_all, orch_status, orch_stop_all
    obar = ttk.Frame(outer); obar.pack(fill="x")
    ttk.Label(obar, text="Procfile:", style="Lbl.TLabel").pack(side="left", padx=(0, 6))
    ttk.Button(obar, text="Start all", style="Accent.TButton",
               command=lambda: print("[orch]", orch_start_all())).pack(side="left")
    ttk.Button(obar, text="Stop all",
               command=lambda: print("[orch]", orch_stop_all())).pack(side="left", padx=4)
    ttk.Button(obar, text="Status",
               command=lambda: print("[orch]\n" + orch_status())).pack(side="left")

    fbar = ttk.Frame(outer); fbar.pack(fill="x", pady=(8, 4))
    ttk.Label(fbar, text="Filter", style="Lbl.TLabel").pack(side="left", padx=(0, 6))
    filt   = tk.StringVar()
    follow = tk.BooleanVar(value=True)
    ttk.Entry(fbar, textvariable=filt, width=30).pack(side="left")
    ttk.Checkbutton(fbar, text="Follow tail", variable=follow).pack(side="left", padx=10)

    def export():
        src = os.path.join(s._HERE, ".launcher_session.log")
        dst = filedialog.asksaveasfilename(defaultextension=".log",
                                           initialfile="ilx_session.log")
        if dst and os.path.exists(src):
            try:
                shutil.copy2(src, dst)
            except OSError as e:
                print(f"[logs] export failed: {e}")
    ttk.Button(fbar, text="Export session...", command=export).pack(side="left")

    txt = make_code_text(outer, readonly=True, height=26)
    txt.configure(font=(s._MONO, 9))
    txt.tag_configure("err",  foreground=s._C_BAD)
    txt.tag_configure("warn", foreground=s._C_WARN)
    txt.tag_configure("src",  foreground=s._C_ACCENT)

    state = {"shown": 0}

    def pump():
        with s._log_lock:
            lines = list(s._log_buffer)
        f    = filt.get().strip().lower()
        view = [(src, ln) for (src, ln) in lines
                if not f or f in ln.lower() or f in src.lower()]
        if len(view) != state["shown"]:
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            for src, ln in view[-s._LOG_BUFFER_MAX:]:
                low = ln.lower()
                tag = ("err"  if ("error" in low or "traceback" in low or "exception" in low)
                       else "warn" if "warn" in low else None)
                txt.insert("end", f"[{src}] ", ("src",))
                txt.insert("end", ln + "\n", (tag,) if tag else ())
            txt.configure(state="disabled")
            if follow.get():
                txt.see("end")
            state["shown"] = len(view)
        root.after(400, pump)
    pump()
    root.mainloop()
    return 0


# --- Crash history window -----------------------------------------------------

def run_crashes() -> int:
    load_config()
    root, bar, set_output = _tool_window(
        "ILX Crash History",
        "Past crashes for this project, grouped by signature.", height=560)
    ttk.Button(bar, text="Refresh",
               command=lambda: _run_async(root, set_output,
                                          crash_history_summary)).pack(side="left")

    def shot():
        p = screenshot("manual")
        return f"screenshot saved -> {p}" if p else "screenshot failed"
    ttk.Button(bar, text="Screenshot now",
               command=lambda: _run_async(root, set_output, shot,
                                          busy="capturing...")).pack(side="left", padx=4)

    def latest_log():
        log_file = os.path.join(s._HERE, "log.txt")
        try:
            with open(log_file, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return "(no log.txt yet)"
    ttk.Button(bar, text="View last log",
               command=lambda: _run_async(root, set_output, latest_log)).pack(side="left")
    _run_async(root, set_output, crash_history_summary)
    root.mainloop()
    return 0


# --- Automation window --------------------------------------------------------

def run_automation() -> int:
    load_config()
    root = tk.Tk()
    root.title("ILX Automation")
    root.geometry("820x640")
    style_theme(root)
    outer = ttk.Frame(root, padding=12); outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Automation", style="Title.TLabel").pack(anchor="w")
    nb = ttk.Notebook(outer); nb.pack(fill="both", expand=True, pady=(8, 0))

    def out_pane(parent):
        t = make_code_text(parent, readonly=True, height=18)
        t.configure(font=(s._MONO, 9))
        return t

    # Scaffold tab.
    sc = ttk.Frame(nb); nb.add(sc, text="New project")
    ttk.Label(sc, text="Create a project skeleton (main.py, version.py, tests, .env).",
              style="Lbl.TLabel", wraplength=760).pack(anchor="w", pady=6)
    srow = ttk.Frame(sc); srow.pack(fill="x")
    ttk.Label(srow, text="Name",   style="Lbl.TLabel", width=8).pack(side="left")
    sc_name = tk.StringVar()
    ttk.Entry(srow, textvariable=sc_name, width=24).pack(side="left")
    drow = ttk.Frame(sc); drow.pack(fill="x", pady=4)
    ttk.Label(drow, text="Folder", style="Lbl.TLabel", width=8).pack(side="left")
    sc_dir = tk.StringVar()
    ttk.Entry(drow, textvariable=sc_dir, width=46).pack(side="left")
    ttk.Button(drow, text="...",
               command=lambda: sc_dir.set(filedialog.askdirectory() or sc_dir.get())).pack(
        side="left", padx=4)
    sc_out = out_pane(sc)

    def do_scaffold():
        ok, msg = scaffold_project(sc_dir.get(), sc_name.get())
        _set_text(sc_out, msg)
    ttk.Button(sc, text="Create", style="Accent.TButton", command=do_scaffold).pack(
        anchor="w", pady=4)

    # Matrix tab.
    mx = ttk.Frame(nb); nb.add(mx, text="Test matrix")
    ttk.Label(mx, text="Run the test suite under several interpreters (one python.exe per line).",
              style="Lbl.TLabel", wraplength=760).pack(anchor="w", pady=6)
    from core.interpreter import project_python
    mx_in = make_code_text(mx, height=4); mx_in.configure(font=(s._MONO, 9))
    mx_in.insert("1.0", project_python() + "\n")
    mx_out = out_pane(mx)
    ttk.Button(mx, text="Run matrix",
               command=lambda: _run_async(
                   root, lambda t: _set_text(mx_out, t),
                   lambda: matrix_test(mx_in.get("1.0", "end-1c").splitlines()),
                   busy="running test matrix...")).pack(anchor="w", pady=4)

    # Quality gate tab.
    qg = ttk.Frame(nb); nb.add(qg, text="Quality gate")
    ttk.Label(qg, text="Run pytest + ruff + black + import check as one pass/fail gate.",
              style="Lbl.TLabel", wraplength=760).pack(anchor="w", pady=6)
    qg_out = out_pane(qg)
    ttk.Button(qg, text="Run gate", style="Accent.TButton",
               command=lambda: _run_async(
                   root, lambda t: _set_text(qg_out, t),
                   lambda: quality_gate()[1],
                   busy="running quality gate...")).pack(anchor="w", pady=4)

    # Coverage tab.
    cv = ttk.Frame(nb); nb.add(cv, text="Coverage")
    ttk.Label(cv, text="Run the tests under coverage and report % per file.",
              style="Lbl.TLabel", wraplength=760).pack(anchor="w", pady=6)
    cv_out = out_pane(cv)
    ttk.Button(cv, text="Run coverage",
               command=lambda: _run_async(
                   root, lambda t: _set_text(cv_out, t), coverage_run,
                   busy="running coverage...")).pack(anchor="w", pady=4)

    # SQLite tab.
    sq = ttk.Frame(nb); nb.add(sq, text="SQLite")
    qrow = ttk.Frame(sq); qrow.pack(fill="x", pady=6)
    ttk.Label(qrow, text="DB file", style="Lbl.TLabel").pack(side="left", padx=(0, 4))
    sq_db = tk.StringVar()
    ttk.Entry(qrow, textvariable=sq_db, width=44).pack(side="left")
    ttk.Button(qrow, text="...", command=lambda: sq_db.set(
        filedialog.askopenfilename(filetypes=[("SQLite", "*.db *.sqlite *.sqlite3"),
                                              ("All", "*.*")]) or sq_db.get())).pack(
        side="left", padx=4)
    sq_out = out_pane(sq)
    ttk.Button(qrow, text="Tables",
               command=lambda: _set_text(sq_out, sqlite_list_tables(sq_db.get()))).pack(
        side="left", padx=4)
    sq_sql = tk.StringVar(value="SELECT 1")
    qr2 = ttk.Frame(sq); qr2.pack(fill="x")
    ttk.Entry(qr2, textvariable=sq_sql).pack(side="left", fill="x", expand=True)
    ttk.Button(qr2, text="Query", command=lambda: _set_text(
        sq_out, sqlite_query(sq_db.get(), sq_sql.get()))).pack(side="left", padx=4)

    root.mainloop()
    return 0


# --- Run configs window -------------------------------------------------------

def _parse_dotenv_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, val = line.partition("=")
        k   = k.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if k:
            out[k] = val
    return out


def run_runconfigs() -> int:
    load_config()
    root = tk.Tk()
    root.title("ILX Run Configurations")
    root.geometry("560x520")
    style_theme(root)
    frm = ttk.Frame(root, padding=14); frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Run Configurations", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frm, text=f"Saved arg/env presets for {os.path.basename(s._HERE)}. Pick one in "
              "the launcher's 'Run config' dropdown before Start.",
              style="Lbl.TLabel", wraplength=520).pack(anchor="w", pady=(0, 8))

    row = ttk.Frame(frm); row.pack(fill="x", pady=2)
    ttk.Label(row, text="Existing", style="Lbl.TLabel", width=10).pack(side="left")
    existing = ttk.Combobox(row, width=28, state="readonly",
                            values=sorted(load_runconfigs(s._HERE).keys()))
    existing.pack(side="left")

    name_v = tk.StringVar()
    args_v = tk.StringVar()
    nrow = ttk.Frame(frm); nrow.pack(fill="x", pady=(8, 2))
    ttk.Label(nrow, text="Name",    style="Lbl.TLabel", width=10).pack(side="left")
    ttk.Entry(nrow, textvariable=name_v, width=28).pack(side="left")
    arow = ttk.Frame(frm); arow.pack(fill="x", pady=2)
    ttk.Label(arow, text="CLI args", style="Lbl.TLabel", width=10).pack(side="left")
    ttk.Entry(arow, textvariable=args_v, width=40).pack(side="left")
    ttk.Label(frm, text="Env vars (KEY=VALUE per line):",
              style="Lbl.TLabel").pack(anchor="w", pady=(8, 0))
    from ui.theme import make_code_text
    env_box = make_code_text(frm, height=8)
    env_box.configure(font=(s._MONO, 9))

    def load_existing(event=None):
        cfg = load_runconfigs(s._HERE).get(existing.get())
        if not cfg:
            return
        name_v.set(existing.get())
        args_v.set(cfg.get("args", ""))
        env_box.delete("1.0", "end")
        env_box.insert("1.0", "\n".join(f"{k}={v}" for k, v in cfg.get("env", {}).items()))
    existing.bind("<<ComboboxSelected>>", load_existing)

    def save_cfg():
        name = name_v.get().strip()
        if not name:
            return
        env = _parse_dotenv_text(env_box.get("1.0", "end-1c"))
        save_runconfig(s._HERE, name, args_v.get().strip(), env)
        existing["values"] = sorted(load_runconfigs(s._HERE).keys())

    def delete_cfg():
        if existing.get():
            delete_runconfig(s._HERE, existing.get())
            existing.set("")
            existing["values"] = sorted(load_runconfigs(s._HERE).keys())

    btns = ttk.Frame(frm); btns.pack(fill="x", pady=10)
    ttk.Button(btns, text="Save",            style="Accent.TButton",
               command=save_cfg).pack(side="left")
    ttk.Button(btns, text="Delete selected", command=delete_cfg).pack(side="left", padx=6)
    ttk.Button(btns, text="Close",           command=root.destroy).pack(side="left")
    root.mainloop()
    return 0

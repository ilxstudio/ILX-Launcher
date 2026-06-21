from __future__ import annotations

import os
import sys
import threading

import tkinter as tk
from tkinter import filedialog, ttk

import core.state as s
from core.config import (
    apply_config, load_config, save_config,
)
from core.interpreter import (
    bundled_python, create_venv, download_bundled_python, interp_has_jurigged,
    jurigged_available, load_interp_for, project_python, save_interp_for, venv_python,
)
from core.ollama import ollama_models
from core.process import proj_run
from ui.theme import style_theme


def run_config() -> int:
    load_config()
    root = tk.Tk()
    root.title("ILX Launcher - Configuration")
    style_theme(root)
    pad  = {"padx": 12, "pady": 3}
    outer = ttk.Frame(root); outer.pack(fill="both", expand=True, padx=10, pady=10)
    nb   = ttk.Notebook(outer); nb.pack(fill="both", expand=True)

    def tab(title: str) -> ttk.Frame:
        f = ttk.Frame(nb, padding=10); nb.add(f, text=title)
        return f

    t_llm     = tab("LLM & Editor")
    t_build   = tab("Build & Interpreter")
    t_behavior = tab("Behavior")
    t_watch   = tab("Watchdog")

    v: dict[str, tk.Variable] = {}

    # === LLM & Editor =========================================================
    ttk.Label(t_llm, text="Local LLM", style="Hdr.TLabel").pack(anchor="w", pady=(0, 4))
    row = ttk.Frame(t_llm); row.pack(fill="x", **pad)
    ttk.Label(row, text="Ollama host", style="Lbl.TLabel", width=22).pack(side="left")
    v["ollama_host"] = tk.StringVar(value=str(s._config["ollama_host"]))
    ttk.Entry(row, textvariable=v["ollama_host"], width=34).pack(side="left")

    row = ttk.Frame(t_llm); row.pack(fill="x", **pad)
    ttk.Label(row, text="Default model", style="Lbl.TLabel", width=22).pack(side="left")
    models = ollama_models()
    cur    = str(s._config["ollama_default"])
    model_combo = ttk.Combobox(row, values=models, width=26, state="readonly")
    model_combo.set(cur if cur in models else (models[0] if models else cur))
    model_combo.pack(side="left")

    def refresh_models():
        s._OLLAMA_HOST = v["ollama_host"].get().rstrip("/")
        ms = ollama_models()
        model_combo["values"] = ms
        c = model_combo.get()
        model_combo.set(c if c in ms else (ms[0] if ms else c))
    ttk.Button(row, text="Refresh", command=refresh_models).pack(side="left", padx=6)

    ttk.Separator(t_llm).pack(fill="x", pady=6)
    ttk.Label(t_llm, text="Editor / tools", style="Hdr.TLabel").pack(anchor="w", pady=(0, 4))
    row = ttk.Frame(t_llm); row.pack(fill="x", **pad)
    ttk.Label(row, text="Editor command (blank=auto)", style="Lbl.TLabel",
              width=22).pack(side="left")
    v["editor"] = tk.StringVar(value=str(s._config["editor"]))
    ttk.Entry(row, textvariable=v["editor"], width=34).pack(side="left")

    v["auto_install_build"] = tk.BooleanVar(value=bool(s._config["auto_install_build"]))
    ttk.Checkbutton(t_llm, text="Auto-install PyInstaller when building",
                    variable=v["auto_install_build"]).pack(anchor="w", **pad)
    v["auto_deps"] = tk.BooleanVar(value=bool(s._config.get("auto_deps", True)))
    ttk.Checkbutton(t_llm, text="Auto-install requirements.txt before Start",
                    variable=v["auto_deps"]).pack(anchor="w", **pad)

    row = ttk.Frame(t_llm); row.pack(fill="x", **pad)
    ttk.Label(row, text="Source-scan interval (s)", style="Lbl.TLabel",
              width=22).pack(side="left")
    v["poll_interval"] = tk.StringVar(value=str(s._config["poll_interval"]))
    ttk.Entry(row, textvariable=v["poll_interval"], width=8).pack(side="left")

    # === Build & Interpreter ==================================================
    ttk.Label(t_build, text="Build & interpreter", style="Hdr.TLabel").pack(
        anchor="w", pady=(0, 4))
    row = ttk.Frame(t_build); row.pack(fill="x", **pad)
    ttk.Label(row, text="Python interpreter", style="Lbl.TLabel", width=22).pack(side="left")
    interp_var = tk.StringVar(value=load_interp_for(s._HERE))
    ttk.Entry(row, textvariable=interp_var, width=30).pack(side="left")

    def browse_interp():
        p = filedialog.askopenfilename(title="Choose a python.exe",
                                       filetypes=[("Python", "python*.exe"), ("All", "*.*")])
        if p:
            interp_var.set(p)
    ttk.Button(row, text="...", width=3, command=browse_interp).pack(side="left", padx=4)
    ttk.Label(t_build, text="Blank = the launcher's own Python. Point at a venv's python.exe.",
              style="Lbl.TLabel", wraplength=520).pack(anchor="w", padx=12)

    row = ttk.Frame(t_build); row.pack(fill="x", **pad)
    ttk.Label(row, text="Create venv (base Python)", style="Lbl.TLabel",
              width=22).pack(side="left")
    base_var = tk.StringVar(value=sys.executable)
    ttk.Entry(row, textvariable=base_var, width=24).pack(side="left")

    def make_venv():
        ok, log = create_venv(base_var.get())
        if ok:
            interp_var.set(venv_python(os.path.join(s._HERE, ".venv")))
        else:
            print("[launcher] venv creation failed:\n" + log[-1500:])
    ttk.Button(row, text="Create .venv", command=make_venv).pack(side="left", padx=4)

    brow = ttk.Frame(t_build); brow.pack(fill="x", **pad)
    ttk.Label(brow, text="Bundled Python", style="Lbl.TLabel", width=22).pack(side="left")
    bundle_lbl = tk.Label(brow, text="", bg=s._C_BG, fg=s._C_LBL, font=(s._FONT, 9))

    def refresh_bundle_lbl():
        bp = bundled_python()
        bundle_lbl.configure(text=(f"installed: {bp}" if bp else s._bundle_status))
        if not bundled_python():
            brow.after(600, refresh_bundle_lbl)

    def get_bundle():
        if bundled_python():
            interp_var.set(bundled_python())
            return
        threading.Thread(target=download_bundled_python, daemon=True).start()
        refresh_bundle_lbl()
    ttk.Button(brow, text=("Use bundled" if bundled_python() else "Download bundled"),
               command=get_bundle).pack(side="left")
    bundle_lbl.pack(side="left", padx=8)
    refresh_bundle_lbl()

    row = ttk.Frame(t_build); row.pack(fill="x", **pad)
    ttk.Label(row, text="EXE build mode", style="Lbl.TLabel", width=22).pack(side="left")
    v["build_mode"] = tk.StringVar(value=str(s._config.get("build_mode", "onedir")))
    ttk.Radiobutton(row, text="Folder of deps (smaller exe)", value="onedir",
                    variable=v["build_mode"]).pack(side="left")
    ttk.Radiobutton(row, text="One file (deps built in)", value="onefile",
                    variable=v["build_mode"]).pack(side="left", padx=8)
    v["gate_before_build"] = tk.BooleanVar(value=bool(s._config.get("gate_before_build")))
    ttk.Checkbutton(t_build, text="Run quality gate (tests+lint+import) before building",
                    variable=v["gate_before_build"]).pack(anchor="w", **pad)

    # === Behavior =============================================================
    ttk.Label(t_behavior, text="Launcher behavior", style="Hdr.TLabel").pack(
        anchor="w", pady=(0, 4))
    v["auto_reload"] = tk.BooleanVar(value=bool(s._config["auto_reload"]))
    ttk.Checkbutton(t_behavior, text="Auto-reload on save",
                    variable=v["auto_reload"]).pack(anchor="w", **pad)
    v["force_utf8"] = tk.BooleanVar(value=bool(s._config["force_utf8"]))
    ttk.Checkbutton(t_behavior, text="Force UTF-8 in the app (PYTHONUTF8=1)",
                    variable=v["force_utf8"]).pack(anchor="w", **pad)
    v["load_dotenv"] = tk.BooleanVar(value=bool(s._config["load_dotenv"]))
    ttk.Checkbutton(t_behavior, text="Load the project's .env into the app",
                    variable=v["load_dotenv"]).pack(anchor="w", **pad)
    v["notify"] = tk.BooleanVar(value=bool(s._config.get("notify", True)))
    ttk.Checkbutton(t_behavior, text="Desktop notification on crash / test-fail / watchdog",
                    variable=v["notify"]).pack(anchor="w", **pad)
    v["hot_patch"] = tk.BooleanVar(value=bool(s._config["hot_patch"]))
    has_jur = jurigged_available()
    hprow = ttk.Frame(t_behavior); hprow.pack(fill="x", **pad)
    hp_cb = ttk.Checkbutton(
        hprow, variable=v["hot_patch"],
        text=("Hot patch (keep app state via jurigged)" if has_jur
              else "Hot patch (jurigged not found in this interpreter)"),
        state=("normal" if has_jur else "disabled"))
    hp_cb.pack(side="left")

    def install_jurigged():
        py = project_python()
        if not py:
            return
        hp_cb.configure(text="Hot patch (installing jurigged...)")

        def work():
            proj_run([py, "-m", "pip", "install", "jurigged"], timeout=s._BUILD_TIMEOUT)
            s._jurigged_cache.pop(py, None)
            ok = interp_has_jurigged(py)
            hp_cb.configure(
                state=("normal" if ok else "disabled"),
                text=("Hot patch (keep app state via jurigged)" if ok
                      else "Hot patch (install failed - see console)"))
        threading.Thread(target=work, daemon=True).start()
    if not has_jur:
        ttk.Button(hprow, text="Install jurigged",
                   command=install_jurigged).pack(side="left", padx=8)

    v["always_on_top"] = tk.BooleanVar(value=bool(s._config["always_on_top"]))
    ttk.Checkbutton(t_behavior, text="Keep launcher always on top",
                    variable=v["always_on_top"]).pack(anchor="w", **pad)
    ttk.Separator(t_behavior).pack(fill="x", pady=6)

    rrow = ttk.Frame(t_behavior); rrow.pack(fill="x", **pad)
    ttk.Label(rrow, text="Live REPL hook", style="Lbl.TLabel", width=22).pack(side="left")

    def copy_repl():
        try:
            root.clipboard_clear()
            root.clipboard_append(s._REPL_SNIPPET)
            print("[launcher] REPL hook copied to clipboard")
        except tk.TclError:
            pass
    ttk.Button(rrow, text="Copy REPL hook", command=copy_repl).pack(side="left")

    # === Watchdog =============================================================
    ttk.Label(t_watch, text="Safety watchdog (auto-kill the app)",
              style="Hdr.TLabel").pack(anchor="w")
    ttk.Label(t_watch, text="Kills the running app before a leak or freeze can exhaust "
              "the machine.", style="Lbl.TLabel", wraplength=520).pack(anchor="w", pady=(0, 4))
    v["watchdog_on"] = tk.BooleanVar(value=bool(s._config["watchdog_on"]))
    ttk.Checkbutton(t_watch, text="Enable safety watchdog",
                    variable=v["watchdog_on"]).pack(anchor="w", **pad)

    def num_row(label, key, val):
        row = ttk.Frame(t_watch); row.pack(fill="x", **pad)
        ttk.Label(row, text=label, style="Lbl.TLabel", width=22).pack(side="left")
        v[key] = tk.StringVar(value=str(val))
        ttk.Entry(row, textvariable=v[key], width=10).pack(side="left")
    num_row("Hard memory cap (MB)",     "mem_cap_mb",      s._config["mem_cap_mb"])
    num_row("Max memory growth (MB/s)", "mem_growth_mb_s", s._config["mem_growth_mb_s"])
    num_row("CPU 'pegged' threshold (%)","cpu_pegged_pct", s._config["cpu_pegged_pct"])
    num_row("Kill after pegged for (s)", "cpu_pegged_s",   s._config["cpu_pegged_s"])

    def save():
        def f(key, default):
            try:
                return float(v[key].get())
            except (TypeError, ValueError, tk.TclError):
                return default
        s._config["ollama_host"]        = v["ollama_host"].get()
        s._config["ollama_default"]     = model_combo.get()
        s._config["editor"]             = v["editor"].get()
        s._config["auto_install_build"] = bool(v["auto_install_build"].get())
        s._config["auto_deps"]          = bool(v["auto_deps"].get())
        s._config["build_mode"]         = v["build_mode"].get()
        s._config["gate_before_build"]  = bool(v["gate_before_build"].get())
        s._config["poll_interval"]      = f("poll_interval", 0.5)
        s._config["force_utf8"]         = bool(v["force_utf8"].get())
        s._config["load_dotenv"]        = bool(v["load_dotenv"].get())
        s._config["notify"]             = bool(v["notify"].get())
        s._config["auto_reload"]        = bool(v["auto_reload"].get())
        s._config["hot_patch"]          = bool(v["hot_patch"].get())
        s._config["always_on_top"]      = bool(v["always_on_top"].get())
        s._config["watchdog_on"]        = bool(v["watchdog_on"].get())
        s._config["mem_cap_mb"]         = int(f("mem_cap_mb", 4000))
        s._config["mem_growth_mb_s"]    = f("mem_growth_mb_s", 150.0)
        s._config["cpu_pegged_pct"]     = f("cpu_pegged_pct", 97.0)
        s._config["cpu_pegged_s"]       = int(f("cpu_pegged_s", 20))
        save_interp_for(s._HERE, interp_var.get())
        apply_config()
        save_config()
        print("[launcher] configuration saved")
        root.destroy()

    btns = ttk.Frame(outer); btns.pack(fill="x", pady=(10, 0))
    ttk.Button(btns, text="Save",   style="Accent.TButton", command=save).pack(side="left")
    ttk.Button(btns, text="Cancel", command=root.destroy).pack(side="left", padx=6)

    root.update_idletasks()
    need_h = min(root.winfo_reqheight() + 20, int(root.winfo_screenheight() * 0.92))
    need_w = max(580, root.winfo_reqwidth() + 20)
    x = (root.winfo_screenwidth() - need_w) // 2
    y = max(0, (root.winfo_screenheight() - need_h) // 2)
    root.geometry(f"{need_w}x{need_h}+{x}+{y}")
    root.mainloop()
    return 0

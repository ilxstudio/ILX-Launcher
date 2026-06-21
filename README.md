# ILX Launcher

**A single-file developer cockpit for running, hot-reloading, testing, and shipping Python desktop apps.**

Point it at any project that has a `main.py` and it runs your app as a child process, watches your
source, hot-patches live edits, captures crashes, manages interpreters and dependencies, builds your
EXE, and gives you a local-LLM coding assistant — all from one window.

![ILX Launcher main window](docs/img/main_window.png)

---

## Why

Running a Python desktop app while you develop it usually means a terminal, a manual restart on every
edit, separate windows for tests, pip, profiling, and builds, and no safety net when something runs
away with your machine. The ILX Launcher folds all of that into one window:

- **No restart on every edit** — live hot-patch keeps app state (loaded project, camera, selection).
- **No "I forgot the CLI args"** — saved run configurations.
- **No "it works on my Python"** — per-project interpreters, one-click venvs, and a bundled Python.
- **No crashed PC** — a resource watchdog kills a runaway child before it exhausts memory or CPU.

It is intentionally **product-agnostic** — it ships as one file and drives any `main.py` project.

## Features

- **Run & live reload** — child-process model; auto-reload on save and **hot patch** (live function
  reload via [jurigged](https://github.com/breuleux/jurigged)) that preserves app state.
- **Coder** — editable editor with live Python syntax highlighting + a local-LLM (Ollama)
  **Chat / Review / Edit** workspace; verified saves that auto-revert if they don't compile or pass tests.
- **Interpreters** — per-project interpreter, one-click `.venv`, and a CPython downloaded on demand
  (run projects on a machine with no Python installed).
- **Dependencies** — pip console + "install all requirements" into the project interpreter.
- **Tests** — a traffic light that re-runs your suite on every source change.
- **Builds** — one-folder / one-file PyInstaller EXE and an Inno Setup installer, with an optional
  pre-build quality gate.
- **Tool windows** — Logs (+ Procfile orchestration), Crash history (SQLite), Profiler
  (cProfile + py-spy), Git, Automation, Code Quality (ruff / black / mypy), and a live REPL into the
  running app.
- **Safety watchdog** — auto-kills a runaway child (hard memory cap, runaway growth, or pegged CPU).

## Requirements

- **Python 3.11+** with **tkinter** available.
  tkinter ships with the standard python.org installer on Windows and macOS; on some Linux distros
  install it separately (e.g. `sudo apt install python3-tk`).
- The launcher core has **no third-party runtime dependencies** — it is pure stdlib + tkinter.
- Optional features (hot patch, builds, lint/format/type, profiling, LLM) use tools the launcher
  installs into your *target project's* interpreter on demand. See [requirements.txt](requirements.txt).
- LLM features need a local [Ollama](https://ollama.com) server (optional).

## Install & run

```bash
git clone <your-repo-url> "ILX Launcher"
cd "ILX Launcher"
python launcher.py
```

That's it — no install step is required to run from source.

**Standalone EXE (Windows):** build a no-console `launcher.exe` from inside the launcher
(Build EXE), or run PyInstaller directly:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name launcher launcher.py
```

On a machine with no Python at all, the frozen launcher can download a self-contained CPython on
first run.

## Documentation

The full **[User Manual](docs/LAUNCHER_MANUAL.md)** walks through every window and feature with
screenshots.

## Configuration & state

Settings persist to `~/.ilx_launcher.json` (recent projects, per-project interpreters, run
configs, watchdog thresholds, and all options). Per-machine runtime state
(`.launcher_crashes.db`, `.launcher_session.log`, `.window_geometry.json`) is git-ignored.

## Project layout

```
launcher.py            # the entire launcher — one file
requirements.txt       # OPTIONAL tools the launcher manages (not imported by it)
docs/
  LAUNCHER_MANUAL.md   # full user manual
  _capture.py          # screenshot harness (regenerates docs/img/*.png)
  img/                 # manual screenshots
```

## License

[MIT](LICENSE) © 2026 ILX Studio, LLC

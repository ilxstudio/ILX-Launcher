# Changelog

All notable changes to the ILX Launcher are recorded here.
This project adheres to [Semantic Versioning](https://semver.org).

## [1.0.0] — 2026-06-21

First standalone release. The launcher was extracted from the ILX Connection v2
product repository into its own home with a fresh history.

### Features
- **Run & live reload** — runs any project with a `main.py` as a child process;
  auto-reload on save and live **hot patch** via [jurigged](https://github.com/breuleux/jurigged)
  (preserves app state across function edits).
- **Coder** — built-in editable code editor with live Python syntax highlighting,
  plus a local-LLM (Ollama) **Chat / Review / Edit** workspace; create new files
  and folders; verified saves (must compile + pass tests or auto-revert).
- **Interpreters** — per-project interpreter, one-click `.venv` creation, and a
  bundled CPython downloaded on demand (runs projects on a machine with no Python).
- **Dependencies** — pip console + "install all requirements" against the project
  interpreter; optional auto-install on Start.
- **Tests** — a traffic light that re-runs the suite on every source change.
- **Builds** — one-folder / one-file PyInstaller EXE and an Inno Setup installer,
  with an optional pre-build quality gate.
- **Tool windows** — Logs (with Procfile orchestration), Crash history (SQLite),
  Profiler (cProfile + py-spy), Git, Automation (scaffold / matrix / gate /
  coverage / SQLite browser), Code Quality (ruff / black / mypy), and a Live REPL
  into the running app.
- **Safety watchdog** — auto-kills a runaway child on a hard memory cap, runaway
  growth, or pegged CPU (captures a py-spy dump first).
- Ships as a single `launcher.py`; can be frozen to a standalone `launcher.exe`.

[1.0.0]: https://github.com/

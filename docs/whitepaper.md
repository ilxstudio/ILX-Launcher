# ILX Launcher: A Developer Cockpit for Python Desktop Apps

*ILX Studio, LLC — 2026*

---

## The Problem

If you build Python desktop apps for a living, you live in a loop:

```
edit code  ->  switch to terminal  ->  Ctrl+C the running app
           ->  python main.py      ->  watch for the error
           ->  switch back to editor  ->  repeat
```

That loop is manageable with one app. It becomes painful with two or three. It becomes a drain when you are iterating fast — fixing a crash, checking what changed, waiting for the import to finish, hunting for the traceback in a terminal that scrolled off. You end up with five terminal windows open, none of them obviously the right one, and a growing reluctance to start the app at all just to test a small thing.

We hit every version of this problem while building ILX Connection, a real-time data platform for industrial customers. The app is large, stateful, and takes a few seconds to reach a working state. Closing and reopening it to test a one-line change was genuinely slow. Crashes produced tracebacks in a terminal — but which terminal? The log file? The one that scrolled past the error? We needed something better.

---

## What We Built

The ILX Launcher is a developer cockpit: a small, always-visible window that runs your app as a child process and gives you buttons for the things you actually do all day.

It started as a simple "start/stop" wrapper. It grew from there as each pain point became obvious.

**The start/stop problem.** The first thing we built was the ability to start and stop the child process from a persistent UI rather than a terminal. The launcher stays open; the app comes and goes inside it. This alone saved minutes per hour.

**The reload problem.** Closing and reopening just to pick up a one-line change felt wasteful. The launcher watches source files and relaunches the child the instant you save. If jurigged is installed, "hot patch" mode patches function definitions in the *live* process — the app never closes, its state is preserved, and the edit takes effect immediately. This is the difference between iterating every few seconds and iterating every few minutes.

**The crash problem.** When the app crashes, the launcher captures the traceback, records it to SQLite, groups identical crashes by signature, and shows a "Jump to crash" button that opens the offending file at the offending line in your editor. Crashes are no longer something you hunt for. They come to you.

**The log problem.** The launcher captures all child stdout/stderr into a ring buffer. The Logs window shows it live, filterable, with color-coded errors and warnings. It exports to a file. It runs Procfile-style multi-process groups. You never need a terminal window just to see what your app printed.

**The dependency problem.** Dependencies for a desktop app live in a venv. The wrong venv silently installs into the wrong place. The launcher's Dependencies window runs pip against *this project's configured interpreter*, shows what's installed, shows what's outdated, and runs arbitrary pip commands — all in one place.

**The LLM problem.** We use a local Ollama model for code assistance. The built-in Coder window gives that model a focused workspace: pick a file, describe a change, let the model rewrite it, review the diff, and apply it. The model's output is validated (must compile, must pass tests) and automatically reverted if verification fails. The Chat tab answers questions about the current file. The Review tab produces a full-file rewrite with findings. All of it runs in-process, with no browser tab needed.

---

## Architecture

The launcher is built on Python's standard library alone. No third-party dependencies in the launcher itself — just tkinter for the UI, plus whatever the *target project* has in its own interpreter.

The key architectural decisions:

**Single-file origin.** The launcher started as a single file (`launcher.py`) and was kept that way through the 1.0 release. A developer tool that you point at a project needs to be easy to carry around, easy to inspect, and impossible to misconfigure. One file satisfies all three. At 1.1.0 it was refactored into a proper package (`core/` + `ui/`), with `launcher.py` remaining as a backward-compatible shim and `main.py` as the new thin entry point.

**Two-interpreter model.** The launcher has its own Python (the one running `launcher.py`). The target app has *its* Python — possibly a venv, possibly a different version, possibly a bundled CPython downloaded on demand. These never mix. Every subprocess the launcher spawns for tooling (pytest, pip, ruff, PyInstaller) goes through `tool_python()` or `project_python()`, which resolves the right interpreter and refuses to spawn the launcher itself when frozen.

**Fork-bomb safety.** When packaged with PyInstaller, `sys.executable` is the launcher EXE. Spawning `sys.executable -m pytest` relaunches the GUI instead of running tests. The launcher guards against this at every spawn site: `tool_python()` returns `None` when frozen and no real Python is available, and callers skip rather than spawn. This invariant is tested manually on every build before shipping.

**Shared state via a single module.** All mutable globals live in `core/state.py`. Every other module does `import core.state as s` and reads/writes through that namespace. This makes the shared state explicit and grep-able, avoids circular imports, and keeps workers from needing to know about the UI.

**Main-thread discipline.** tkinter is not thread-safe. All widget access happens on the main thread. Background workers snapshot the data they need before launching, pass results through simple shared variables, and let the UI tick (every 200ms for the main window, 150ms for the coder) pick them up and paint them.

---

## Results

The launcher replaced five terminal windows, a text file of shortcuts, and a mental map of "which terminal has my app." We now have one window that shows the child's state, the codebase stats, and the test results at a glance.

More concretely:
- Crashes are captured and presented in under a second, with a button to jump to the line.
- Hot-patch mode means most edits take effect without restarting the app at all.
- The test traffic light turns red within a few seconds of a save that breaks something.
- Building an EXE is a button click; the quality gate runs first.

The launcher is not a replacement for a proper CI pipeline, a debugger, or a test runner. It is the thing you look at while you are working, and it makes the hour-to-hour rhythm of Python desktop development noticeably faster.

---

*ILX Launcher is MIT licensed. See LICENSE.*

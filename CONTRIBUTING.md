# Contributing to ILX Launcher

Thanks for your interest. This is a small, focused tool — contributions that keep it small and focused are most welcome.

## Setup

```bash
git clone https://github.com/ilxstudio/ILX-Launcher
cd ILX-Launcher
python main.py              # run the launcher
python -c "import core.state, core.interpreter, core.config, core.process, core.build, core.automation, core.coder; print('core OK')"
python -c "import ui.theme; print('ui OK')"
```

No pip install needed. The launcher has zero third-party runtime dependencies.

## Code rules

**700 lines per file.** No exceptions. If a module is getting long, split it.

**Pure stdlib + tkinter.** `core/` and `ui/` must import nothing outside the standard library. Third-party packages (`psutil`, `requests`, `jurigged`) are driven inside the *target project's* interpreter — they are never imported by the launcher itself.

**ASCII-only `print()`.** Em-dashes (`—`), ellipsis (`…`), and smart quotes crash on Windows cp1252 when the launcher is frozen. Use plain ASCII: `--`, `...`, `"`.

**`_NO_WINDOW` on every subprocess.** All `Popen`/`subprocess.run` calls that the user shouldn't see a console for must pass `creationflags=s._NO_WINDOW`.

**Fork-bomb guard.** Any new code that spawns Python must route through `tool_python()` or `project_python()` and apply the `_SELF` guard. Never spawn `sys.executable` directly in code that runs when frozen.

**Permissive licenses only.** MIT / BSD / Apache / PSF / OFL. No GPL, LGPL, MPL, or any copyleft. The launcher is part of a sold product.

**Copyright holder is "ILX Studio, LLC"** — not "Rivera Engineering" or any other string.

## Pull requests

1. Fork, branch off `main`, make your change.
2. Run the smoke test (see Setup).
3. Fill out the PR template checklist.
4. Keep the PR small and focused.

## Reporting bugs

Use the GitHub issue tracker. Fill out the bug report template — especially the environment section and any traceback.

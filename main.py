# ILX Launcher -- thin entry point.
#
# python main.py                  -- open the main launcher window
# python main.py --coder          -- open the Coder window for the active project
# python main.py --config         -- open Configuration
# python main.py --project <dir>  -- set the active project before opening any window
from __future__ import annotations

import sys


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()

    import core.state as s
    from core.config import is_project_dir, set_project

    args = sys.argv[1:]
    if "--project" in args:
        i = args.index("--project")
        if i + 1 < len(args) and is_project_dir(args[i + 1]):
            set_project(args[i + 1])

    dispatch = {
        "--coder":      "ui.coder_window:run_coder",
        "--config":     "ui.config_window:run_config",
        "--deps":       "ui.tool_windows:run_deps",
        "--quality":    "ui.tool_windows:run_quality",
        "--git":        "ui.tool_windows:run_git",
        "--profile":    "ui.tool_windows:run_profile",
        "--logs":       "ui.tool_windows:run_logs",
        "--crashes":    "ui.tool_windows:run_crashes",
        "--automation": "ui.tool_windows:run_automation",
        "--runconfigs": "ui.tool_windows:run_runconfigs",
    }
    for flag, target in dispatch.items():
        if flag in args:
            mod_name, _, fn_name = target.partition(":")
            import importlib
            mod = importlib.import_module(mod_name)
            return getattr(mod, fn_name)()

    from ui.main_window import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

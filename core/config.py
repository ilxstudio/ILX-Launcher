from __future__ import annotations

import json
import os

import core.state as s


def load_store() -> dict:
    try:
        with open(s._RECENTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_store(data: dict) -> None:
    try:
        with open(s._RECENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def load_config() -> None:
    saved = load_store().get("config", {})
    if isinstance(saved, dict):
        s._config.update({k: v for k, v in saved.items() if k in s._config})
    apply_config()
    try:
        s._store_mtime = os.path.getmtime(s._RECENTS_FILE)
    except OSError:
        s._store_mtime = 0.0


def reload_config_if_changed() -> None:
    try:
        mtime = os.path.getmtime(s._RECENTS_FILE)
    except OSError:
        return
    if mtime == s._store_mtime:
        return
    s._store_mtime = mtime
    was_hot = bool(s._config.get("hot_patch"))
    load_config()
    print("[launcher] configuration reloaded")
    from core.process import is_running, relaunch
    if bool(s._config.get("hot_patch")) != was_hot and is_running():
        mode = "hot patch (state preserved)" if s._config.get("hot_patch") else "plain relaunch"
        relaunch(f"switch to {mode}")


def apply_config() -> None:
    import tkinter as tk
    s._OLLAMA_HOST    = str(s._config["ollama_host"]).rstrip("/")
    s._OLLAMA_DEFAULT = str(s._config["ollama_default"])
    try:
        s._POLL_INTERVAL = max(0.1, float(s._config["poll_interval"]))
    except (TypeError, ValueError):
        s._POLL_INTERVAL = 0.5
    editor = str(s._config["editor"]).strip()
    s._EDITORS = (editor, "code", "cursor", "subl") if editor else ("code", "cursor", "subl")
    root = s._ui.get("root")
    if root is not None:
        try:
            root.attributes("-topmost", bool(s._config.get("always_on_top")))
        except tk.TclError:
            pass


def save_config() -> None:
    data = load_store()
    data["config"] = dict(s._config)
    save_store(data)


def load_recents() -> list[str]:
    return [p for p in load_store().get("recents", []) if os.path.isdir(p)]


def save_recents(recents: list[str]) -> None:
    data = load_store()
    data["recents"] = recents[:s._MAX_RECENTS]
    save_store(data)


def remember_project(root: str) -> list[str]:
    root = os.path.abspath(root)
    recents = [p for p in load_recents() if os.path.abspath(p) != root]
    recents.insert(0, root)
    recents = recents[:s._MAX_RECENTS]
    save_recents(recents)
    return recents


def load_runconfigs(root: str) -> dict:
    rc = load_store().get("runconfigs", {})
    return rc.get(os.path.abspath(root), {}) if isinstance(rc, dict) else {}


def save_runconfig(root: str, name: str, args: str, env: dict[str, str]) -> None:
    data = load_store()
    rc = data.get("runconfigs")
    if not isinstance(rc, dict):
        rc = {}
    key = os.path.abspath(root)
    rc.setdefault(key, {})[name] = {"args": args, "env": env}
    data["runconfigs"] = rc
    save_store(data)


def delete_runconfig(root: str, name: str) -> None:
    data = load_store()
    rc = data.get("runconfigs", {})
    if isinstance(rc, dict) and os.path.abspath(root) in rc:
        rc[os.path.abspath(root)].pop(name, None)
        data["runconfigs"] = rc
        save_store(data)


def parse_dotenv(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.lower().startswith("export "):
                    line = line[7:]
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                if key:
                    out[key] = val
    except OSError:
        pass
    return out


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    import os as _os
    env = dict(_os.environ, ILX_DEV="1")
    env["ILX_REPL_PORT"] = str(s._REPL_PORT)
    if s._config.get("force_utf8"):
        env["PYTHONUTF8"] = "1"
        env.setdefault("PYTHONIOENCODING", "utf-8")
    if s._config.get("load_dotenv"):
        dotenv = os.path.join(s._HERE, ".env")
        if os.path.exists(dotenv):
            env.update(parse_dotenv(dotenv))
    if extra:
        env.update(extra)
    return env


def set_project(root: str) -> None:
    from core.interpreter import load_interp_for
    s._HERE         = os.path.abspath(root)
    s._MAIN         = os.path.join(s._HERE, "main.py")
    s._LOG_FILE     = os.path.join(s._HERE, "log.txt")
    s._CMD_FILE     = os.path.join(s._HERE, ".launcher_cmd")
    s._LOCK_FILE    = os.path.join(s._HERE, ".llm.lock")
    s._SPEC         = os.path.join(s._HERE, "ILXConnection.spec")
    s._ISS          = os.path.join(s._HERE, "installer", "ILXConnection.iss")
    s._MANUAL_FILE  = os.path.join(s._HERE, "Program_Manual.md")
    s._baseline     = {}
    s._crash_jump   = None
    s._active_runconfig = None
    s._project_interp   = load_interp_for(s._HERE)


def is_project_dir(path: str) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, "main.py"))

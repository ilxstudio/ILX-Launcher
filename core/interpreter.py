from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

import core.state as s


def tool_python() -> str | None:
    if not s._FROZEN:
        return sys.executable
    cand = s._project_interp if (s._project_interp and os.path.exists(s._project_interp)) else ""
    return cand or bundled_python() or system_python() or None


def bundled_python() -> str:
    exe = os.path.join(s._BUNDLE_DIR, "python", "python.exe")
    return exe if os.path.exists(exe) else ""


def have_real_python() -> bool:
    if not getattr(sys, "frozen", False):
        return True
    return bool(shutil.which("python") or shutil.which("py"))


def system_python() -> str:
    for name in ("python", "py"):
        exe = shutil.which(name)
        if exe:
            return exe
    return ""


def venv_python(venv_dir: str) -> str:
    win = os.path.join(venv_dir, "Scripts", "python.exe")
    pos = os.path.join(venv_dir, "bin", "python")
    return win if os.path.exists(win) else pos


def project_python() -> str:
    p = s._project_interp
    if p and os.path.exists(p):
        return p
    if not s._FROZEN:
        return sys.executable
    return bundled_python() or system_python() or ""


def interp_label() -> str:
    p = project_python()
    if os.path.abspath(p) == os.path.abspath(sys.executable):
        return "launcher Python"
    bp = bundled_python()
    if bp and os.path.abspath(p) == os.path.abspath(bp):
        return "bundled Python 3.12"
    parts = p.replace("\\", "/").split("/")
    if "Scripts" in parts or "bin" in parts:
        return ".../" + "/".join(parts[-3:])
    return p


def interp_has_module(python: str, mod: str) -> bool:
    try:
        return subprocess.run(
            [python, "-c", f"import {mod}"],
            capture_output=True, timeout=15, creationflags=s._NO_WINDOW
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def interp_has_jurigged(python: str) -> bool:
    if not python or (s._FROZEN and os.path.abspath(python) == os.path.abspath(s._SELF)):
        return False
    if not s._FROZEN and os.path.abspath(python) == os.path.abspath(sys.executable):
        try:
            import importlib.util
            return importlib.util.find_spec("jurigged") is not None
        except (ImportError, ValueError):
            return False
    if python in s._jurigged_cache:
        return s._jurigged_cache[python]
    try:
        out = subprocess.run(
            [python, "-c", "import jurigged"],
            capture_output=True, timeout=15, creationflags=s._NO_WINDOW)
        ok = out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    s._jurigged_cache[python] = ok
    return ok


def jurigged_available() -> bool:
    py = project_python()
    if py:
        return interp_has_jurigged(py)
    if not s._FROZEN:
        try:
            import importlib.util
            return importlib.util.find_spec("jurigged") is not None
        except (ImportError, ValueError):
            return False
    return False


def hotpatch_on() -> bool:
    return bool(s._config.get("hot_patch")) and jurigged_available()


def download_bundled_python() -> str:
    if bundled_python():
        s._bundle_status = "already installed"
        return bundled_python()
    if s._bundle_downloading:
        return ""
    s._bundle_downloading = True
    tmp = os.path.join(tempfile.gettempdir(), s._PBS_ASSET)
    try:
        s._bundle_status = "connecting..."
        req = urllib.request.Request(s._PBS_URL, headers={"User-Agent": "ILX-Launcher"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length", 0))
            got = 0
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                pct = f"{got * 100 // total}%" if total else f"{got // 1048576} MB"
                s._bundle_status = f"downloading... {pct}"
        s._bundle_status = "extracting..."
        os.makedirs(s._BUNDLE_DIR, exist_ok=True)
        with tarfile.open(tmp, "r:gz") as tar:
            tar.extractall(s._BUNDLE_DIR)
        exe = bundled_python()
        s._bundle_status = (f"installed -> {exe}" if exe else "extracted but python.exe not found")
        return exe
    except (urllib.error.URLError, OSError, tarfile.TarError, ValueError) as e:
        s._bundle_status = f"download failed: {e}"
        return ""
    finally:
        s._bundle_downloading = False
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_interp_for(root: str) -> str:
    from core.config import load_store
    interps = load_store().get("interpreters", {})
    return interps.get(os.path.abspath(root), "") if isinstance(interps, dict) else ""


def save_interp_for(root: str, python: str) -> None:
    from core.config import load_store, save_store
    data = load_store()
    interps = data.get("interpreters")
    if not isinstance(interps, dict):
        interps = {}
    key = os.path.abspath(root)
    if python.strip():
        interps[key] = python.strip()
    else:
        interps.pop(key, None)
    data["interpreters"] = interps
    save_store(data)


def create_venv(base_python: str, name: str = ".venv") -> tuple[bool, str]:
    from core.process import proj_run
    base = base_python.strip() or sys.executable
    target = os.path.join(s._HERE, name or ".venv")
    rc, out = proj_run([base, "-m", "venv", target], timeout=s._BUILD_TIMEOUT)
    ok = rc == 0 and os.path.exists(venv_python(target))
    if ok:
        s._project_interp = venv_python(target)
        save_interp_for(s._HERE, s._project_interp)
    return ok, out

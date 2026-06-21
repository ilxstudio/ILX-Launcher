from __future__ import annotations

import os
import subprocess
import tempfile

import core.state as s
from core.interpreter import interp_has_module, project_python, tool_python
from core.process import proj_run, source_files, snapshot


# --- Testing ------------------------------------------------------------------

def has_project_tests() -> bool:
    for name in ("test", "tests"):
        if os.path.isdir(os.path.join(s._HERE, name)):
            return True
    try:
        return any(f.startswith("test_") and f.endswith(".py") for f in os.listdir(s._HERE))
    except OSError:
        return False


def run_embedded_test() -> tuple[str, str]:
    py = tool_python()
    if not py:
        return "none", "no Python for tests"
    try:
        with tempfile.TemporaryDirectory() as td:
            tpath = os.path.join(td, "test_ilx_embedded.py")
            with open(tpath, "w", encoding="utf-8") as f:
                f.write(s._EMBEDDED_GOD_FILE_TEST)
            env = dict(os.environ, ILX_TEST_ROOT=s._HERE)
            out = subprocess.run(
                [py, "-m", "pytest", "-q", "--no-header", tpath],
                cwd=td, capture_output=True, text=True, env=env,
                timeout=s._TEST_TIMEOUT, creationflags=s._NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "fail", "timed out"
    except (OSError, subprocess.SubprocessError):
        return "fail", "pytest error"
    state   = "pass" if out.returncode in (0, 5) else "fail"
    lines   = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    summary = (lines[-1] if lines else "") + " (built-in)"
    summary = "".join(c for c in summary if c.isascii() and c.isprintable())
    return state, summary[:26]


def run_pytest() -> tuple[str, str]:
    if not has_project_tests():
        return run_embedded_test()
    py = tool_python()
    if not py:
        return "none", "no Python for tests"
    try:
        out = subprocess.run(
            [py, "-m", "pytest", "-q", "--no-header"],
            cwd=s._HERE, capture_output=True, text=True,
            timeout=s._TEST_TIMEOUT, creationflags=s._NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "fail", "timed out"
    except (OSError, subprocess.SubprocessError):
        return "fail", "pytest error"
    state   = "pass" if out.returncode in (0, 5) else "fail"
    lines   = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    summary = lines[-1] if lines else ("no tests" if out.returncode == 5 else "")
    summary = "".join(c for c in summary if c.isascii() and c.isprintable())
    return state, (summary[:26] or ("all good" if state == "pass" else "errors"))


def test_worker() -> None:
    last_snap: dict[str, float] | None = None
    while True:
        if s._manual_running or s._build_running:
            if s._test_stop.wait(s._TEST_POLL):
                return
            continue
        snap = snapshot()
        if snap != last_snap or s._test_request.is_set():
            s._test_request.clear()
            last_snap = snap
            prev = s._test_state
            s._test_state = "running"
            state, summary = run_pytest()
            if snapshot() == snap:
                if state == "fail" and prev != "fail":
                    from core.notifications import notify
                    notify("Tests failed", summary)
                s._test_state, s._test_summary = state, summary
        if s._test_stop.wait(s._TEST_POLL):
            return


def request_tests() -> None:
    s._test_request.set()


def imports_ok() -> tuple[bool, str]:
    py = tool_python()
    if not py:
        return True, ""
    try:
        out = subprocess.run(
            [py, "-c", "import main"],
            cwd=s._HERE, capture_output=True, text=True,
            timeout=60, creationflags=s._NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if out.returncode == 0:
        return True, ""
    errs = [ln.strip() for ln in out.stderr.splitlines() if ln.strip()]
    msg  = errs[-1] if errs else "import failed"
    return False, "".join(c for c in msg if c.isascii() and c.isprintable())[:80]


# --- Quality tools ------------------------------------------------------------

def quality_run(tool: str) -> str:
    py  = project_python()
    mod = {"ruff": "ruff", "black": "black", "mypy": "mypy"}[tool]
    chk = subprocess.run([py, "-c", f"import {mod}"],
                         capture_output=True, creationflags=s._NO_WINDOW)
    if chk.returncode != 0:
        if not s._config.get("auto_install_build"):
            return f"{tool} not installed (enable auto-install in Configuration)"
        rc, out = proj_run([py, "-m", "pip", "install", mod], timeout=s._BUILD_TIMEOUT)
        if rc != 0:
            return f"failed to install {tool}:\n{out}"
    if tool == "ruff":
        args = [py, "-m", "ruff", "check", "."]
    elif tool == "black":
        args = [py, "-m", "black", "--check", "--diff", "."]
    else:
        args = [py, "-m", "mypy", "."]
    rc, out = proj_run(args, timeout=s._BUILD_TIMEOUT)
    return out.strip() or (f"{tool}: clean" if rc == 0 else f"{tool}: issues found")


def black_format() -> str:
    py = project_python()
    rc, out = proj_run([py, "-m", "black", "."], timeout=s._BUILD_TIMEOUT)
    return out.strip() or "black: nothing to reformat"


def quality_gate() -> tuple[bool, str]:
    report = []
    ok = True
    state, summary = run_pytest()
    report.append(f"pytest:  {summary}")
    ok = ok and state == "pass"
    for tool in ("ruff", "black"):
        res   = quality_run(tool)
        clean = "clean" in res or "would reformat 0" in res or res.endswith(": clean")
        report.append(f"{tool}:  {'ok' if clean else 'issues'}")
        ok = ok and clean
    imp_ok, imp_err = imports_ok()
    report.append(f"import:  {'ok' if imp_ok else imp_err}")
    ok = ok and imp_ok
    verdict = "GATE PASSED - safe to build" if ok else "GATE FAILED - fix before building"
    return ok, verdict + "\n\n" + "\n".join(report)


def coverage_run() -> str:
    py = project_python()
    if not interp_has_module(py, "coverage"):
        if not s._config.get("auto_install_build"):
            return "coverage not installed (enable auto-install in Configuration)"
        proj_run([py, "-m", "pip", "install", "coverage"], timeout=s._BUILD_TIMEOUT)
    proj_run([py, "-m", "coverage", "run", "-m", "pytest", "-q"], timeout=s._TEST_TIMEOUT)
    rc, out = proj_run([py, "-m", "coverage", "report"], timeout=60)
    return out.strip() or f"(coverage exited {rc})"


def profile_run(top_n: int = 25, seconds: int = 0) -> str:
    from io import StringIO
    import pstats
    out_path = os.path.join(tempfile.gettempdir(), "ilx_profile.pstats")
    py = project_python()
    runner = (
        "import cProfile, runpy, sys\n"
        "pr = cProfile.Profile(); pr.enable()\n"
        "sys.argv = ['main.py']\n"
        "try:\n"
        f"    runpy.run_path(r{s._MAIN!r}, run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n"
        "finally:\n"
        "    pr.disable()\n"
        f"    pr.dump_stats(r{out_path!r})\n"
    )
    rc, log = proj_run([py, "-c", runner], timeout=s._BUILD_TIMEOUT)
    if not os.path.exists(out_path):
        return f"no profile produced (did the app run/close?):\n{log[-1500:]}"
    buf = StringIO()
    try:
        st = pstats.Stats(out_path, stream=buf)
        st.sort_stats("cumulative").print_stats(top_n)
    except Exception as e:
        return f"could not read profile: {e}"
    return buf.getvalue()


# --- Dependencies -------------------------------------------------------------

def requirements_files() -> list[str]:
    names = ["requirements.txt", "requirements-dev.txt", "dev-requirements.txt"]
    return [n for n in names if os.path.exists(os.path.join(s._HERE, n))]


def auto_install_deps(on_status=None) -> tuple[bool, str]:
    py = project_python()
    if not py:
        return False, "no Python interpreter to install into"
    reqs = requirements_files()
    if not reqs:
        return True, "no requirements file found (nothing to install)"
    log = []
    for rel in reqs:
        msg = f"installing {rel}..."
        if on_status:
            on_status(msg)
        print(f"[launcher] {msg}")
        rc, out = proj_run(
            [py, "-m", "pip", "install", "-r", os.path.join(s._HERE, rel)],
            timeout=s._BUILD_TIMEOUT)
        log.append(f"=== {rel} (exit {rc}) ===\n{out.strip()}")
        if rc != 0:
            return False, "\n\n".join(log)
    return True, "\n\n".join(log) or "dependencies up to date"


def pip_freeze() -> str:
    rc, out = proj_run([project_python(), "-m", "pip", "list"])
    return out if rc == 0 else f"pip list failed:\n{out}"


def pip_outdated() -> str:
    rc, out = proj_run([project_python(), "-m", "pip", "list", "--outdated"])
    return out.strip() or "(everything up to date)"


def pip_install(spec: str) -> str:
    args = [project_python(), "-m", "pip", "install"]
    if spec.strip().lower().endswith((".txt",)) or spec.strip().startswith("-r"):
        req = spec.strip().split(None, 1)[-1] if spec.strip().startswith("-r") else spec
        args += ["-r", req.strip()]
    else:
        args += spec.split()
    rc, out = proj_run(args, timeout=s._BUILD_TIMEOUT)
    return out


def pip_command(cmd: str) -> str:
    parts = cmd.strip().split()
    if parts and parts[0].lower() == "pip":
        parts = parts[1:]
    if not parts:
        return "(type a pip command, e.g.  install requests   or   uninstall numpy)"
    rc, out = proj_run([project_python(), "-m", "pip", *parts], timeout=s._BUILD_TIMEOUT)
    return out.strip() or f"(pip exited with code {rc})"


# --- SQLite browser -----------------------------------------------------------

def sqlite_list_tables(db: str) -> str:
    import sqlite3
    try:
        con  = sqlite3.connect(db)
        tabs = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out = []
        for t in tabs:
            n = con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
            out.append(f"{t}  ({n} rows)")
        con.close()
        return "\n".join(out) or "(no tables)"
    except sqlite3.Error as e:
        return f"sqlite error: {e}"


def sqlite_query(db: str, sql: str) -> str:
    import sqlite3
    if not sql.strip().lower().startswith(("select", "pragma", "explain", "with")):
        return "only read-only queries allowed (SELECT / PRAGMA / EXPLAIN / WITH)"
    try:
        con  = sqlite3.connect(db)
        cur  = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(500)
        con.close()
    except sqlite3.Error as e:
        return f"sqlite error: {e}"
    if not cols:
        return "(no result set)"
    out = [" | ".join(cols), "-" * 40]
    for r in rows:
        out.append(" | ".join(str(x) for x in r))
    return "\n".join(out)


# --- Project scaffold ---------------------------------------------------------

def scaffold_project(target: str, name: str) -> tuple[bool, str]:
    if not name.strip():
        return False, "give the project a name"
    try:
        os.makedirs(target, exist_ok=True)
        os.makedirs(os.path.join(target, "test"), exist_ok=True)
        for rel, body in s._SCAFFOLD_FILES.items():
            path = os.path.join(target, rel)
            if os.path.exists(path):
                continue
            if os.path.dirname(rel):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body.replace("{name}", name.strip()))
        return True, f"created project '{name}' at {target}"
    except OSError as e:
        return False, f"scaffold failed: {e}"


# --- Matrix tests -------------------------------------------------------------

def matrix_test(interpreters: list[str]) -> str:
    if not interpreters:
        return "no interpreters given (one path per line)"
    lines = ["Interpreter                                  Result"]
    for py in interpreters:
        py = py.strip()
        if not py:
            continue
        if not os.path.exists(py):
            lines.append(f"{py:44} MISSING")
            continue
        ver  = proj_run([py, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                        timeout=20)[1].strip()
        rc, out = proj_run([py, "-m", "pytest", "-q", "--no-header"], timeout=s._TEST_TIMEOUT)
        tail    = [ln for ln in out.splitlines() if ln.strip()]
        summary = tail[-1][:30] if tail else ""
        mark    = "PASS" if rc in (0, 5) else "FAIL"
        lines.append(f"{py[:36]:36} {ver:8} {mark}  {summary}")
    return "\n".join(lines)


# --- Procfile orchestration ---------------------------------------------------

def procfile_path() -> str:
    return os.path.join(s._HERE, "Procfile")


def parse_procfile() -> list[tuple[str, str, str]]:
    import re
    out: list[tuple[str, str, str]] = []
    try:
        with open(procfile_path(), encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                name, _, rest = line.partition(":")
                rest = rest.strip()
                wait = ""
                m = re.match(r"\[wait\s+([^\]]+)\]\s*(.*)", rest)
                if m:
                    wait, rest = m.group(1).strip(), m.group(2).strip()
                out.append((name.strip(), wait, rest))
    except OSError:
        pass
    return out


def wait_ready(spec: str, timeout: float = 30.0) -> bool:
    import socket
    import time
    import urllib.error
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if spec.startswith("tcp:"):
                _, host, port = spec.split(":", 2)
                with socket.create_connection((host, int(port)), timeout=2):
                    return True
            elif spec.startswith("http:") or spec.startswith("https:"):
                with urllib.request.urlopen(spec, timeout=3) as r:
                    return r.status < 500
        except (OSError, ValueError, urllib.error.URLError):
            import time as _t; _t.sleep(1)
    return False


def orch_spawn(name: str, command: str, wait: str) -> None:
    import subprocess
    import threading
    from core.config import child_env
    from core.process import log_emit

    def supervise():
        backoff   = 1.0
        stop_evt  = s._orch[name]["stop"]
        while not stop_evt.is_set():
            env = child_env()
            try:
                p = subprocess.Popen(
                    command, cwd=s._HERE, env=env, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, encoding="utf-8",
                    errors="replace", creationflags=s._NO_WINDOW)
            except (OSError, ValueError) as e:
                log_emit(name, f"failed to start: {e}\n")
                return
            with s._orch_lock:
                s._orch[name]["proc"] = p
            log_emit(name, f"started (pid {p.pid})\n")
            try:
                for line in p.stdout:
                    log_emit(name, line)
            except Exception:
                pass
            rc = p.wait()
            if stop_evt.is_set():
                log_emit(name, "stopped\n")
                return
            log_emit(name, f"exited (code {rc}) - restarting in {backoff:.0f}s\n")
            with s._orch_lock:
                s._orch[name]["restarts"] += 1
            if stop_evt.wait(backoff):
                return
            backoff = min(backoff * 2, 30.0)

    if wait:
        from core.process import log_emit
        log_emit(name, f"waiting for {wait}...\n")
        if not wait_ready(wait):
            log_emit(name, f"gate {wait} not ready - starting anyway\n")
    threading.Thread(target=supervise, daemon=True).start()


def orch_start_all() -> str:
    import threading
    procs = parse_procfile()
    if not procs:
        return "no Procfile found (create one: 'name: command' per line)"
    for name, wait, command in procs:
        with s._orch_lock:
            if name in s._orch and s._orch[name].get("proc") and \
                    s._orch[name]["proc"].poll() is None:
                continue
            s._orch[name] = {"proc": None, "cmd": command, "wait": wait,
                             "restarts": 0, "stop": threading.Event()}
        orch_spawn(name, command, wait)
    return f"started {len(procs)} process(es): " + ", ".join(n for n, _, _ in procs)


def orch_stop_all() -> str:
    with s._orch_lock:
        names = list(s._orch.keys())
    for name in names:
        orch_stop_one(name)
    return f"stopped {len(names)} process(es)"


def orch_stop_one(name: str) -> None:
    with s._orch_lock:
        entry = s._orch.get(name)
    if not entry:
        return
    entry["stop"].set()
    p = entry.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        except OSError:
            pass


def orch_status() -> str:
    procs = parse_procfile()
    if not procs:
        return "(no Procfile)"
    lines = []
    for name, wait, command in procs:
        with s._orch_lock:
            entry = s._orch.get(name)
        if entry and entry.get("proc") and entry["proc"].poll() is None:
            state = f"running (pid {entry['proc'].pid}, restarts {entry['restarts']})"
        else:
            state = "stopped"
        gate = f"  [wait {wait}]" if wait else ""
        lines.append(f"{name:14} {state}{gate}\n    {command}")
    return "\n".join(lines)

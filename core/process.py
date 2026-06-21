from __future__ import annotations

import ast
import datetime
import os
import subprocess
import threading
import time
from collections import deque

import core.state as s
from core.interpreter import (
    hotpatch_on, interp_has_jurigged, project_python, tool_python
)


def is_running() -> bool:
    return s._proc is not None and s._proc.poll() is None


def source_files() -> list[str]:
    files: list[str] = []
    for root, dirs, names in os.walk(s._HERE):
        dirs[:] = [d for d in dirs if d not in s._SKIP_DIRS and not d.startswith(".")]
        for name in names:
            if not name.endswith(".py"):
                continue
            path = os.path.abspath(os.path.join(root, name))
            if path != s._SELF:
                files.append(path)
    return files


def snapshot() -> dict[str, float]:
    snap: dict[str, float] = {}
    for path in source_files():
        try:
            snap[path] = os.path.getmtime(path)
        except OSError:
            pass
    return snap


def log_emit(source: str, line: str) -> None:
    with s._log_lock:
        s._log_buffer.append((source, line.rstrip("\n")))
        s._log_seq += 1
    session_log_write(source, line)


def session_log_write(source: str, line: str) -> None:
    try:
        if s._session_log_fh is None:
            path = os.path.join(s._HERE, ".launcher_session.log")
            if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
                try:
                    os.replace(path, path + ".1")
                except OSError:
                    pass
            s._session_log_fh = open(path, "a", encoding="utf-8", errors="replace")
        s._session_log_fh.write(f"[{source}] {line}" if not line.endswith("\n")
                                else f"[{source}] {line}")
        s._session_log_fh.flush()
    except OSError:
        pass


def pump_child_output(proc: subprocess.Popen, source: str = "app") -> None:
    tail: deque[str] = deque(maxlen=s._MAX_LOG_LINES)
    try:
        for line in proc.stdout:
            print(line, end="")
            tail.append(line)
            log_emit(source, line)
    except Exception:
        pass
    rc = proc.wait()
    if not getattr(proc, "_ilx_stopping", False):
        s._last_exit = rc
        if rc != 0:
            write_crash_log(rc, "".join(tail))


def start(force_plain: bool = False) -> None:
    from core.config import child_env
    from core.notifications import notify
    if is_running():
        print(f"[launcher] already running (pid {s._proc.pid}) - start ignored")
        return
    s._crash_jump      = None
    s._cpu_hot_since   = None
    s._wd_mem.clear()
    s._wd_msg          = ""
    s._last_exit       = None
    s._child_start_time = time.monotonic()
    if not os.path.exists(s._MAIN):
        print(f"[launcher] cannot start - {s._MAIN} not found")
        return
    rc  = s._active_runconfig or {}
    env = child_env(rc.get("env"))
    extra_args = (rc.get("args") or "").split()
    py = project_python()
    if not py or (s._FROZEN and os.path.abspath(py) == os.path.abspath(s._SELF)):
        print("[launcher] no Python interpreter - set one or download the bundled Python "
              "in Configuration > Build & Interpreter")
        s._wd_msg = "no Python: set an interpreter or download the bundled one (Configuration)"
        return
    use_hot = hotpatch_on() and not force_plain and interp_has_jurigged(py)
    if use_hot:
        cmd = [py, "-u", "-m", "jurigged", "--watch", s._HERE, s._MAIN, *extra_args]
        print("[launcher] starting under jurigged (hot patch - state preserved)")
    else:
        cmd = [py, "-u", s._MAIN, *extra_args]
    s._proc = subprocess.Popen(
        cmd, cwd=s._HERE, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        bufsize=1, encoding="utf-8", errors="replace",
        creationflags=s._NO_WINDOW)
    s._child_pid  = s._proc.pid
    s._started_at = time.monotonic()
    s._launches  += 1
    s._baseline   = snapshot()
    threading.Thread(target=pump_child_output, args=(s._proc,), daemon=True).start()
    print(f"[launcher] started main.py (pid {s._proc.pid})")


def start_with_deps() -> None:
    from core.automation import auto_install_deps, requirements_files
    if is_running():
        return
    if s._config.get("auto_deps") and requirements_files() and project_python():
        s._wd_msg = "installing dependencies before start..."

        def work():
            ok, _ = auto_install_deps(on_status=lambda msg: s.__dict__.update({"_wd_msg": msg}))
            if not ok:
                s._wd_msg = "dependency install failed - see Logs/console"
                return
            s._wd_msg = ""
            start()
        threading.Thread(target=work, daemon=True).start()
    else:
        start()


def stop() -> None:
    if is_running():
        pid = s._proc.pid
        s._proc._ilx_stopping = True
        s._proc.terminate()
        try:
            s._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            s._proc.kill()
            s._proc.wait()
        print(f"[launcher] stopped main.py (pid {pid})")
    s._proc         = None
    s._child_pid    = None
    s._started_at   = None
    s._prev_cpu_secs = None
    s._prev_cpu_at  = None
    s._mem_hist.clear()
    s._wd_mem.clear()


def write_crash_log(rc: int, output: str) -> None:
    from core.notifications import notify
    stamp  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"ILX Connection crashed at {stamp}  (exit code {rc})\n{'=' * 64}\n"
    try:
        with open(s._LOG_FILE, "w", encoding="utf-8") as f:
            f.write(header + (output or "(no output captured)\n"))
        print(f"[launcher] crash logged to {os.path.basename(s._LOG_FILE)} (exit {rc})")
    except OSError as e:
        print(f"[launcher] could not write {os.path.basename(s._LOG_FILE)}: {e}")
    set_crash_jump(output or "")
    record_crash(rc, output or "")
    exc = s._crash_jump.get("exc", "crash") if s._crash_jump else f"exit {rc}"
    notify("App crashed", str(exc))


def crash_db_path() -> str:
    return os.path.join(s._HERE, ".launcher_crashes.db")


def crash_group_key(output: str) -> str:
    import hashlib
    frames = [f"{os.path.basename(p)}:{ln}" for p, ln in s._TRACE_RE.findall(output)
              if os.path.abspath(p).startswith(s._HERE + os.sep)]
    exc = ""
    for ln in reversed(output.splitlines()):
        if ln.strip():
            exc = ln.strip()
            break
    return hashlib.md5(("|".join(frames) + "||" + exc).encode("utf-8")).hexdigest()[:12]


def record_crash(rc: int, output: str) -> None:
    import sqlite3
    try:
        commit = git("rev-parse", "--short", "HEAD")[1].splitlines()[0] if \
            os.path.isdir(os.path.join(s._HERE, ".git")) else ""
    except (OSError, IndexError):
        commit = ""
    exc   = s._crash_jump.get("exc", "") if s._crash_jump else ""
    where = (f"{s._crash_jump['rel']}:{s._crash_jump['line']}" if s._crash_jump else "")
    try:
        con = sqlite3.connect(crash_db_path())
        con.execute("CREATE TABLE IF NOT EXISTS crashes (ts TEXT, grp TEXT, rc INTEGER, "
                    "exc TEXT, loc TEXT, commit_hash TEXT, traceback TEXT)")
        con.execute("INSERT INTO crashes VALUES (?,?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(timespec="seconds"),
                     crash_group_key(output), rc, exc, where, commit, output[-4000:]))
        con.commit()
        con.close()
    except sqlite3.Error as e:
        print(f"[launcher] crash-history write failed: {e}")


def crash_history_summary() -> str:
    import sqlite3
    if not os.path.exists(crash_db_path()):
        return "(no crashes recorded yet)"
    try:
        con  = sqlite3.connect(crash_db_path())
        rows = con.execute(
            "SELECT grp, COUNT(*), MIN(ts), MAX(ts), exc, loc, commit_hash FROM crashes "
            "GROUP BY grp ORDER BY MAX(ts) DESC").fetchall()
        con.close()
    except sqlite3.Error as e:
        return f"crash-history read failed: {e}"
    if not rows:
        return "(no crashes recorded yet)"
    out = []
    for grp, n, first, last, exc, loc, commit in rows:
        out.append(f"[{grp}]  x{n}   {loc or '?'}   {commit or ''}\n"
                   f"    {exc}\n    first {first}  last {last}")
    return "\n".join(out)


def set_crash_jump(output: str) -> None:
    frames = s._TRACE_RE.findall(output)
    chosen: tuple[str, int] | None = None
    for path, lineno in frames:
        ap = os.path.abspath(path)
        if ap.startswith(s._HERE + os.sep) and os.path.exists(ap):
            chosen = (ap, int(lineno))
    if not chosen:
        return
    exc = ""
    for ln in reversed(output.splitlines()):
        if ln.strip():
            exc = ln.strip()
            break
    ap, lineno = chosen
    s._crash_jump = {"file": ap, "line": lineno,
                     "rel": os.path.relpath(ap, s._HERE), "exc": exc[:60]}


def open_in_editor(path: str, line: int) -> bool:
    import shutil as _shutil
    for ed in s._EDITORS:
        ed = (ed or "").strip()
        if not ed:
            continue
        exe = _shutil.which(ed)
        if not exe:
            continue
        base = os.path.basename(ed).lower()
        if base.startswith(("code", "cursor")):
            args = [exe, "-g", f"{path}:{line}"]
        elif base.startswith("subl"):
            args = [exe, f"{path}:{line}"]
        else:
            args = [exe, path]
        try:
            subprocess.Popen(args, cwd=s._HERE)
            return True
        except OSError:
            continue
    return False


def jump_to_crash() -> None:
    cj = s._crash_jump
    if not cj:
        return
    if not open_in_editor(str(cj["file"]), int(cj["line"])):
        try:
            os.startfile(s._LOG_FILE)
        except OSError as e:
            print(f"[launcher] could not open crash location: {e}")


# --- Watchdog -----------------------------------------------------------------

def watchdog_kill(reason: str) -> None:
    from core.notifications import notify
    from core.diagnostics import pyspy_available, pyspy_dump
    stamp   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s._wd_msg = reason
    print(f"[launcher] WATCHDOG: {reason} - killing the app to protect the machine")
    dump = ""
    if "pegged" in reason and s._child_pid and pyspy_available():
        print("[launcher] capturing py-spy stack dump before kill...")
        dump = "\n\n=== py-spy stack dump ===\n" + pyspy_dump(s._child_pid)
    if s._proc is not None:
        try:
            s._proc._ilx_stopping = True
            s._proc.kill()
        except OSError:
            pass
    report = (f"ILX safety watchdog killed the app at {stamp}\n{'=' * 64}\n{reason}\n\n"
              "The launcher stopped the app before it could exhaust system resources.\n"
              "If this was a false alarm, raise the thresholds in Configuration.\n" + dump)
    try:
        with open(s._LOG_FILE, "w", encoding="utf-8") as f:
            f.write(report)
    except OSError:
        pass
    notify("Watchdog stopped the app", reason)
    stop()


def check_watchdog(mem_mb: float | None, cpu_pct: float | None) -> None:
    if not s._config.get("watchdog_on") or not is_running():
        s._cpu_hot_since = None
        return
    now = time.monotonic()
    if isinstance(mem_mb, float):
        cap = float(s._config["mem_cap_mb"])
        if cap > 0 and mem_mb >= cap:
            watchdog_kill(f"memory {mem_mb:.0f} MB reached the hard cap of {cap:.0f} MB")
            return
        s._wd_mem.append((mem_mb, now))
        # skip growth check during startup warmup — initial RSS jump looks like a leak
        in_warmup = (s._child_start_time is not None and
                     now - s._child_start_time < s._WD_WARMUP_S)
        if not in_warmup and len(s._wd_mem) >= 4:
            (m0, t0), (m1, t1) = s._wd_mem[0], s._wd_mem[-1]
            dt   = t1 - t0
            rise = m1 - m0
            rate = rise / dt if dt > 0 else 0.0
            limit    = float(s._config["mem_growth_mb_s"])
            min_rise = max(50.0, limit * dt)
            if limit > 0 and rate >= limit and rise >= min_rise:
                watchdog_kill(
                    f"memory growing {rate:.0f} MB/s (> {limit:.0f} MB/s) - likely a leak")
                return
    if isinstance(cpu_pct, float):
        thr = float(s._config["cpu_pegged_pct"])
        if cpu_pct >= thr:
            if s._cpu_hot_since is None:
                s._cpu_hot_since = now
            elif now - s._cpu_hot_since >= float(s._config["cpu_pegged_s"]):
                held = now - s._cpu_hot_since
                watchdog_kill(
                    f"CPU pegged at {cpu_pct:.0f}% for {held:.0f}s - likely a frozen loop")
                return
        else:
            s._cpu_hot_since = None


def relaunch(reason: str, force_plain: bool = False) -> None:
    print(f"[launcher] {reason}")
    stop()
    start(force_plain=force_plain)


def restart() -> None:
    relaunch("restart (full close/open)", force_plain=True)


def refresh() -> None:
    relaunch("refresh code - relaunching to pick up edits")


def check_for_changes() -> None:
    if (not s._config.get("auto_reload") or not is_running()
            or s._manual_running or s._build_running):
        return
    now = time.monotonic()
    if now - s._last_poll < s._POLL_INTERVAL:
        return
    s._last_poll = now
    if hotpatch_on() and is_running():
        s._baseline = snapshot()
        return
    current = snapshot()
    if current == s._baseline:
        return
    changed = sorted(
        os.path.relpath(p, s._HERE)
        for p in set(s._baseline) | set(current)
        if s._baseline.get(p) != current.get(p)
    )
    s._baseline = current
    relaunch(f"auto-reload - changed: {', '.join(changed)}")


def check_backdoor() -> None:
    try:
        if not os.path.exists(s._CMD_FILE):
            return
        with open(s._CMD_FILE, encoding="utf-8") as f:
            cmd = f.read().strip().lower()
    except OSError:
        return
    try:
        os.remove(s._CMD_FILE)
    except OSError:
        pass
    if cmd == "stop":
        print("[launcher] backdoor: stop app")
        stop()
    elif cmd == "restart":
        print("[launcher] backdoor: restart app")
        relaunch("backdoor restart")


# --- Process stats ------------------------------------------------------------

def cpu_secs_from(field: str) -> float | None:
    parts = field.strip().split(":")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return None
    secs = 0.0
    for n in nums:
        secs = secs * 60 + n
    return secs


def query_proc(pid: int) -> tuple[float | None, float | None]:
    try:
        out = subprocess.run(
            ["tasklist", "/v", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=4, creationflags=s._NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None, None
    line = out.stdout.strip()
    if not line or "No tasks" in line:
        return None, None
    fields = [f.strip('"') for f in line.split('","')]
    if len(fields) < 8:
        return None, None
    mem = None
    digits = fields[4].replace(",", "").replace("K", "").strip()
    try:
        mem = int(digits) / 1024.0
    except ValueError:
        pass
    return mem, cpu_secs_from(fields[7])


def codebase_stats() -> dict[str, object]:
    files    = source_files()
    loc = size = 0
    big_name, big_lines = "", 0
    for path in files:
        try:
            size += os.path.getsize(path)
            with open(path, encoding="utf-8", errors="ignore") as f:
                total = code = 0
                for line in f:
                    total += 1
                    if line.strip():
                        code += 1
            loc += code
            if total > big_lines:
                big_lines, big_name = total, os.path.basename(path)
        except OSError:
            pass
    return {"files": len(files), "loc": loc, "size_kb": size / 1024.0,
            "big_name": big_name, "big_lines": big_lines}


def read_assign(name: str, default: str) -> str:
    try:
        with open(os.path.join(s._HERE, "version.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return default
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return str(ast.literal_eval(node.value))
                    except (ValueError, SyntaxError):
                        return default
    return default


def program_version() -> str:
    return read_assign("VERSION", "?")


def program_name() -> str:
    return read_assign("PRODUCT_NAME", "ILX")


def stats_worker() -> None:
    while True:
        cb = codebase_stats()
        pid = s._child_pid
        mem, cpu_secs = query_proc(pid) if pid is not None else (None, None)
        cb["mem_mb"] = mem
        cpu_pct = None
        now = time.monotonic()
        if cpu_secs is not None and s._prev_cpu_secs is not None and s._prev_cpu_at is not None:
            dt = now - s._prev_cpu_at
            if dt > 0:
                pct = (cpu_secs - s._prev_cpu_secs) / dt / s._cpu_cores * 100.0
                cpu_pct = max(0.0, min(100.0, pct))
        s._prev_cpu_secs, s._prev_cpu_at = cpu_secs, now
        cb["cpu_pct"] = cpu_pct
        if isinstance(mem, float):
            s._mem_hist.append(mem)
        check_watchdog(mem, cpu_pct)
        cb["version"] = program_version()
        cb["name"]    = program_name()
        s._stats = cb
        if s._stats_stop.wait(s._STATS_INTERVAL):
            return


def open_folder() -> None:
    try:
        os.startfile(s._HERE)
    except OSError as e:
        print(f"[launcher] open folder failed: {e}")


# --- Git helper ---------------------------------------------------------------

def git(*args: str) -> tuple[int, str]:
    try:
        out = subprocess.run(
            ["git", *args], cwd=s._HERE, capture_output=True,
            text=True, timeout=120, creationflags=s._NO_WINDOW)
        return out.returncode, (out.stdout + out.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def proj_run(args: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        out = subprocess.run(args, cwd=s._HERE, capture_output=True, text=True,
                             timeout=timeout, creationflags=s._NO_WINDOW)
        return out.returncode, (out.stdout + out.stderr)
    except subprocess.TimeoutExpired:
        return 1, "(timed out)"
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)

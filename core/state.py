from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# --- Frozen / self identity ---------------------------------------------------
_FROZEN = getattr(sys, "frozen", False)
_SELF   = os.path.abspath(sys.executable if _FROZEN else
          os.path.join(os.path.dirname(__file__), "..", "main.py"))
_HERE   = os.path.dirname(_SELF)
_MAIN   = os.path.join(_HERE, "main.py")

# --- Paths that move when the active project changes --------------------------
_LOG_FILE    = os.path.join(_HERE, "log.txt")
_CMD_FILE    = os.path.join(_HERE, ".launcher_cmd")
_LOCK_FILE   = os.path.join(_HERE, ".llm.lock")
_SPEC        = os.path.join(_HERE, "ILXConnection.spec")
_ISS         = os.path.join(_HERE, "installer", "ILXConnection.iss")
_MANUAL_FILE = os.path.join(_HERE, "Program_Manual.md")

# --- Launcher version (from version.py at the repo root) ---------------------
def _read_launcher_version() -> str:
    try:
        import ast as _ast
        _vpath = os.path.join(os.path.dirname(os.path.dirname(__file__)), "version.py")
        with open(_vpath, encoding="utf-8") as _f:
            _tree = _ast.parse(_f.read())
        for _n in _tree.body:
            if isinstance(_n, _ast.Assign):
                for _t in _n.targets:
                    if isinstance(_t, _ast.Name) and _t.id == "VERSION":
                        return str(_ast.literal_eval(_n.value))
    except (OSError, SyntaxError, ValueError, AttributeError):
        pass
    return "1.1.0"

_LAUNCHER_VERSION = _read_launcher_version()

# --- Recents / store ----------------------------------------------------------
_RECENTS_FILE = os.path.join(os.path.expanduser("~"), ".ilx_launcher.json")
_MAX_RECENTS  = 8
_combo_paths: list[str] = []

# --- User config (persisted under "config" in the JSON store) -----------------
_config: dict[str, object] = {
    "ollama_host":        "http://192.168.50.100:11434",
    "ollama_default":     "qwen2.5:14b",
    "editor":             "",
    "auto_install_build": True,
    "build_mode":         "onedir",
    "gate_before_build":  False,
    "force_utf8":         True,
    "load_dotenv":        True,
    "notify":             True,
    "auto_deps":          True,
    "poll_interval":      0.5,
    "auto_reload":        True,
    "hot_patch":          False,
    "always_on_top":      False,
    "watchdog_on":        True,
    "mem_cap_mb":         4000,
    "mem_growth_mb_s":    150.0,
    "cpu_pegged_s":       20,
    "cpu_pegged_pct":     97.0,
}
_store_mtime: float = 0.0

# --- Child process ------------------------------------------------------------
_proc:             subprocess.Popen | None = None
_active_runconfig: dict | None = None
_last_exit:        int | None  = None
_child_pid:        int | None  = None
_started_at:       float | None = None
_launches:         int   = 0
_session_log_fh          = None

# --- Log buffer (shared between child-output reader and log window) -----------
_LOG_BUFFER_MAX = 5000
_log_buffer: deque[tuple[str, str]] = deque(maxlen=_LOG_BUFFER_MAX)
_log_lock   = threading.Lock()
_log_seq    = 0

# --- Auto-reload / hot-patch bookkeeping --------------------------------------
_POLL_INTERVAL = 0.5
_baseline:   dict[str, float] = {}
_last_poll:  float = 0.0

_jurigged_cache: dict[str, bool] = {}

# --- Live stats (daemon thread -> UI tick) ------------------------------------
_NO_WINDOW     = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_STATS_INTERVAL = 1.0
_stats:     dict[str, object] = {}
_stats_stop = threading.Event()

_cpu_cores      = os.cpu_count() or 1
_prev_cpu_secs: float | None = None
_prev_cpu_at:   float | None = None

_SPARK_LEN  = 60
_SPARK_W, _SPARK_H = 150, 30
_mem_hist: deque[float] = deque(maxlen=_SPARK_LEN)

# --- Watchdog state -----------------------------------------------------------
_cpu_hot_since: float | None = None
_wd_mem: deque[tuple[float, float]] = deque(maxlen=12)
_wd_msg: str = ""

# --- Test traffic light -------------------------------------------------------
_TEST_POLL    = 0.7
_TEST_TIMEOUT = 120
_test_state:   str = "none"
_test_summary: str = "—"
_test_stop    = threading.Event()
_test_request = threading.Event()

# --- Crash jump (deepest in-project frame of last crash) ----------------------
_crash_jump: dict[str, object] | None = None
_TRACE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_MAX_LOG_LINES = 800

# --- Editor preferences -------------------------------------------------------
_EDITORS  = ("code", "cursor", "subl")
_SKIP_DIRS = {"__pycache__", "build", "dist", "node_modules", "venv", "env", "ENV"}
_MAX_FILE_LINES = 700

# --- Theme colours (modern flat light) ----------------------------------------
_C_BG        = "#eef1f6"
_C_CARD      = "#ffffff"
_C_CARD2     = "#f4f6fa"
_C_BORDER    = "#e2e6ee"
_C_TEXT      = "#1b2230"
_C_ACCENT    = "#3b6fe0"
_C_ACCENT_HI = "#2f5fce"
_C_HDR       = "#3b6fe0"
_C_LBL       = "#7a828f"
_C_HOVER     = "#e7ecf6"
_C_OK        = "#1f9d57"
_C_BAD       = "#d24a3b"
_C_WARN      = "#c9912f"
_C_RED,  _C_DIM_RED = "#e22020", "#3b1414"
_C_YEL,  _C_DIM_YEL = "#f5b301", "#3b2f0a"
_C_GRN,  _C_DIM_GRN = "#19a821", "#103a16"

# --- Font stack (resolved once a tk.Tk() exists, by ui.theme._pick_font) ------
_FONT = "Segoe UI"
_MONO = "Cascadia Code"

_SYN: dict[str, str] = {
    "keyword": "#0b66c2",
    "string":  "#2a8a40",
    "comment": "#9aa0a8",
    "number":  "#a3551b",
    "def":     "#7a3fb0",
    "builtin": "#1f8fa3",
}
import builtins as _builtins_mod
_BUILTINS = set(dir(_builtins_mod))

# --- Ollama -------------------------------------------------------------------
_OLLAMA_HOST     = "http://192.168.50.100:11434"
_OLLAMA_DEFAULT  = "qwen2.5:14b"
_OLLAMA_FALLBACK = ["qwen2.5:14b", "llama3:latest"]
_OLLAMA_TIMEOUT  = 600
_FIRST_TOKEN     = 300
_STALL           = 90
_BACKUP_DIR      = ".harden_backups"

_CTX_MIN, _CTX_MAX = 4096, 16384
_CHARS_PER_TOKEN    = 3.5

# --- REPL ---------------------------------------------------------------------
_REPL_PORT = 8731
_REPL_SNIPPET = '''\
# --- ILX Launcher live REPL hook (dev-only; paste into your app startup) ---
def _start_dev_repl():
    import os, socket, threading, traceback
    from contextlib import redirect_stdout, redirect_stderr
    from io import StringIO
    if os.environ.get("ILX_DEV", "") != "1":
        return
    port = int(os.environ.get("ILX_REPL_PORT", "8731"))
    ns = globals(); ns["modules"] = __import__("sys").modules
    def serve():
        try:
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port)); s.listen(1)
        except OSError:
            return
        while True:
            try: c, _ = s.accept()
            except OSError: return
            with c:
                data = b""
                while not data.endswith(b"\\n\\x00"):
                    chunk = c.recv(4096)
                    if not chunk: break
                    data += chunk
                code = data.rstrip(b"\\n\\x00").decode("utf-8", "replace")
                buf = StringIO()
                try:
                    with redirect_stdout(buf), redirect_stderr(buf):
                        try:
                            r = eval(compile(code, "<repl>", "eval"), ns)
                            if r is not None: print(repr(r), file=buf)
                        except SyntaxError:
                            exec(compile(code, "<repl>", "exec"), ns)
                except Exception:
                    buf.write(traceback.format_exc())
                try: c.sendall(buf.getvalue().encode("utf-8", "replace") or b"(ok)\\n")
                except OSError: pass
    threading.Thread(target=serve, daemon=True).start()
# call _start_dev_repl() once at startup
'''

# --- Build --------------------------------------------------------------------
_APP_NAME      = "ILX Connection"
_ISCC_DEFAULT  = r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
_BUILD_TIMEOUT = 1200
_build_running  = False
_build_overlay  = "idle"
_build_progress: float = 0.0
_build_thread: threading.Thread | None = None

# --- Manual writing (kept for parity) -----------------------------------------
_MANUAL_FILE_PROMPT = (
    "You are writing the END-USER MANUAL for a desktop application called {app}.\n"
    "Below is the manual draft so far, then the SOURCE of one module. Update the manual to "
    "cover any USER-FACING features this module provides. Write for USERS, not developers.\n"
    "Return the COMPLETE updated manual in GitHub-flavored Markdown and nothing else.\n\n"
    "===== MANUAL SO FAR =====\n{manual}\n\n===== MODULE {rel} =====\n{content}\n"
)
_MANUAL_CONSOLIDATE_PROMPT = (
    "You are editing the END-USER MANUAL for {app}. Revise the manual below into a single "
    "coherent user guide: remove duplication, merge related sections, fix ordering.\n"
    "Return the COMPLETE revised manual in GitHub-flavored Markdown and nothing else.\n\n"
    "===== MANUAL =====\n{manual}\n"
)
_MANUAL_CONSOLIDATE_EVERY = 0.20
_manual_running  = False
_manual_stop     = threading.Event()
_manual_progress: float = 0.0
_manual_overlay: str    = "idle"
_manual_thread: threading.Thread | None = None

# --- Coder prompts ------------------------------------------------------------
_CODER_PROMPT = (
    "You are a precise coding assistant editing ONE file in an existing project.\n"
    "{digest}\n\n"
    "TARGET FILE: {rel}\n"
    "----- BEGIN FILE -----\n{content}\n----- END FILE -----\n\n"
    "INSTRUCTION:\n{instruction}\n\n"
    "Apply the instruction. Preserve all unrelated code and the public API.\n"
    "Return ONLY a JSON object -- no markdown, no prose, no code fences:\n"
    '{{"summary": "<what you changed>", "files": [{{"path": "{rel}", '
    '"action": "replace", "content": "<COMPLETE new file content>"}}]}}\n'
    "The content must be the entire file. Never use ellipsis or unchanged.\n"
)
_CODER_MAX_FIXES = 2
_CODER_FIX_PROMPT = (
    "You are fixing ONE file in an existing project. Your previous edit FAILED verification. "
    "Repair it so tests pass and the app still imports.\n"
    "{digest}\n\n"
    "TARGET FILE: {rel}\n"
    "----- BEGIN CURRENT FILE -----\n{content}\n----- END CURRENT FILE -----\n\n"
    "VERIFICATION FAILURE:\n{error}\n\n"
    "Return ONLY a JSON object -- no markdown, no prose, no code fences:\n"
    '{{"summary": "<what you fixed>", "files": [{{"path": "{rel}", '
    '"action": "replace", "content": "<COMPLETE fixed file content>"}}]}}\n'
    "The content must be the entire file. Never use ellipsis or unchanged.\n"
)
_CHAT_PROMPT = (
    "You are a senior engineer answering questions about ONE file in an existing project. "
    "Be precise and concise. When you propose a code change, show it in a ```python fenced "
    "block so it can be copied.\n"
    "{digest}\n\n"
    "FILE: {rel}\n----- BEGIN FILE -----\n{content}\n----- END FILE -----\n"
    "{selection}"
    "\nCONVERSATION SO FAR:\n{history}\n\n"
    "USER: {question}\nASSISTANT:"
)
_CHAT_SELECTION = (
    "\nThe user has SELECTED this portion of the file -- focus your answer on it:\n"
    "----- SELECTION -----\n{sel}\n----- END SELECTION -----\n"
)
_REVIEW_PROMPT = (
    "You are doing a thorough CODE REVIEW of ONE file in an existing project. Identify bugs, "
    "risky patterns, unclear names, missing error handling, and style issues. Then provide an "
    "improved version of the WHOLE file that addresses them without changing the public API.\n"
    "{digest}\n\n"
    "TARGET FILE: {rel}\n----- BEGIN FILE -----\n{content}\n----- END FILE -----\n\n"
    "Return ONLY a JSON object -- no markdown, no prose, no code fences:\n"
    '{{"summary": "<bulleted findings, newline-separated>", "files": [{{"path": "{rel}", '
    '"action": "replace", "content": "<COMPLETE improved file content>"}}]}}\n'
    "The content must be the entire file. Never use ellipsis or unchanged.\n"
)

import re as _re
_BLOCKED = [_re.compile(p) for p in (
    r"\brm\s+-rf\b",
    r"\bos\.system\s*\(",
    r"\bshutil\.rmtree\b",
    r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"__import__\s*\(",
)]
_MAX_EDIT_BYTES = 512 * 1024

# --- Coder / editor / chat runtime state -------------------------------------
_coder_running   = False
_coder_stop      = threading.Event()
_coder_status:   str = "idle"
_coder_proposal: dict | None = None
_coder_last_applied: dict | None = None
_coder_thread:   threading.Thread | None = None
_coder_loaded_rel: str | None = None
_chat_running    = False
_chat_history:   list[tuple[str, str]] = []
_chat_transcript: str = ""
_chat_last_code:  str | None = None
_pending_editor_text: str | None = None
_review_findings: str = ""

# --- Multi-process orchestration (Procfile) -----------------------------------
_orch:      dict[str, dict] = {}
_orch_lock  = threading.Lock()

# --- Bundled Python -----------------------------------------------------------
_PBS_TAG   = "20260610"
_PBS_ASSET = "cpython-3.12.13+20260610-x86_64-pc-windows-msvc-install_only.tar.gz"
_PBS_URL   = (f"https://github.com/astral-sh/python-build-standalone/releases/download/"
              f"{_PBS_TAG}/{_PBS_ASSET}")
_BUNDLE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ILX", "python")
_bundle_status       = "idle"
_bundle_downloading  = False

# --- Per-project interpreter --------------------------------------------------
_project_interp: str = ""

# --- UI widget indirection (main thread only) ---------------------------------
_ui: dict[str, object] = {}

# --- Traffic-light lamp geometry (computed once the canvas exists) -------------
_LAMP_H = 20

# --- Scaffold template files --------------------------------------------------
_SCAFFOLD_FILES: dict[str, str] = {
    "main.py": (
        '"""Entry point. Run via the ILX Launcher (Start) or: python main.py"""\n\n\n'
        "def main() -> None:\n"
        '    print("Hello from {name}!")\n\n\n'
        'if __name__ == "__main__":\n    main()\n'
    ),
    "version.py": (
        'PRODUCT_NAME = "{name}"\n'
        'VERSION = "2.0.0"\n'
        "VERSION_INFO = (2, 0, 0)\n"
    ),
    "requirements.txt": "# add your dependencies here, one per line\n",
    ".gitignore": ("__pycache__/\n*.py[cod]\n.venv/\n.env\nlog.txt\n"
                   ".launcher_session.log\n.launcher_crashes.db\nbuild/\ndist/\n"),
    ".env": "# KEY=VALUE per line; loaded into the app by the launcher\n",
    "test/test_smoke.py": (
        "def test_imports():\n"
        "    import main\n"
        "    assert hasattr(main, 'main')\n"
    ),
}

# --- Embedded pytest (god-file size guard) ------------------------------------
_EMBEDDED_GOD_FILE_TEST = '''\
"""Embedded by the ILX Launcher: architecture guard -- no file may exceed MAX_LINES lines."""
import os

MAX_LINES = 700
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "ENV", "build", "dist",
              ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules",
              ".harden_backups"}
_EXEMPT_FILES = {"launcher.py"}
_PROJECT_ROOT = os.environ.get("ILX_TEST_ROOT", os.getcwd())


def _iter_py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def test_no_file_exceeds_max_lines():
    offenders = []
    for path in _iter_py_files(_PROJECT_ROOT):
        if os.path.basename(path) in _EXEMPT_FILES:
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            n = sum(1 for _ in f)
        if n > MAX_LINES:
            offenders.append((os.path.relpath(path, _PROJECT_ROOT), n))
    offenders.sort(key=lambda t: -t[1])
    assert not offenders, "Files exceed %d lines:\\n%s" % (
        MAX_LINES, "\\n".join("  %s: %d" % (r, n) for r, n in offenders))
'''

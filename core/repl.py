from __future__ import annotations

import socket

import core.state as s
from core.process import is_running


def repl_eval(code: str) -> str:
    if not is_running():
        return "(start the app first - the REPL runs inside the live process)"
    try:
        with socket.create_connection(("127.0.0.1", s._REPL_PORT), timeout=5) as sock:
            sock.sendall(code.encode("utf-8") + b"\n\x00")
            chunks = []
            sock.settimeout(15)
            while True:
                b = sock.recv(4096)
                if not b:
                    break
                chunks.append(b)
        return b"".join(chunks).decode("utf-8", "replace").rstrip() or "(ok)"
    except (OSError, socket.timeout):
        return (
            "could not reach the app's REPL on 127.0.0.1:%d.\n"
            "Is the REPL hook wired? See Configuration > 'Copy REPL hook'." % s._REPL_PORT
        )

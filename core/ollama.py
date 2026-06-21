from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import core.state as s


def ollama_up(model: str) -> bool:
    try:
        with urllib.request.urlopen(s._OLLAMA_HOST + "/api/tags", timeout=5) as r:
            tags = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return any(m.get("name") == model for m in tags.get("models", []))


def ollama_models() -> list[str]:
    try:
        with urllib.request.urlopen(s._OLLAMA_HOST + "/api/tags", timeout=6) as r:
            data = json.loads(r.read().decode())
        names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return names or list(s._OLLAMA_FALLBACK)
    except (urllib.error.URLError, OSError, ValueError):
        return list(s._OLLAMA_FALLBACK)


def default_model(models: list[str]) -> str:
    if s._OLLAMA_DEFAULT in models:
        return s._OLLAMA_DEFAULT
    return models[0] if models else s._OLLAMA_DEFAULT


def llm_locked() -> bool:
    return os.path.exists(s._LOCK_FILE)


def acquire_lock(who: str) -> bool:
    try:
        fd = os.open(s._LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return True
    try:
        os.write(fd, who.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def release_lock() -> None:
    try:
        os.remove(s._LOCK_FILE)
    except OSError:
        pass


def ollama_stream(prompt: str, model: str, num_ctx: int,
                  on_progress=None, should_stop=None) -> str | None:
    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": True,
        "options": {"temperature": 0.2, "num_ctx": num_ctx},
    }).encode()
    req = urllib.request.Request(
        s._OLLAMA_HOST + "/api/generate", data=payload,
        headers={"Content-Type": "application/json"})
    chunks: list[str] = []
    ntok = 0
    try:
        resp = urllib.request.urlopen(req, timeout=s._FIRST_TOKEN)
        with resp:
            for raw in resp:
                if should_stop and should_stop():
                    return None
                if ntok == 1:
                    try:
                        resp.fp.raw._sock.settimeout(s._STALL)
                    except (AttributeError, OSError):
                        pass
                line = raw.decode("utf-8", "ignore").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                piece = obj.get("response", "")
                if piece:
                    chunks.append(piece)
                    ntok += 1
                    if on_progress:
                        on_progress(ntok, sum(len(c) for c in chunks))
                if obj.get("done"):
                    break
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        print(f"[launcher] ollama stream error: {e}")
        return None
    return "".join(chunks)

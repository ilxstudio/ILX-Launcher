from __future__ import annotations

import ast
import difflib
import os
import re
import shutil
import threading

import core.state as s
from core.ollama import acquire_lock, ollama_stream, release_lock
from core.process import source_files


# --- Source analysis ----------------------------------------------------------

def harden_targets() -> list[str]:
    test_dir = os.path.abspath(os.path.join(s._HERE, "test")) + os.sep
    return [p for p in source_files() if not os.path.abspath(p).startswith(test_dir)]


def file_api(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return []
    sigs: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            sigs.append(f"class {node.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and not node.name.startswith("_"):
            args = ", ".join(a.arg for a in node.args.args)
            sigs.append(f"def {node.name}({args})")
    return sigs


def project_digest(targets: list[str]) -> str:
    lines = ["PROJECT API MAP (signatures only - preserve these interfaces):"]
    for path in targets:
        rel = os.path.relpath(path, s._HERE)
        api = file_api(path)
        lines.append(f"  {rel}: " + ("; ".join(api) if api else "(no public API)"))
    return "\n".join(lines)


def ctx_for(*texts: str) -> int:
    chars = sum(len(t) for t in texts)
    need  = int(chars / s._CHARS_PER_TOKEN * 2.4)
    return max(s._CTX_MIN, min(s._CTX_MAX, need))


def set_coder_status(text: str) -> None:
    s._coder_status = text


# --- JSON parsing -------------------------------------------------------------

def _strip_fences(text: str) -> str:
    return re.sub(r"```[a-zA-Z0-9_+-]*\n?", "", text)


def balanced_json(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def json_unescape(raw: str) -> str:
    def repl(m):
        e = m.group(0)
        simple = {"\\n": "\n", "\\t": "\t", "\\r": "\r", '\\"': '"',
                  "\\\\": "\\", "\\/": "/", "\\b": "\b", "\\f": "\f"}
        if e in simple:
            return simple[e]
        if e[1] == "u":
            try:
                return chr(int(e[2:], 16))
            except ValueError:
                return e
        return e
    return re.sub(r"\\u[0-9a-fA-F]{4}|\\.", repl, raw)


def coder_parse_loose(raw: str) -> dict | None:
    text = _strip_fences(raw)
    cm = re.search(r'"content"\s*:\s*"', text)
    if not cm:
        return None
    cstart = cm.end()
    tail = text.find('"\n', cstart)
    end  = text.rfind('"', cstart, (tail if tail != -1 else len(text)) + 1)
    if end <= cstart:
        end = text.rfind('"')
    if end <= cstart:
        return None
    content = json_unescape(text[cstart:end])
    pm = re.search(r'"path"\s*:\s*"([^"]+)"', text)
    am = re.search(r'"action"\s*:\s*"([^"]+)"', text)
    sm = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if not pm or not content.strip():
        return None
    return {"summary": json_unescape(sm.group(1)) if sm else "",
            "files": [{"path": pm.group(1),
                       "action": am.group(1) if am else "replace",
                       "content": content}]}


def coder_parse(raw: str) -> dict | None:
    import json
    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))
    bal = balanced_json(_strip_fences(raw))
    if bal:
        candidates.append(bal)
    text = _strip_fences(raw).strip()
    s_idx, e_idx = text.find("{"), text.rfind("}")
    if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
        candidates.append(text[s_idx:e_idx + 1])
    for blob in candidates:
        for cand in (blob, re.sub(r",(\s*[}\]])", r"\1", blob)):
            try:
                obj = json.loads(cand)
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("files"), list):
                return obj
    return coder_parse_loose(raw)


# --- Validation ---------------------------------------------------------------

def _compiles(code: str, path: str) -> str:
    try:
        compile(code, path, "exec")
        return ""
    except SyntaxError as e:
        return str(e)


def coder_validate(files: list) -> tuple[bool, str]:
    if not files:
        return False, "model returned no files"
    for fa in files:
        if not isinstance(fa, dict):
            return False, "malformed file entry"
        path    = fa.get("path", "")
        content = fa.get("content", "")
        action  = fa.get("action", "replace")
        if action not in ("replace", "append"):
            return False, f"unsupported action '{action}'"
        parts = path.replace("\\", "/").split("/")
        if not path or os.path.isabs(path) or ":" in path or ".." in parts:
            return False, f"unsafe path '{path}'"
        full = os.path.abspath(os.path.join(s._HERE, path))
        if full != s._HERE and not full.startswith(s._HERE + os.sep):
            return False, f"path escapes project '{path}'"
        if not content:
            return False, f"empty content for '{path}'"
        if len(content.encode("utf-8")) > s._MAX_EDIT_BYTES:
            return False, f"'{path}' too large"
        for rx in s._BLOCKED:
            if rx.search(content):
                return False, f"blocked pattern in '{path}': {rx.pattern}"
    return True, ""


def unified_diff(old: str, new: str, rel: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{rel} (current)", tofile=f"{rel} (proposed)", lineterm="")
    return "\n".join(diff) or "(model returned identical content - no changes)"


# --- Editor helpers (main-thread only) ----------------------------------------

def editor_text() -> str:
    ed = s._ui.get("editor")
    try:
        return ed.get("1.0", "end-1c") if ed is not None else ""
    except Exception:
        return ""


def first_code_block(text: str) -> str | None:
    m = re.search(r"```[a-zA-Z0-9_+-]*\n(.*?)```", text, re.DOTALL)
    return m.group(1).rstrip("\n") if m else None


def set_editor_text(text: str) -> None:
    from ui.theme import highlight_editor
    ed = s._ui.get("editor")
    if ed is None:
        return
    ed.delete("1.0", "end")
    ed.insert("1.0", text)
    highlight_editor()


def load_into_editor(rel: str) -> None:
    path = os.path.join(s._HERE, rel)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        set_coder_status(f"cannot read {rel}: {e}")
        return
    s._coder_loaded_rel = rel
    set_editor_text(text)
    set_coder_status(f"loaded {rel}")


def on_coder_file_selected(event=None) -> None:
    combo = s._ui.get("file_combo")
    if combo is None:
        return
    s._chat_history    = []
    s._chat_transcript = ""
    s._chat_last_code  = None
    load_into_editor(combo.get())


def coder_refresh_files(select: str | None = None) -> None:
    combo = s._ui.get("file_combo")
    if combo is None:
        return
    rels = [os.path.relpath(p, s._HERE) for p in harden_targets()]
    combo["values"] = rels
    if select and select in rels:
        combo.set(select)


def coder_new_file() -> None:
    from tkinter import simpledialog
    rel = simpledialog.askstring("New file",
                                 "New .py file (path relative to the project):",
                                 initialvalue="new_module.py")
    if not rel:
        return
    rel  = rel.strip().replace("/", os.sep)
    if not rel.endswith(".py"):
        rel += ".py"
    path = os.path.join(s._HERE, rel)
    if not os.path.abspath(path).startswith(s._HERE + os.sep):
        set_coder_status("path escapes the project - not created")
        return
    if os.path.exists(path):
        set_coder_status(f"{rel} already exists - opening it")
    else:
        try:
            if os.path.dirname(rel):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f'"""{os.path.basename(rel)}"""\n')
            set_coder_status(f"created {rel}")
        except OSError as e:
            set_coder_status(f"could not create {rel}: {e}")
            return
    coder_refresh_files(rel)
    load_into_editor(rel)


def coder_new_folder() -> None:
    from tkinter import simpledialog
    rel = simpledialog.askstring("New folder",
                                 "New folder (path relative to the project):",
                                 initialvalue="package")
    if not rel:
        return
    path = os.path.join(s._HERE, rel.strip().replace("/", os.sep))
    if not os.path.abspath(path).startswith(s._HERE + os.sep):
        set_coder_status("path escapes the project - not created")
        return
    try:
        os.makedirs(path, exist_ok=True)
        init = os.path.join(path, "__init__.py")
        if not os.path.exists(init):
            with open(init, "w", encoding="utf-8") as f:
                f.write("")
        set_coder_status(f"created folder {rel}/ (with __init__.py)")
        coder_refresh_files()
    except OSError as e:
        set_coder_status(f"could not create folder: {e}")


def editor_reload_clicked() -> None:
    if s._coder_loaded_rel:
        load_into_editor(s._coder_loaded_rel)


# --- Coder workers (background threads) ---------------------------------------

def coder_verify() -> tuple[bool, str]:
    from core.automation import imports_ok, run_pytest
    state, summary = run_pytest()
    if state != "pass":
        return False, f"pytest: {summary}"
    imp_ok, imp_err = imports_ok()
    if not imp_ok:
        return False, f"import broke: {imp_err}"
    return True, summary


def coder_request_fix(rel: str, current: str, error: str, model: str) -> str | None:
    path   = os.path.join(s._HERE, rel)
    digest = project_digest(harden_targets())
    prompt = s._CODER_FIX_PROMPT.format(
        digest=digest, rel=rel.replace("\\", "/"), content=current, error=error)
    raw = ollama_stream(
        prompt, model, ctx_for(digest, current, error),
        on_progress=lambda nt, nc: set_coder_status(f"repairing... {nt} tok"),
        should_stop=s._coder_stop.is_set)
    if not raw or s._coder_stop.is_set():
        return None
    obj = coder_parse(raw)
    if not obj:
        return None
    ok, _ = coder_validate(obj.get("files", []))
    if not ok:
        return None
    new_content = obj["files"][0]["content"]
    if _compiles(new_content, path):
        return None
    return new_content


def coder_worker(rel: str, instruction: str, model: str, working_copy: str = "") -> None:
    s._coder_running  = True
    s._coder_proposal = None
    try:
        path     = os.path.join(s._HERE, rel)
        original = working_copy
        if not original:
            try:
                with open(path, encoding="utf-8") as f:
                    original = f.read()
            except OSError as e:
                set_coder_status(f"cannot read {rel}: {e}")
                return
        digest = project_digest(harden_targets())
        prompt = s._CODER_PROMPT.format(
            digest=digest, rel=rel.replace("\\", "/"),
            content=original, instruction=instruction)
        set_coder_status("generating...")
        raw = ollama_stream(
            prompt, model, ctx_for(digest, original, instruction),
            on_progress=lambda nt, nc: set_coder_status(f"generating... {nt} tok"),
            should_stop=s._coder_stop.is_set)
        if s._coder_stop.is_set():
            set_coder_status("cancelled")
            return
        if not raw:
            set_coder_status("no response (stalled or unreachable)")
            return
        obj = coder_parse(raw)
        if not obj:
            set_coder_status("could not parse the model's JSON")
            return
        ok, reason = coder_validate(obj.get("files", []))
        if not ok:
            set_coder_status("rejected - " + reason)
            return
        new_content = obj["files"][0]["content"]
        err = _compiles(new_content, path)
        if err:
            set_coder_status("rejected - proposed file does not compile")
            return
        s._coder_proposal = {
            "rel": rel, "path": path, "old": original, "new": new_content,
            "summary": obj.get("summary", ""),
            "diff": unified_diff(original, new_content, rel)}
        set_coder_status("ready - review the diff, then Apply")
    finally:
        s._coder_running = False


def coder_apply_worker() -> None:
    import datetime
    p = s._coder_proposal
    if not p:
        return
    s._coder_running = True
    locked = False
    try:
        if not acquire_lock("coder apply"):
            set_coder_status("another LLM write is in progress - try again shortly")
            return
        locked  = True
        model   = str(s._ui.get("coder_model") or s._OLLAMA_DEFAULT)
        set_coder_status("backing up + applying...")
        ts    = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bpath = os.path.join(s._HERE, s._BACKUP_DIR, "coder", ts, p["rel"])
        try:
            os.makedirs(os.path.dirname(bpath), exist_ok=True)
            shutil.copy2(p["path"], bpath)
        except OSError:
            pass
        content     = p["new"]
        last_reason = ""
        for attempt in range(s._CODER_MAX_FIXES + 1):
            if s._coder_stop.is_set():
                last_reason = "cancelled"
                break
            try:
                with open(p["path"], "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError as e:
                last_reason = f"write failed: {e}"
                break
            tag = "verifying" if attempt == 0 else f"verifying fix {attempt}"
            set_coder_status(f"{tag} (pytest + import)...")
            ok, reason = coder_verify()
            if ok:
                kept = dict(p); kept["new"] = content
                s._coder_last_applied = kept
                s._coder_proposal     = None
                note = "applied OK" if attempt == 0 else f"self-healed in {attempt} fix(es)"
                set_coder_status(f"{note} - tests: {reason}")
                return
            last_reason = reason
            if attempt == s._CODER_MAX_FIXES:
                break
            set_coder_status(f"verify failed ({reason}) - asking model to fix...")
            fixed = coder_request_fix(p["rel"], content, reason, model)
            if not fixed:
                last_reason = reason + " (no usable fix returned)"
                break
            content = fixed
        try:
            with open(p["path"], "w", encoding="utf-8") as f:
                f.write(p["old"])
        except OSError:
            pass
        set_coder_status(f"reverted - {last_reason}")
    finally:
        if locked:
            release_lock()
        s._coder_running = False


def editor_save_worker(rel: str, text: str) -> None:
    import datetime
    s._coder_running = True
    locked = False
    try:
        if not acquire_lock("editor save"):
            set_coder_status("another LLM write is in progress - try again shortly")
            return
        locked = True
        path = os.path.join(s._HERE, rel)
        err  = _compiles(text, path)
        if err:
            set_coder_status(f"not saved - does not compile: {err}")
            return
        try:
            with open(path, encoding="utf-8") as f:
                original = f.read()
        except OSError:
            original = ""
        ts    = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bpath = os.path.join(s._HERE, s._BACKUP_DIR, "editor", ts, rel)
        try:
            os.makedirs(os.path.dirname(bpath), exist_ok=True)
            if original:
                with open(bpath, "w", encoding="utf-8") as f:
                    f.write(original)
        except OSError:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            set_coder_status(f"write failed: {e}")
            return
        set_coder_status("saved - verifying (pytest + import)...")
        ok, reason = coder_verify()
        if ok:
            s._coder_last_applied = {"rel": rel, "path": path, "old": original, "new": text}
            set_coder_status(f"saved + verified - tests: {reason}")
        else:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(original)
            except OSError:
                pass
            set_coder_status(f"reverted - {reason}")
    finally:
        if locked:
            release_lock()
        s._coder_running = False


# --- Button actions (main-thread entry points) --------------------------------

def coder_submit() -> None:
    if s._coder_running:
        return
    rel         = s._coder_loaded_rel
    instruction = str(s._ui.get("instruction") or "").strip()
    model       = str(s._ui.get("coder_model") or s._OLLAMA_DEFAULT)
    if not rel or not instruction:
        set_coder_status("pick a file and type an instruction")
        return
    working = editor_text()
    s._coder_stop.clear()
    s._coder_thread = threading.Thread(
        target=coder_worker, args=(rel, instruction, model, working), daemon=True)
    s._coder_thread.start()


def coder_apply_clicked() -> None:
    if s._coder_running or not s._coder_proposal:
        return
    s._coder_thread = threading.Thread(target=coder_apply_worker, daemon=True)
    s._coder_thread.start()


def coder_undo_clicked() -> None:
    if s._coder_running or not s._coder_last_applied:
        return
    p = s._coder_last_applied
    try:
        with open(p["path"], "w", encoding="utf-8") as f:
            f.write(p["old"])
        set_coder_status(f"undone - {p['rel']} restored")
        if p["rel"] == s._coder_loaded_rel:
            load_into_editor(p["rel"])
    except OSError as e:
        set_coder_status(f"undo failed: {e}")


def editor_save_clicked() -> None:
    if s._coder_running or not s._coder_loaded_rel:
        set_coder_status("pick a file first")
        return
    text = editor_text()
    s._coder_stop.clear()
    s._coder_thread = threading.Thread(
        target=editor_save_worker, args=(s._coder_loaded_rel, text), daemon=True)
    s._coder_thread.start()


# --- Chat ---------------------------------------------------------------------

def chat_worker(rel: str, question: str, selection: str, model: str,
                editor_text_snap: str = "") -> None:
    s._chat_running = True
    try:
        digest  = "(answer based on the file shown below)"
        sel     = s._CHAT_SELECTION.format(sel=selection) if selection.strip() else ""
        history = "\n".join(f"{r.upper()}: {t}" for r, t in s._chat_history[-6:])
        prompt  = s._CHAT_PROMPT.format(
            digest=digest, rel=rel.replace("\\", "/"), content=editor_text_snap,
            selection=sel, history=history or "(none)", question=question)
        s._chat_history.append(("you", question))
        s._chat_transcript += f"\nYou: {question}\n"
        answer = ollama_stream(
            prompt, model, ctx_for(editor_text_snap, question, selection),
            on_progress=lambda nt, nc: set_coder_status(f"thinking... {nt} tok"),
            should_stop=s._coder_stop.is_set)
        if not answer or s._coder_stop.is_set():
            set_coder_status("no response (stalled or cancelled)")
            return
        answer = answer.strip()
        s._chat_history.append(("ai", answer))
        s._chat_transcript += f"\nAI: {answer}\n"
        code = first_code_block(answer)
        s._chat_last_code = code
        set_coder_status("answer ready" + ("  (code block available)" if code else ""))
    finally:
        s._chat_running = False


def chat_send_clicked() -> None:
    if s._chat_running or s._coder_running:
        return
    if not s._coder_loaded_rel:
        set_coder_status("pick a file first")
        return
    inp      = s._ui.get("chat_input")
    question = (inp.get("1.0", "end-1c").strip() if inp is not None else "")
    if not question:
        set_coder_status("type a question")
        return
    selb      = s._ui.get("chat_selection")
    selection = (selb.get("1.0", "end-1c") if selb is not None else "")
    model     = str(s._ui.get("coder_model") or s._OLLAMA_DEFAULT)
    working   = editor_text()
    if inp is not None:
        inp.delete("1.0", "end")
    s._coder_stop.clear()
    s._coder_thread = threading.Thread(
        target=chat_worker,
        args=(s._coder_loaded_rel, question, selection, model, working), daemon=True)
    s._coder_thread.start()


def chat_code_to_editor() -> None:
    if s._chat_last_code:
        s._pending_editor_text = s._chat_last_code
        set_coder_status("AI code loaded into the editor - review, then Save to disk")
    else:
        set_coder_status("no code block in the last answer")


# --- Review -------------------------------------------------------------------

def review_worker(rel: str, model: str, editor_text_snap: str = "") -> None:
    s._coder_running  = True
    s._coder_proposal = None
    try:
        path   = os.path.join(s._HERE, rel)
        digest = "(review the single file shown below)"
        prompt = s._REVIEW_PROMPT.format(
            digest=digest, rel=rel.replace("\\", "/"), content=editor_text_snap)
        set_coder_status("reviewing...")
        raw = ollama_stream(
            prompt, model, ctx_for(editor_text_snap),
            on_progress=lambda nt, nc: set_coder_status(f"reviewing... {nt} tok"),
            should_stop=s._coder_stop.is_set)
        if not raw or s._coder_stop.is_set():
            set_coder_status("no response (stalled or cancelled)")
            return
        obj = coder_parse(raw)
        if not obj:
            set_coder_status("could not parse the review")
            return
        ok, reason = coder_validate(obj.get("files", []))
        if not ok:
            set_coder_status("rejected - " + reason)
            return
        new_content = obj["files"][0]["content"]
        err = _compiles(new_content, path)
        if err:
            set_coder_status("rejected - proposed file does not compile")
            return
        s._coder_proposal = {
            "rel": rel, "path": path, "old": editor_text_snap, "new": new_content,
            "summary": obj.get("summary", ""),
            "diff": unified_diff(editor_text_snap, new_content, rel)}
        s._review_findings = obj.get("summary", "(no findings text)")
        set_coder_status("review ready - see findings, then Apply or load into editor")
    finally:
        s._coder_running = False


def review_clicked() -> None:
    if s._coder_running or not s._coder_loaded_rel:
        set_coder_status("pick a file first")
        return
    model   = str(s._ui.get("coder_model") or s._OLLAMA_DEFAULT)
    working = editor_text()
    s._coder_stop.clear()
    s._coder_thread = threading.Thread(
        target=review_worker, args=(s._coder_loaded_rel, model, working), daemon=True)
    s._coder_thread.start()


def proposal_to_editor() -> None:
    if s._coder_proposal:
        s._pending_editor_text = s._coder_proposal["new"]
        set_coder_status("proposal loaded into the editor - review, then Save to disk")

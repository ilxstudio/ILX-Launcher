from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

import core.state as s
from core.config import load_config
from core.coder import (
    coder_apply_clicked, coder_new_file, coder_new_folder, coder_refresh_files,
    coder_submit, coder_undo_clicked, chat_code_to_editor, chat_send_clicked,
    editor_reload_clicked, editor_save_clicked, on_coder_file_selected,
    proposal_to_editor, review_clicked, set_coder_status,
)
from core.interpreter import project_python
from core.ollama import default_model, ollama_models
from ui.theme import (
    config_syntax_tags, highlight_editor, make_code_text, set_readonly, style_theme,
)


def _coder_tick(root: tk.Tk) -> None:
    if s._pending_editor_text is not None:
        from core.coder import set_editor_text
        set_editor_text(s._pending_editor_text)
        s._pending_editor_text = None

    lbl = s._ui.get("coder_status_lbl")
    if lbl is not None:
        lbl.configure(text=s._coder_status)

    diff_key = (s._coder_proposal or {}).get("diff")
    if s._ui.get("_diff_shown") != diff_key:
        set_readonly("coder_diff", s._coder_proposal["diff"] if s._coder_proposal else "")
        s._ui["_diff_shown"] = diff_key

    if s._ui.get("_chat_shown") != s._chat_transcript:
        set_readonly("chat_log", s._chat_transcript.strip())
        s._ui["_chat_shown"] = s._chat_transcript

    if s._ui.get("_findings_shown") != s._review_findings:
        set_readonly("review_findings", s._review_findings)
        s._ui["_findings_shown"] = s._review_findings

    mw = s._ui.get("coder_model_widget")
    if mw is not None:
        s._ui["coder_model"] = mw.get()
    iw = s._ui.get("instruction_widget")
    if iw is not None:
        s._ui["instruction"] = iw.get("1.0", "end-1c")

    busy     = s._coder_running or s._chat_running
    has_prop = bool(s._coder_proposal)

    def en(key, ok):
        w = s._ui.get(key)
        if w is not None:
            w.configure(state=("normal" if ok else "disabled"))

    en("gen_btn",      not busy)
    en("ask_btn",      not busy)
    en("review_btn",   not busy)
    en("apply_btn",    has_prop and not busy)
    en("edit_to_ed",   has_prop and not busy)
    en("review_apply", has_prop and not busy)
    en("review_to_ed", has_prop and not busy)
    en("chat_to_ed",   bool(s._chat_last_code) and not busy)
    en("undo_btn",     bool(s._coder_last_applied) and not busy)

    root.after(150, lambda: _coder_tick(root))


def run_coder() -> int:
    load_config()
    root = tk.Tk()
    root.title("ILX Coder")
    root.geometry("1180x780")
    style_theme(root)

    models = ollama_models()

    top = ttk.Frame(root); top.pack(fill="x", padx=10, pady=(10, 4))
    ttk.Label(top, text="File", style="Lbl.TLabel").pack(side="left")
    rels = [os.path.relpath(p, s._HERE) for p in
            __import__("core.coder", fromlist=["harden_targets"]).harden_targets()]
    file_combo = ttk.Combobox(top, values=rels, width=42, state="readonly")
    file_combo.pack(side="left", padx=(4, 12))
    file_combo.bind("<<ComboboxSelected>>", on_coder_file_selected)
    s._ui["file_combo"] = file_combo

    ttk.Label(top, text="Model", style="Lbl.TLabel").pack(side="left")
    model_combo = ttk.Combobox(top, values=models, width=24, state="readonly")
    model_combo.set(default_model(models))
    model_combo.pack(side="left", padx=(4, 12))
    s._ui["coder_model_widget"] = model_combo

    ttk.Button(top, text="Close",      command=root.destroy).pack(side="right")
    ttk.Button(top, text="New folder", command=coder_new_folder).pack(side="right", padx=4)
    ttk.Button(top, text="New file",   command=coder_new_file).pack(side="right")

    status = ttk.Label(root, text="idle", style="Hdr.TLabel")
    status.pack(fill="x", padx=10)
    s._ui["coder_status_lbl"] = status

    body = ttk.Frame(root); body.pack(fill="both", expand=True, padx=10, pady=8)

    # Left: editable working copy with live syntax highlighting.
    left = ttk.Frame(body, width=580); left.pack(side="left", fill="both", expand=True)
    left.pack_propagate(False)
    ttk.Label(left, text="Editor (your working copy)", style="Hdr.TLabel").pack(anchor="w")
    lbtns = ttk.Frame(left); lbtns.pack(fill="x", pady=2)
    ttk.Button(lbtns, text="Save to disk", command=editor_save_clicked).pack(side="left")
    ttk.Button(lbtns, text="Reload",       command=editor_reload_clicked).pack(
        side="left", padx=4)
    undo_btn = ttk.Button(lbtns, text="Undo last", command=coder_undo_clicked)
    undo_btn.pack(side="left")
    s._ui["undo_btn"] = undo_btn
    editor = make_code_text(left, readonly=False, height=30)
    config_syntax_tags(editor)
    editor.bind("<KeyRelease>", highlight_editor)
    s._ui["editor"] = editor

    # Right: tabbed tools.
    right = ttk.Frame(body, width=540)
    right.pack(side="left", fill="both", expand=True, padx=(10, 0))
    nb = ttk.Notebook(right); nb.pack(fill="both", expand=True)

    # Edit tab.
    edit_tab = ttk.Frame(nb); nb.add(edit_tab, text="Edit")
    ttk.Label(edit_tab, text="Describe a change; the model rewrites the file. Review the "
              "diff, load it into the editor, then Save.", style="Lbl.TLabel",
              wraplength=480).pack(anchor="w", pady=(6, 2))
    instruction = make_code_text(edit_tab, height=4)
    instruction.configure(font=(s._FONT, 10))
    s._ui["instruction_widget"] = instruction
    ebtns = ttk.Frame(edit_tab); ebtns.pack(fill="x", pady=4)
    gen_btn   = ttk.Button(ebtns, text="Generate",       command=coder_submit)
    apply_btn = ttk.Button(ebtns, text="Apply directly", command=coder_apply_clicked)
    edit_to_ed = ttk.Button(ebtns, text="Load to editor", command=proposal_to_editor)
    gen_btn.pack(side="left")
    apply_btn.pack(side="left", padx=4)
    edit_to_ed.pack(side="left")
    s._ui["gen_btn"] = gen_btn
    s._ui["apply_btn"] = apply_btn
    s._ui["edit_to_ed"] = edit_to_ed
    ttk.Label(edit_tab, text="Proposed diff", style="Lbl.TLabel").pack(anchor="w")
    diff = make_code_text(edit_tab, readonly=True, height=14)
    s._ui["coder_diff"] = diff

    # Chat tab.
    chat_tab = ttk.Frame(nb); nb.add(chat_tab, text="Chat")
    ttk.Label(chat_tab, text="Ask about this file. Optionally paste a selected snippet.",
              style="Lbl.TLabel", wraplength=480).pack(anchor="w", pady=(6, 2))
    ttk.Label(chat_tab, text="Selection (optional)", style="Lbl.TLabel").pack(anchor="w")
    chat_sel = make_code_text(chat_tab, height=4)
    s._ui["chat_selection"] = chat_sel
    ttk.Label(chat_tab, text="Question", style="Lbl.TLabel").pack(anchor="w")
    chat_in = make_code_text(chat_tab, height=3)
    chat_in.configure(font=(s._FONT, 10))
    s._ui["chat_input"] = chat_in
    cbtns = ttk.Frame(chat_tab); cbtns.pack(fill="x", pady=4)
    ask_btn    = ttk.Button(cbtns, text="Ask",           command=chat_send_clicked)
    chat_to_ed = ttk.Button(cbtns, text="Code -> editor", command=chat_code_to_editor)
    ask_btn.pack(side="left")
    chat_to_ed.pack(side="left", padx=4)
    s._ui["ask_btn"]    = ask_btn
    s._ui["chat_to_ed"] = chat_to_ed
    ttk.Label(chat_tab, text="Conversation", style="Lbl.TLabel").pack(anchor="w")
    chat_log = make_code_text(chat_tab, readonly=True, height=12)
    chat_log.configure(font=(s._FONT, 10), wrap="word")
    s._ui["chat_log"] = chat_log

    # Review tab.
    rev_tab = ttk.Frame(nb); nb.add(rev_tab, text="Review")
    ttk.Label(rev_tab, text="The model reviews the file and proposes an improved version. "
              "Apply (self-healing) or load it into the editor.",
              style="Lbl.TLabel", wraplength=480).pack(anchor="w", pady=(6, 2))
    rbtns = ttk.Frame(rev_tab); rbtns.pack(fill="x", pady=4)
    review_btn    = ttk.Button(rbtns, text="Review file",    command=review_clicked)
    review_apply  = ttk.Button(rbtns, text="Apply directly", command=coder_apply_clicked)
    review_to_ed  = ttk.Button(rbtns, text="Load to editor", command=proposal_to_editor)
    review_btn.pack(side="left")
    review_apply.pack(side="left", padx=4)
    review_to_ed.pack(side="left")
    s._ui["review_btn"]   = review_btn
    s._ui["review_apply"] = review_apply
    s._ui["review_to_ed"] = review_to_ed
    ttk.Label(rev_tab, text="Findings", style="Lbl.TLabel").pack(anchor="w")
    findings = make_code_text(rev_tab, readonly=True, height=16)
    findings.configure(font=(s._FONT, 10), wrap="word")
    s._ui["review_findings"] = findings

    if rels:
        file_combo.set(rels[0])
        from core.coder import load_into_editor
        load_into_editor(rels[0])

    _coder_tick(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (s._coder_stop.set(), root.destroy()))
    root.mainloop()
    return 0

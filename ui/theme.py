from __future__ import annotations

import keyword
import subprocess
import threading
import tokenize
from io import StringIO

import tkinter as tk
from tkinter import ttk

import core.state as s


# --- Font resolution ----------------------------------------------------------

def pick_font() -> None:
    try:
        from tkinter import font as tkfont
        fams = set(tkfont.families())
    except tk.TclError:
        return
    for f in ("Segoe UI Variable", "Segoe UI", "Inter", "Helvetica Neue", "Arial"):
        if f in fams:
            s._FONT = f
            break
    for f in ("Cascadia Code", "Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"):
        if f in fams:
            s._MONO = f
            break


# --- Theme application --------------------------------------------------------

def style_theme(root: tk.Tk) -> None:
    pick_font()
    root.configure(bg=s._C_BG)
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass

    f_base  = (s._FONT, 10)
    f_small = (s._FONT, 9)
    f_hdr   = (s._FONT, 9, "bold")
    f_title = (s._FONT, 13, "bold")

    st.configure(".", background=s._C_BG, foreground=s._C_TEXT,
                 fieldbackground=s._C_CARD, bordercolor=s._C_BORDER, font=f_base,
                 focuscolor=s._C_BG)
    st.configure("TFrame",       background=s._C_BG)
    st.configure("Card.TFrame",  background=s._C_CARD)
    st.configure("TLabel",       background=s._C_BG, foreground=s._C_TEXT, font=f_base)
    st.configure("Title.TLabel", background=s._C_BG, foreground=s._C_TEXT, font=f_title)
    st.configure("Hdr.TLabel",   background=s._C_BG, foreground=s._C_LBL,  font=f_hdr)
    st.configure("Ver.TLabel",   background=s._C_BG, foreground=s._C_ACCENT, font=f_hdr)
    st.configure("Lbl.TLabel",   background=s._C_BG, foreground=s._C_LBL,  font=f_small)

    st.configure("TButton", background=s._C_CARD2, foreground=s._C_TEXT, borderwidth=0,
                 focuscolor=s._C_BG, padding=(12, 7), font=f_base, relief="flat",
                 anchor="center")
    st.map("TButton",
           background=[("pressed", s._C_BORDER), ("active", s._C_HOVER),
                       ("disabled", s._C_BG)],
           foreground=[("disabled", "#b6bcc4")])

    st.configure("Accent.TButton", background=s._C_ACCENT, foreground="#ffffff",
                 borderwidth=0, focuscolor=s._C_ACCENT, padding=(12, 7),
                 font=(s._FONT, 10, "bold"), relief="flat", anchor="center")
    st.map("Accent.TButton",
           background=[("pressed", s._C_ACCENT_HI), ("active", s._C_ACCENT_HI),
                       ("disabled", "#a9bdec")],
           foreground=[("disabled", "#eef2fb")])

    st.configure("TCheckbutton", background=s._C_BG, foreground=s._C_TEXT, font=f_small,
                 focuscolor=s._C_BG)
    st.map("TCheckbutton", background=[("active", s._C_BG)],
           indicatorcolor=[("selected", s._C_ACCENT), ("!selected", s._C_CARD)])

    st.configure("TNotebook", background=s._C_BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
    st.configure("TNotebook.Tab", background=s._C_BG, foreground=s._C_LBL,
                 padding=(16, 7), borderwidth=0, font=f_small)
    st.map("TNotebook.Tab",
           background=[("selected", s._C_CARD)],
           foreground=[("selected", s._C_ACCENT), ("active", s._C_TEXT)],
           expand=[("selected", (0, 0, 0, 0))])

    st.configure("TCombobox", fieldbackground=s._C_CARD, background=s._C_CARD,
                 bordercolor=s._C_BORDER, arrowcolor=s._C_LBL, padding=4, relief="flat")
    st.map("TCombobox", fieldbackground=[("readonly", s._C_CARD)],
           bordercolor=[("focus", s._C_ACCENT)])
    st.configure("TEntry", fieldbackground=s._C_CARD, bordercolor=s._C_BORDER, padding=5,
                 relief="flat")
    st.map("TEntry", bordercolor=[("focus", s._C_ACCENT)])
    st.configure("TSeparator", background=s._C_BORDER)
    st.configure("Horizontal.TProgressbar", background=s._C_ACCENT, troughcolor=s._C_CARD2,
                 borderwidth=0, thickness=8)
    try:
        root.option_add("*TCombobox*Listbox.background", s._C_CARD)
        root.option_add("*TCombobox*Listbox.foreground", s._C_TEXT)
        root.option_add("*TCombobox*Listbox.selectBackground", s._C_ACCENT)
        root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        root.option_add("*TCombobox*Listbox.font", f_base)
    except tk.TclError:
        pass


# --- Widget factory helpers ---------------------------------------------------

def make_code_text(parent: tk.Widget, readonly: bool = False, height: int = 10) -> tk.Text:
    wrap = tk.Frame(parent, bg=s._C_BORDER)
    wrap.pack(fill="both", expand=True)
    inner = tk.Frame(wrap, bg=s._C_CARD)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    sb  = ttk.Scrollbar(inner)
    sb.pack(side="right", fill="y")
    txt = tk.Text(inner, wrap="none", undo=True, height=height,
                  bg=s._C_CARD, fg=s._C_TEXT, insertbackground=s._C_ACCENT,
                  selectbackground="#d4e2fb", selectforeground=s._C_TEXT, relief="flat",
                  font=(s._MONO, 10), yscrollcommand=sb.set, padx=8, pady=6,
                  borderwidth=0, highlightthickness=0)
    txt.pack(side="left", fill="both", expand=True)
    sb.config(command=txt.yview)
    if readonly:
        txt.configure(state="disabled")
    return txt


def card(parent: tk.Widget, title: str) -> ttk.Frame:
    outer = tk.Frame(parent, bg=s._C_BORDER)
    outer.pack(side="left", anchor="n", fill="y", padx=(0, 0))
    inner = tk.Frame(outer, bg=s._C_CARD, padx=12, pady=8)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    tk.Label(inner, text=title, bg=s._C_CARD, fg=s._C_LBL,
             font=(s._FONT, 9, "bold")).pack(anchor="w", pady=(0, 6))
    return inner


def stat_row(parent: tk.Widget, label: str, key: str, ui: dict) -> None:
    row = tk.Frame(parent, bg=s._C_CARD)
    row.pack(anchor="w", fill="x", pady=1)
    tk.Label(row, text=label + ":", bg=s._C_CARD, fg=s._C_LBL,
             font=(s._FONT, 9), width=9, anchor="w").pack(side="left")
    lbl = tk.Label(row, text="—", bg=s._C_CARD, fg=s._C_TEXT, font=(s._FONT, 9))
    lbl.pack(side="left")
    ui[key] = lbl


def shade(color: str, factor: float) -> str:
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    r = min(255, int(r * factor))
    g = min(255, int(g * factor))
    b = min(255, int(b * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


# --- Traffic light ------------------------------------------------------------

def build_traffic_light(cv: tk.Canvas) -> None:
    housing = s._C_CARD2
    cv.create_rectangle(6, 4, 38, 120, fill=housing, outline=s._C_BORDER, width=1)
    for key, y in (("red", 20), ("yel", 62), ("grn", 100)):
        dark = {"red": "#4a0000", "yel": "#3a3000", "grn": "#004a00"}[key]
        cv.create_oval(10, y, 34, y + 24, fill=dark, outline="", tags=key)
        cv.create_oval(16, y + 3, 24, y + 9, fill="", outline="", tags=f"{key}_hi")


def set_lamp(cv: tk.Canvas, key: str, on: bool) -> None:
    colors = {"red": ("#ff3b30", "#ff8a84"), "yel": ("#ffcc00", "#ffe680"),
              "grn": ("#34c759", "#90e8a8")}
    dark   = {"red": "#4a0000", "yel": "#3a3000", "grn": "#004a00"}
    if on:
        cv.itemconfig(key, fill=colors[key][0])
        cv.itemconfig(f"{key}_hi", fill=colors[key][1])
    else:
        cv.itemconfig(key, fill=dark[key])
        cv.itemconfig(f"{key}_hi", fill="")


# --- Readonly text helper -----------------------------------------------------

def set_readonly(key: str, text: str) -> None:
    w = s._ui.get(key)
    if w is None:
        return
    try:
        w.configure(state="normal")
        w.delete("1.0", "end")
        w.insert("1.0", text)
        w.configure(state="disabled")
    except tk.TclError:
        pass


def set_text(widget: tk.Text, text: str) -> None:
    try:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
    except tk.TclError:
        pass


# --- Syntax highlighting ------------------------------------------------------

def config_syntax_tags(text_widget: tk.Text) -> None:
    for name, color in s._SYN.items():
        text_widget.tag_configure(name, foreground=color)
    text_widget.tag_configure("comment", foreground=s._SYN["comment"])


def safe_tokens(src: str) -> list:
    out: list = []
    for i, line in enumerate(src.splitlines(), start=1):
        try:
            for tok in tokenize.generate_tokens(StringIO(line + "\n").readline):
                ttype, tstr, (sr, sc), (er, ec), _ = tok
                out.append((ttype, tstr, (i, sc), (i, ec), line))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            continue
    return out


def highlight_editor(event=None) -> None:
    ed = s._ui.get("editor")
    if ed is None:
        return
    src = ed.get("1.0", "end-1c")
    for tag in s._SYN:
        ed.tag_remove(tag, "1.0", "end")
    try:
        tokens = list(tokenize.generate_tokens(StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        tokens = safe_tokens(src)
    prev_kw = ""
    for tok in tokens:
        ttype, tstr, (srow, scol), (erow, ecol), _ = tok
        start = f"{srow}.{scol}"
        end   = f"{erow}.{ecol}"
        tag   = None
        if ttype == tokenize.COMMENT:
            tag = "comment"
        elif ttype == tokenize.STRING:
            tag = "string"
        elif ttype == tokenize.NUMBER:
            tag = "number"
        elif ttype == tokenize.NAME:
            if keyword.iskeyword(tstr):
                tag = "keyword"
            elif prev_kw in ("def", "class"):
                tag = "def"
            elif tstr in s._BUILTINS:
                tag = "builtin"
        if tag:
            try:
                ed.tag_add(tag, start, end)
            except tk.TclError:
                pass
        if ttype == tokenize.NAME and keyword.iskeyword(tstr):
            prev_kw = tstr
        elif ttype not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                           tokenize.DEDENT):
            prev_kw = ""


# --- Async tool runner --------------------------------------------------------

def tool_window(title: str, fn, *args, width: int = 700, height: int = 500) -> None:
    win = tk.Toplevel()
    win.title(title)
    win.geometry(f"{width}x{height}")
    out = make_code_text(win, readonly=True)
    config_syntax_tags(out)

    def worker():
        try:
            result = fn(*args)
        except Exception as e:
            result = f"error: {e}"
        win.after(0, lambda: set_text(out, str(result)))

    threading.Thread(target=worker, daemon=True).start()


def run_tool_async(title: str, fn, *args) -> None:
    tool_window(title, fn, *args)


def pip_command(cmd: str) -> str:
    from core.automation import pip_command as _pip
    return _pip(cmd)

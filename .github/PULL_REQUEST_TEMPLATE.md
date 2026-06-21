## What does this PR do?

Short description.

## Checklist

- [ ] No file exceeds 700 lines
- [ ] No third-party imports added to `core/` or `ui/` (stdlib + tkinter only)
- [ ] All `print()` output is ASCII-only (no em-dashes, ellipsis, smart quotes)
- [ ] Any new subprocess call uses `creationflags=s._NO_WINDOW`
- [ ] New Python spawns route through `tool_python()` / `project_python()` with the `_SELF` guard
- [ ] License of any new dependency is MIT / BSD / Apache / PSF / OFL (no copyleft)
- [ ] Smoke test passes: `python -c "import importlib.util as u; s=u.spec_from_file_location('l','launcher.py'); m=u.module_from_spec(s); s.loader.exec_module(m)"`
- [ ] CHANGELOG.md updated (if user-visible change)

## Testing

Describe how you tested this.
